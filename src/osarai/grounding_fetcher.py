"""Récupération documentaire MediaWiki filtrée par liste blanche (`CC BY-SA` / `Etalab 2.0`)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import httpx

from osarai import USER_AGENT, ExitCode, OsaraiError
from osarai.schemas import (
    WHITESPACE_RE,
    SourcesPolicy,
    TextSourceCredit,
    normalize_hostname,
    normalize_search_text,
)
from osarai.yaml_io import dump_yaml_roundtrip

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5
MAX_GROUNDING_BYTES = 40 * 1024
WIKI_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)


@dataclass(frozen=True)
class MediaWikiSearchHit:
    """Résultat de recherche sur un wiki autorisé (`fr.vikidia.org`, `fr.wikipedia.org`)."""

    title: str
    url: str
    domain: str
    snippet: str
    wordcount: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "snippet": self.snippet,
            "wordcount": self.wordcount,
        }


@dataclass(frozen=True)
class GroundingDocument:
    """Extrait encyclopédique nettoyé (`<= 40 Ko`) accompagné de son crédit TASL complet."""

    title: str
    url: str
    source_domain: str
    section: str | None
    text: str
    truncated: bool
    byte_length: int
    credit: TextSourceCredit

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source_domain": self.source_domain,
            "section": self.section,
            "text": self.text,
            "truncated": self.truncated,
            "byte_length": self.byte_length,
            "credit": self.credit.model_dump(mode="json"),
        }


class _HtmlTextStripper(HTMLParser):
    """Supprime toutes les balises HTML ainsi que le contenu des blocs `<script>` et `<style>`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html_tags(text: str) -> str:
    """Nettoie tout HTML/script résiduel d'une chaîne."""
    stripper = _HtmlTextStripper()
    stripper.feed(text)
    stripper.close()
    return stripper.get_text()


def _parse_retry_after(headers: httpx.Headers) -> int:
    raw = headers.get("retry-after", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return 60


def _assert_grounding_allowed(url: str, sources: SourcesPolicy) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise OsaraiError(
            f"URL HTTPS requise pour `fetch-grounding` : {url!r}",
            ExitCode.LICENSE_DISALLOWED,
            details={"url": url},
        )
    host = normalize_hostname(url)
    rule = sources.find_domain_rule(url)
    if rule is None or not rule.allow_grounding or rule.adapter != "mediawiki_text":
        raise OsaraiError(
            f"Domaine `{host}` interdit pour `fetch-grounding` selon `sources.yaml`.",
            ExitCode.LICENSE_DISALLOWED,
            details={"url": url, "domain": host},
        )
    return host


def _get_json_with_policy_redirects(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None,
    sources: SourcesPolicy,
) -> tuple[str, dict[str, Any]]:
    current_url = url
    current_params = params
    for _hop in range(MAX_REDIRECTS + 1):
        _assert_grounding_allowed(current_url, sources)
        try:
            resp = client.get(current_url, params=current_params)
        except httpx.HTTPError as exc:
            raise OsaraiError(
                f"Erreur réseau MediaWiki sur {current_url} : {exc}",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"url": current_url},
            ) from exc

        if resp.status_code in REDIRECT_STATUSES:
            loc = resp.headers.get("location", "").strip()
            if not loc:
                raise OsaraiError(
                    f"Redirection HTTP {resp.status_code} sans `Location` sur {current_url}.",
                    ExitCode.LICENSE_DISALLOWED,
                    details={"url": current_url},
                )
            current_url = urljoin(str(resp.request.url), loc)
            current_params = None
            continue

        if resp.status_code in {403, 429}:
            raise OsaraiError(
                f"Limitation de débit MediaWiki (HTTP {resp.status_code}) sur {current_url}.",
                ExitCode.RATE_LIMITED,
                details={
                    "url": current_url,
                    "status_code": resp.status_code,
                    "retry_after_seconds": _parse_retry_after(resp.headers),
                },
            )
        if resp.status_code in {404, 410}:
            raise OsaraiError(
                f"Ressource MediaWiki introuvable (HTTP {resp.status_code}) : {current_url}",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"url": current_url, "status_code": resp.status_code},
            )
        if resp.status_code >= 400:
            raise OsaraiError(
                f"Erreur HTTP {resp.status_code} depuis MediaWiki ({current_url}).",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"url": current_url, "status_code": resp.status_code},
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise OsaraiError(
                f"Réponse JSON MediaWiki invalide sur {current_url}.",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"url": current_url},
            ) from exc
        if not isinstance(payload, dict):
            raise OsaraiError(
                f"Objet JSON attendu depuis MediaWiki ({current_url}).",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"url": current_url},
            )
        return normalize_hostname(str(resp.request.url)), payload

    raise OsaraiError(
        f"Trop de redirections HTTP (> {MAX_REDIRECTS}) depuis {url}.",
        ExitCode.LICENSE_DISALLOWED,
        details={"url": url},
    )


def _resolve_rightsinfo_license(
    rightsinfo: dict[str, Any],
    sources: SourcesPolicy,
) -> tuple[str, str]:
    raw_url = str(rightsinfo.get("url") or "").strip()
    raw_text = str(rightsinfo.get("text") or "").strip()
    if raw_url.startswith("//"):
        license_url = f"https:{raw_url}"
    else:
        license_url = raw_url

    haystack = f"{license_url} {raw_text}".lower()
    candidates: list[tuple[tuple[str, ...], str, str]] = [
        (
            ("by-sa/4.0", "by-sa 4.0"),
            "CC-BY-SA-4.0",
            "https://creativecommons.org/licenses/by-sa/4.0/",
        ),
        (
            ("by-sa/3.0", "by-sa 3.0"),
            "CC-BY-SA-3.0",
            "https://creativecommons.org/licenses/by-sa/3.0/",
        ),
        (
            ("by-sa/2.5", "by-sa 2.5"),
            "CC-BY-SA-2.5",
            "https://creativecommons.org/licenses/by-sa/2.5/",
        ),
        (
            ("by-sa/2.0", "by-sa 2.0"),
            "CC-BY-SA-2.0",
            "https://creativecommons.org/licenses/by-sa/2.0/",
        ),
        (("by/4.0", "cc by 4.0"), "CC-BY-4.0", "https://creativecommons.org/licenses/by/4.0/"),
        (("by/3.0", "cc by 3.0"), "CC-BY-3.0", "https://creativecommons.org/licenses/by/3.0/"),
        (("by/2.5", "cc by 2.5"), "CC-BY-2.5", "https://creativecommons.org/licenses/by/2.5/"),
        (("by/2.0", "cc by 2.0"), "CC-BY-2.0", "https://creativecommons.org/licenses/by/2.0/"),
        (
            ("publicdomain/zero/1.0", "cc0"),
            "CC0-1.0",
            "https://creativecommons.org/publicdomain/zero/1.0/",
        ),
        (
            ("publicdomain/mark/1.0", "public domain"),
            "CC-PDM-1.0",
            "https://creativecommons.org/publicdomain/mark/1.0/",
        ),
        (
            ("etalab", "licence-ouverte", "open-licence"),
            "Etalab-2.0",
            "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
        ),
    ]

    matched_spdx: str | None = None
    default_url: str = ""
    for patterns, spdx, fallback_url in candidates:
        if any(pat in haystack for pat in patterns):
            matched_spdx = spdx
            default_url = fallback_url
            break

    if matched_spdx is None or matched_spdx not in set(sources.allowed_licenses):
        raise OsaraiError(
            f"Licence MediaWiki non autorisée ou non reconnue : {raw_text!r} ({raw_url!r}).",
            ExitCode.LICENSE_DISALLOWED,
            details={"rights_text": raw_text, "rights_url": raw_url},
        )

    final_url = license_url if license_url.startswith("https://") else default_url
    return matched_spdx, final_url


def _extract_wiki_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path.startswith("/wiki/"):
        raw_title = unquote(parsed.path[len("/wiki/") :]).strip()
        if raw_title:
            return raw_title.replace("_", " ")
    if parsed.query:
        qs = parse_qs(parsed.query)
        titles = qs.get("title")
        if titles and titles[0].strip():
            return titles[0].strip().replace("_", " ")
    raise OsaraiError(
        f"Impossible d'extraire le titre d'article MediaWiki depuis l'URL {url!r}.",
        ExitCode.VALIDATION_ERROR,
        details={"url": url},
    )


def _slice_wiki_section(full_text: str, section_name: str) -> str:
    target_norm = normalize_search_text(section_name)
    matches = list(WIKI_HEADING_RE.finditer(full_text))
    for idx, match in enumerate(matches):
        level = len(match.group(1))
        heading_title = match.group(2).strip()
        if normalize_search_text(heading_title) == target_norm:
            start_pos = match.start()
            end_pos = len(full_text)
            for next_match in matches[idx + 1 :]:
                if len(next_match.group(1)) <= level:
                    end_pos = next_match.start()
                    break
            return full_text[start_pos:end_pos].strip()

    raise OsaraiError(
        f"Sous-section `== {section_name} ==` introuvable dans l'article.",
        ExitCode.UPSTREAM_NOT_FOUND,
        details={"section": section_name},
    )


def _truncate_utf8(text: str, max_bytes: int = MAX_GROUNDING_BYTES) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    clipped = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    return clipped, True


def search_grounding(
    query: str,
    sources: SourcesPolicy,
    domain: str | None = None,
    limit: int = 5,
) -> list[MediaWikiSearchHit]:
    """Recherche des articles encyclopédiques sur les domaines `mediawiki_text` autorisés."""
    cleaned_query = query.strip()
    if not cleaned_query:
        raise OsaraiError("La requête `--search` ne peut pas être vide.", ExitCode.VALIDATION_ERROR)

    if domain is not None:
        norm_dom = normalize_hostname(domain)
        _assert_grounding_allowed(f"https://{norm_dom}/w/api.php", sources)
        target_domains = [norm_dom]
    else:
        target_domains = [
            rule.domain
            for rule in sources.grounding_and_media_sources
            if rule.allow_grounding and rule.adapter == "mediawiki_text"
        ]

    hits: list[MediaWikiSearchHit] = []
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=15.0,
    ) as client:
        for dom in target_domains:
            api_url = f"https://{dom}/w/api.php"
            params = {
                "action": "query",
                "list": "search",
                "srsearch": cleaned_query,
                "srlimit": max(1, min(limit, 20)),
                "format": "json",
            }
            resolved_dom, payload = _get_json_with_policy_redirects(
                client, api_url, params, sources
            )
            search_items = payload.get("query", {}).get("search", [])
            if not isinstance(search_items, list):
                continue
            for item in search_items[:limit]:
                if not isinstance(item, dict) or not item.get("title"):
                    continue
                title = str(item["title"]).strip()
                encoded_slug = quote(title.replace(" ", "_"), safe=":_()-")
                raw_snippet = str(item.get("snippet") or "")
                clean_snippet = WHITESPACE_RE.sub(" ", strip_html_tags(raw_snippet)).strip()
                hits.append(
                    MediaWikiSearchHit(
                        title=title,
                        url=f"https://{resolved_dom}/wiki/{encoded_slug}",
                        domain=resolved_dom,
                        snippet=clean_snippet,
                        wordcount=int(item.get("wordcount") or 0),
                    )
                )
    return hits


def fetch_grounding(
    url: str,
    sources: SourcesPolicy,
    section: str | None = None,
    theme_dir: Path | None = None,
) -> GroundingDocument:
    """Récupère un extrait MediaWiki (`<= 40 Ko`) et enregistre son crédit TASL dans `meta.yaml`."""
    host = _assert_grounding_allowed(url, sources)
    requested_title = _extract_wiki_title_from_url(url)

    api_url = f"https://{host}/w/api.php"
    params = {
        "action": "query",
        "redirects": "1",
        "titles": requested_title,
        "prop": "extracts|revisions",
        "meta": "siteinfo",
        "siprop": "rightsinfo",
        "explaintext": "1",
        "exsectionformat": "wiki",
        "rvprop": "ids|timestamp",
        "format": "json",
    }

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=20.0,
    ) as client:
        resolved_host, payload = _get_json_with_policy_redirects(client, api_url, params, sources)

    query_obj = payload.get("query")
    if not isinstance(query_obj, dict):
        raise OsaraiError(
            f"Réponse MediaWiki incomplète pour {url}.",
            ExitCode.UPSTREAM_NOT_FOUND,
            details={"url": url},
        )

    rightsinfo = query_obj.get("rightsinfo")
    if not isinstance(rightsinfo, dict):
        raise OsaraiError(
            f"Métadonnées de licence `query.rightsinfo` absentes sur {resolved_host}.",
            ExitCode.LICENSE_DISALLOWED,
            details={"url": url},
        )
    license_spdx, license_url = _resolve_rightsinfo_license(rightsinfo, sources)

    pages = query_obj.get("pages")
    if not isinstance(pages, dict) or not pages:
        raise OsaraiError(
            f"Aucune page retournée par MediaWiki pour `{requested_title}`.",
            ExitCode.UPSTREAM_NOT_FOUND,
            details={"url": url},
        )

    page_obj = next(iter(pages.values()))
    if (
        not isinstance(page_obj, dict)
        or "missing" in page_obj
        or str(page_obj.get("pageid", "-1")) == "-1"
    ):
        raise OsaraiError(
            f"Article MediaWiki introuvable : `{requested_title}`.",
            ExitCode.UPSTREAM_NOT_FOUND,
            details={"url": url, "title": requested_title},
        )

    canonical_title = str(page_obj.get("title") or requested_title).strip()
    raw_extract = str(page_obj.get("extract") or "")
    if section is not None:
        raw_extract = _slice_wiki_section(raw_extract, section)

    cleaned_text = strip_html_tags(raw_extract).strip()
    truncated_text, was_truncated = _truncate_utf8(cleaned_text, MAX_GROUNDING_BYTES)
    byte_len = len(truncated_text.encode("utf-8"))

    revisions = page_obj.get("revisions")
    revision_or_date = datetime.now(UTC).date().isoformat()
    if isinstance(revisions, list) and revisions and isinstance(revisions[0], dict):
        rev0 = revisions[0]
        if rev0.get("revid") is not None:
            revision_or_date = str(rev0["revid"])
        elif isinstance(rev0.get("timestamp"), str) and rev0["timestamp"]:
            revision_or_date = rev0["timestamp"][:10]

    encoded_title = quote(canonical_title.replace(" ", "_"), safe=":_()-")
    canonical_article_url = f"https://{resolved_host}/wiki/{encoded_title}"
    history_url = f"https://{resolved_host}/wiki/Special:History/{encoded_title}"
    wiki_label = "Vikidia" if "vikidia" in resolved_host else "Wikipédia"

    credit = TextSourceCredit(
        title=f"{canonical_title} — {wiki_label}",
        url=canonical_article_url,
        source_domain=resolved_host,
        authors_or_history_url=history_url,
        license_spdx=license_spdx,
        license_url=license_url,
        revision_or_date=revision_or_date,
    )

    if theme_dir is not None:
        meta_path = theme_dir / "meta.yaml"
        credit_dict = credit.model_dump(mode="json")

        def _upsert_source_credit(doc: Any) -> None:
            if not isinstance(doc, dict):
                return
            sources_list = doc.setdefault("sources_used", [])
            for idx, existing in enumerate(sources_list):
                if isinstance(existing, dict) and existing.get("url") == credit.url:
                    sources_list[idx] = credit_dict
                    return
            sources_list.append(credit_dict)

        dump_yaml_roundtrip(meta_path, _upsert_source_credit)

    return GroundingDocument(
        title=canonical_title,
        url=canonical_article_url,
        source_domain=resolved_host,
        section=section,
        text=truncated_text,
        truncated=was_truncated,
        byte_length=byte_len,
        credit=credit,
    )
