"""Découverte, téléchargement vérifié et extraction tabulaire des PDF officiels Éduscol."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import httpx
import pdfplumber

from osarai import USER_AGENT, ExitCode, OsaraiError
from osarai.schemas import SLUG_RE, WHITESPACE_RE, BoManifest, SourcesPolicy
from osarai.yaml_io import dump_yaml_roundtrip, load_yaml

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5
DRUPAL_DOWNLOAD_RE = re.compile(r"^/document/[^/]+/download/?$", re.IGNORECASE)


@dataclass(frozen=True)
class DiscoveredPdfLink:
    """Hyperlien PDF détecté sur une page sommaire ministérielle Éduscol."""

    title: str
    url: str
    source_kind: Literal["pdf_ext", "drupal_download"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True)
class PdfExtractionMetadata:
    """Métadonnées d'extraction d'un document PDF du Bulletin Officiel."""

    title: str
    url: str
    pdf_path: str
    markdown_path: str
    sha256: str
    pages: int
    tables_extracted: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "pdf_path": self.pdf_path,
            "markdown_path": self.markdown_path,
            "sha256": self.sha256,
            "pages": self.pages,
            "tables_extracted": self.tables_extracted,
        }


class _AnchorExtractor(HTMLParser):
    """Extrait les couples `(href, texte)` des balises `<a ...>` d'une page HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_fallback: str = ""
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        href = attr_map.get("href", "").strip()
        if href:
            self._current_href = href
            self._current_fallback = (
                attr_map.get("title", "").strip() or attr_map.get("aria-label", "").strip()
            )
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current_href is not None:
            label = WHITESPACE_RE.sub(" ", "".join(self._chunks)).strip()
            if not label:
                label = WHITESPACE_RE.sub(" ", self._current_fallback).strip()
            self.links.append((self._current_href, label))
            self._current_href = None
            self._current_fallback = ""
            self._chunks = []


def _parse_retry_after(headers: httpx.Headers) -> int:
    raw = headers.get("retry-after", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return 60


def _assert_eduscol_bo_url(url: str, sources: SourcesPolicy) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise OsaraiError(
            f"Schéma HTTPS requis pour Éduscol : {url!r}",
            ExitCode.LICENSE_DISALLOWED,
            details={"url": url},
        )
    rule = sources.find_domain_rule(url)
    if rule is None or rule.adapter != "eduscol_bo" or not rule.allow_grounding:
        raise OsaraiError(
            f"Domaine `{parsed.hostname}` non autorisé pour `eduscol_bo` dans `sources.yaml`.",
            ExitCode.LICENSE_DISALLOWED,
            details={"url": url},
        )


def _raise_for_upstream_status(resp: httpx.Response, url: str) -> None:
    status = resp.status_code
    if status in {403, 429}:
        retry_after = _parse_retry_after(resp.headers)
        raise OsaraiError(
            f"Accès limité ou filtré par le serveur distant (HTTP {status}) sur {url}.",
            ExitCode.RATE_LIMITED,
            details={"url": url, "status_code": status, "retry_after_seconds": retry_after},
        )
    if status in {404, 410}:
        raise OsaraiError(
            f"Ressource distante introuvable (HTTP {status}) : {url}",
            ExitCode.UPSTREAM_NOT_FOUND,
            details={"url": url, "status_code": status},
        )
    if status >= 400:
        raise OsaraiError(
            f"Erreur HTTP {status} lors du téléchargement de {url}.",
            ExitCode.UPSTREAM_NOT_FOUND,
            details={"url": url, "status_code": status},
        )


def _fetch_eduscol_bytes(
    client: httpx.Client,
    url: str,
    sources: SourcesPolicy,
) -> tuple[str, httpx.Headers, bytes]:
    current = url.strip()
    for _hop in range(MAX_REDIRECTS + 1):
        _assert_eduscol_bo_url(current, sources)
        try:
            resp = client.get(current)
        except httpx.HTTPError as exc:
            raise OsaraiError(
                f"Erreur réseau sur {current} : {exc}",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"url": current},
            ) from exc

        if resp.status_code in REDIRECT_STATUSES:
            location = resp.headers.get("location", "").strip()
            if not location:
                raise OsaraiError(
                    f"Redirection HTTP {resp.status_code} sans en-tête `Location` sur {current}.",
                    ExitCode.LICENSE_DISALLOWED,
                    details={"url": current},
                )
            current = urljoin(current, location)
            continue

        _raise_for_upstream_status(resp, current)
        return current, resp.headers, resp.content

    raise OsaraiError(
        f"Trop de redirections HTTP (> {MAX_REDIRECTS}) depuis {url}.",
        ExitCode.LICENSE_DISALLOWED,
        details={"url": url},
    )


def _confirm_pdf_content_type(
    client: httpx.Client,
    url: str,
    sources: SourcesPolicy,
) -> tuple[bool, str]:
    """Vérifie via les en-têtes HTTP qu'une route `/document/<id>/download` sert un PDF."""
    current = url.strip()
    for _hop in range(MAX_REDIRECTS + 1):
        _assert_eduscol_bo_url(current, sources)
        try:
            resp = client.head(current)
        except httpx.HTTPError:
            return False, current

        if resp.status_code == 405:
            try:
                with client.stream("GET", current) as stream_resp:
                    if stream_resp.status_code in REDIRECT_STATUSES:
                        loc = stream_resp.headers.get("location", "").strip()
                        if not loc:
                            return False, current
                        current = urljoin(current, loc)
                        continue
                    if stream_resp.status_code != 200:
                        return False, current
                    ctype = stream_resp.headers.get("content-type", "").lower()
                    return "application/pdf" in ctype, current
            except httpx.HTTPError:
                return False, current

        if resp.status_code in REDIRECT_STATUSES:
            loc = resp.headers.get("location", "").strip()
            if not loc:
                return False, current
            current = urljoin(current, loc)
            continue

        if resp.status_code != 200:
            return False, current
        ctype = resp.headers.get("content-type", "").lower()
        return "application/pdf" in ctype, current

    return False, current


def _slugify_title(text: str) -> str:
    lowered = text.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return cleaned[:60].strip("-") or "document"


def discover_eduscol_pdfs(page_url: str, sources: SourcesPolicy) -> list[DiscoveredPdfLink]:
    """Liste les hyperliens PDF (`.pdf` et `/document/<id>/download`) d'une page Éduscol."""
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=20.0,
    ) as client:
        final_page_url, _headers, raw_html = _fetch_eduscol_bytes(client, page_url, sources)
        html_text = raw_html.decode("utf-8", errors="replace")

        parser = _AnchorExtractor()
        parser.feed(html_text)

        discovered: list[DiscoveredPdfLink] = []
        seen_urls: set[str] = set()

        for href, raw_label in parser.links:
            abs_url = urljoin(final_page_url, href).split("#", 1)[0].strip()
            parsed = urlparse(abs_url)
            if parsed.scheme != "https" or not parsed.netloc:
                continue
            rule = sources.find_domain_rule(abs_url)
            if rule is None or rule.adapter != "eduscol_bo" or not rule.allow_grounding:
                continue
            if abs_url in seen_urls:
                continue

            path_lower = parsed.path.lower()
            if path_lower.endswith(".pdf"):
                seen_urls.add(abs_url)
                fallback_title = Path(parsed.path).stem.replace("-", " ").replace("_", " ")
                discovered.append(
                    DiscoveredPdfLink(
                        title=raw_label or fallback_title or "Document PDF",
                        url=abs_url,
                        source_kind="pdf_ext",
                    )
                )
            elif DRUPAL_DOWNLOAD_RE.match(parsed.path):
                is_pdf, resolved_url = _confirm_pdf_content_type(client, abs_url, sources)
                if is_pdf and resolved_url not in seen_urls:
                    seen_urls.add(abs_url)
                    seen_urls.add(resolved_url)
                    discovered.append(
                        DiscoveredPdfLink(
                            title=raw_label or "Document officiel Éduscol",
                            url=abs_url,
                            source_kind="drupal_download",
                        )
                    )

    return discovered


def _format_markdown_table(rows: list[list[str | None]]) -> str:
    cleaned_rows: list[list[str]] = []
    max_cols = 0
    for row in rows:
        if not row:
            continue
        cells = [WHITESPACE_RE.sub(" ", (cell or "")).strip().replace("|", r"\|") for cell in row]
        if any(cells):
            cleaned_rows.append(cells)
            max_cols = max(max_cols, len(cells))

    if not cleaned_rows or max_cols == 0:
        return ""

    padded = [r + [""] * (max_cols - len(r)) for r in cleaned_rows]
    header = "| " + " | ".join(padded[0]) + " |"
    separator = "| " + " | ".join(["---"] * max_cols) + " |"
    body_lines = ["| " + " | ".join(r) + " |" for r in padded[1:]]
    return "\n".join([header, separator, *body_lines])


def _clean_layout_text(raw_text: str | None) -> str:
    if not raw_text:
        return ""
    lines = [line.rstrip() for line in raw_text.splitlines()]
    compact: list[str] = []
    blank_streak = 0
    for line in lines:
        if not line.strip():
            blank_streak += 1
            if blank_streak <= 1 and compact:
                compact.append("")
        else:
            blank_streak = 0
            compact.append(re.sub(r"[ \t]{2,}", " ", line.strip()))
    return "\n".join(compact).strip()


def _infer_repo_root_from_manifest(manifest_path: Path) -> Path:
    resolved = manifest_path.resolve()
    if len(resolved.parts) >= 3 and resolved.parts[-3:-1] == ("curriculum", "sources"):
        return resolved.parents[2]
    return resolved.parent


def sync_and_extract_bo(
    manifest_path: Path,
    cycle: str,
    subject: str,
    sources: SourcesPolicy,
) -> list[PdfExtractionMetadata]:
    """Télécharge, vérifie le `sha256` et extrait en Markdown tabulaire les PDF d'une matière."""
    if not SLUG_RE.match(cycle) or not SLUG_RE.match(subject):
        raise OsaraiError(
            f"Couple `(cycle, subject)` invalide : ({cycle!r}, {subject!r}).",
            ExitCode.VALIDATION_ERROR,
        )

    raw_manifest = load_yaml(manifest_path)
    try:
        manifest = BoManifest.model_validate(raw_manifest)
    except Exception as exc:
        raise OsaraiError(
            f"`bo_manifest.yaml` invalide ({manifest_path}) : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(manifest_path)},
        ) from exc

    subj_idx: int | None = None
    target_subject = None
    for idx, entry in enumerate(manifest.subjects):
        if entry.cycle == cycle and entry.subject == subject:
            subj_idx = idx
            target_subject = entry
            break

    if target_subject is None or subj_idx is None:
        raise OsaraiError(
            f"Aucune entrée `({cycle}, {subject})` trouvée dans `{manifest_path}`.",
            ExitCode.VALIDATION_ERROR,
            details={"cycle": cycle, "subject": subject},
        )

    repo_root = _infer_repo_root_from_manifest(manifest_path)
    pdfs_dir = repo_root / ".osarai_tmp" / "bo_pdfs"
    texts_dir = repo_root / ".osarai_tmp" / "bo_texts" / f"{cycle}-{subject}"
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    texts_dir.mkdir(parents=True, exist_ok=True)

    results: list[PdfExtractionMetadata] = []
    updated_shas: dict[int, str] = {}

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=30.0,
    ) as client:
        for doc_num, doc in enumerate(target_subject.documents, start=1):
            _final_url, _headers, pdf_bytes = _fetch_eduscol_bytes(client, doc.url, sources)
            actual_sha = hashlib.sha256(pdf_bytes).hexdigest()

            if doc.sha256 is not None and doc.sha256 != actual_sha:
                raise OsaraiError(
                    f"Empreinte `sha256` discordante pour `{doc.title}` "
                    f"(attendu {doc.sha256}, reçu {actual_sha}).",
                    ExitCode.VALIDATION_ERROR,
                    details={"url": doc.url, "expected_sha256": doc.sha256, "sha256": actual_sha},
                )
            if doc.sha256 is None:
                updated_shas[doc_num - 1] = actual_sha

            doc_slug = _slugify_title(doc.title)
            pdf_file = pdfs_dir / f"{cycle}-{subject}-{doc_num:02d}-{doc_slug}.pdf"
            pdf_file.write_bytes(pdf_bytes)

            md_sections: list[str] = [
                f"# {doc.title}",
                "",
                f"- **Cycle** : `{cycle}`",
                f"- **Matière** : `{subject}`",
                f"- **Type** : `{doc.doc_type}`",
                f"- **Date de publication** : `{doc.publication_date.isoformat()}`",
                f"- **URL officielle** : {doc.url}",
                f"- **SHA-256** : `{actual_sha}`",
                "",
            ]

            table_count = 0
            with pdfplumber.open(pdf_file) as pdf:
                page_count = len(pdf.pages)
                for p_num, page in enumerate(pdf.pages, start=1):
                    md_sections.append(f"## Page {p_num}")
                    md_sections.append("")

                    found_tables = page.find_tables()
                    bboxes = [tbl.bbox for tbl in found_tables]
                    if bboxes:

                        def _outside_tables(
                            obj: dict[str, Any],
                            boxes: list[tuple[float, float, float, float]] = bboxes,
                        ) -> bool:
                            ox0 = float(obj.get("x0", 0.0))
                            otop = float(obj.get("top", 0.0))
                            ox1 = float(obj.get("x1", ox0))
                            obottom = float(obj.get("bottom", otop))
                            cx = (ox0 + ox1) / 2.0
                            cy = (otop + obottom) / 2.0
                            return not any(
                                bx0 - 1.0 <= cx <= bx1 + 1.0 and btop - 1.0 <= cy <= bbot + 1.0
                                for bx0, btop, bx1, bbot in boxes
                            )

                        outside_page = page.filter(_outside_tables)
                    else:
                        outside_page = page

                    prose_text = _clean_layout_text(outside_page.extract_text(layout=True))
                    if prose_text:
                        md_sections.append(prose_text)
                        md_sections.append("")

                    raw_tables = page.extract_tables()
                    for raw_tbl in raw_tables:
                        md_tbl = _format_markdown_table(raw_tbl)
                        if md_tbl:
                            table_count += 1
                            md_sections.append(md_tbl)
                            md_sections.append("")

            md_file = texts_dir / f"{doc_num:02d}-{doc_slug}.md"
            md_file.write_text("\n".join(md_sections).rstrip() + "\n", encoding="utf-8")

            results.append(
                PdfExtractionMetadata(
                    title=doc.title,
                    url=doc.url,
                    pdf_path=str(pdf_file),
                    markdown_path=str(md_file),
                    sha256=actual_sha,
                    pages=page_count,
                    tables_extracted=table_count,
                )
            )

    if updated_shas:
        s_index = subj_idx

        def _write_shas(doc_yaml: Any) -> None:
            docs_node = doc_yaml["subjects"][s_index]["documents"]
            for d_idx, new_sha in updated_shas.items():
                docs_node[d_idx]["sha256"] = new_sha

        dump_yaml_roundtrip(manifest_path, _write_shas)

    return results
