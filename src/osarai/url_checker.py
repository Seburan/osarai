"""Vérificateur HTTP asynchrone de liens externes (`probe-links` et `check-urls`)."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx
from ruamel.yaml import YAML

from osarai import USER_AGENT, ExitCode
from osarai.id_manager import resolve_merge_base
from osarai.schemas import (
    WHITESPACE_RE,
    ResourcesFile,
    SourcesPolicy,
    normalize_channel_url,
    normalize_hostname,
)
from osarai.yaml_io import load_yaml

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5
MAX_PROBE_HTML_BYTES = 64 * 1024
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_OEMBED_URL = "https://www.youtube.com/oembed"
TRACKING_PARAMS = frozenset({"fbclid", "si", "feature"})
SOFT_404_PATTERNS: tuple[str, ...] = (
    "404",
    "page introuvable",
    "page non trouvée",
    "page non trouvee",
    "not found",
    "erreur 404",
)

ProbeVerdict = Literal["ok", "dead", "soft_404", "rate_limited", "disallowed", "error"]


@dataclass(frozen=True)
class UrlProbeResult:
    """Résultat unitaire de sondage d'en-têtes/`oEmbed` d'une URL externe (sans corps d'article)."""

    input_url: str
    canonical_url: str
    source_domain: str
    status: int | None
    ok: bool
    verdict: ProbeVerdict
    exit_code: ExitCode
    title: str | None = None
    h1: str | None = None
    channel_url: str | None = None
    is_youtube: bool = False
    reason: str | None = None
    retry_after_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "input_url": self.input_url,
            "canonical_url": self.canonical_url,
            "source_domain": self.source_domain,
            "status": self.status,
            "ok": self.ok,
            "verdict": self.verdict,
            "exit_code": int(self.exit_code),
            "title": self.title,
            "h1": self.h1,
            "channel_url": self.channel_url,
            "is_youtube": self.is_youtube,
            "reason": self.reason,
        }
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        return payload


@dataclass
class UrlCheckSummary:
    """Bilan global d'exécution de `check_repository_urls`."""

    checked_at: str
    checked_count: int = 0
    dead_links: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    exit_code: ExitCode = ExitCode.OK

    @property
    def ok(self) -> bool:
        return self.exit_code == ExitCode.OK

    def to_report_dict(self) -> dict[str, Any]:
        """Format canonique de `--json-report` (`link-report.json`)."""
        return {
            "checked_at": self.checked_at,
            "dead_links": self.dead_links,
            "warnings": self.warnings,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "exit_code": int(self.exit_code),
            "checked_at": self.checked_at,
            "checked_count": self.checked_count,
            "dead_links": self.dead_links,
            "warnings": self.warnings,
        }


class _TitleAndH1Parser(HTMLParser):
    """Extrait uniquement `<title>` et le premier `<h1>` sans conserver le reste du document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._in_first_h1 = False
        self._h1_done = False
        self._ignored_depth = 0
        self._title_parts: list[str] = []
        self._h1_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth > 0:
            return
        if t == "title":
            self._in_title = True
        elif t == "h1" and not self._h1_done:
            self._in_first_h1 = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style"} and self._ignored_depth > 0:
            self._ignored_depth -= 1
            return
        if t == "title":
            self._in_title = False
        elif t == "h1" and self._in_first_h1:
            self._in_first_h1 = False
            self._h1_done = True

    def handle_data(self, data: str) -> None:
        if self._ignored_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._in_first_h1:
            self._h1_parts.append(data)

    @property
    def title(self) -> str:
        return WHITESPACE_RE.sub(" ", "".join(self._title_parts)).strip()

    @property
    def first_h1(self) -> str:
        return WHITESPACE_RE.sub(" ", "".join(self._h1_parts)).strip()


def _parse_retry_after(headers: httpx.Headers) -> int:
    raw = headers.get("retry-after", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return 60


def _extract_youtube_video_id(parsed: Any) -> str | None:
    host = normalize_hostname(parsed.netloc)
    path = parsed.path.strip("/")
    candidate: str | None = None

    if host == "youtu.be":
        first_seg = path.split("/", 1)[0]
        candidate = first_seg
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if path == "watch":
            qs = parse_qs(parsed.query)
            vals = qs.get("v")
            if vals:
                candidate = vals[0]
        elif path.startswith(("shorts/", "embed/", "v/")):
            parts = path.split("/")
            if len(parts) >= 2:
                candidate = parts[1]

    if candidate and YOUTUBE_ID_RE.match(candidate):
        return candidate
    return None


def _strip_tracking_query(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return urlunparse(parsed._replace(fragment=""))
    qs = parse_qs(parsed.query, keep_blank_values=True)
    kept: list[tuple[str, str]] = []
    for k, values in qs.items():
        kl = k.lower()
        if kl.startswith("utm_") or kl in TRACKING_PARAMS:
            continue
        for val in values:
            kept.append((k, val))
    clean_query = urlencode(kept)
    return urlunparse(parsed._replace(query=clean_query, fragment=""))


def _is_soft_404(
    initial_path: str, final_path: str, title: str, h1: str
) -> tuple[bool, str | None]:
    init_clean = initial_path.strip("/")
    final_clean = final_path.strip("/")
    if init_clean and not final_clean:
        return True, "Soft-404 : redirection d'un chemin profond vers la racine `/`."
    if not title:
        return True, "Soft-404 : balise `<title>` absente ou vide."

    lower_title = title.lower()
    lower_h1 = h1.lower()
    for pat in SOFT_404_PATTERNS:
        if pat in lower_title or pat in lower_h1:
            return True, f"Soft-404 : motif `{pat}` détecté dans `<title>` ou `<h1>`."
    return False, None


async def _probe_youtube_oembed(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    input_url: str,
    video_id: str,
    sources: SourcesPolicy,
    expected_channel_url: str | None = None,
) -> UrlProbeResult:
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    if not sources.is_allowed_resource_domain("youtube.com"):
        return UrlProbeResult(
            input_url=input_url,
            canonical_url=canonical_url,
            source_domain="youtube.com",
            status=None,
            ok=False,
            verdict="disallowed",
            exit_code=ExitCode.LICENSE_DISALLOWED,
            is_youtube=True,
            reason="Domaine `youtube.com` non autorisé dans `sources.yaml`.",
        )

    async with sem:
        try:
            resp = await client.get(
                YOUTUBE_OEMBED_URL,
                params={"url": canonical_url, "format": "json"},
            )
        except httpx.HTTPError as exc:
            return UrlProbeResult(
                input_url=input_url,
                canonical_url=canonical_url,
                source_domain="youtube.com",
                status=None,
                ok=False,
                verdict="error",
                exit_code=ExitCode.UPSTREAM_NOT_FOUND,
                is_youtube=True,
                reason=f"Erreur réseau oEmbed YouTube : {exc}",
            )

    status = resp.status_code
    if status in {403, 429}:
        retry = _parse_retry_after(resp.headers)
        return UrlProbeResult(
            input_url=input_url,
            canonical_url=canonical_url,
            source_domain="youtube.com",
            status=status,
            ok=False,
            verdict="rate_limited",
            exit_code=ExitCode.RATE_LIMITED,
            is_youtube=True,
            reason=f"Limitation oEmbed YouTube (HTTP {status}).",
            retry_after_seconds=retry,
        )
    if status in {400, 401, 404, 410}:
        return UrlProbeResult(
            input_url=input_url,
            canonical_url=canonical_url,
            source_domain="youtube.com",
            status=status,
            ok=False,
            verdict="dead",
            exit_code=ExitCode.UPSTREAM_NOT_FOUND,
            is_youtube=True,
            reason=f"Vidéo YouTube indisponible ou non intégrable (oEmbed HTTP {status}).",
        )
    if status != 200:
        return UrlProbeResult(
            input_url=input_url,
            canonical_url=canonical_url,
            source_domain="youtube.com",
            status=status,
            ok=False,
            verdict="error",
            exit_code=ExitCode.UPSTREAM_NOT_FOUND,
            is_youtube=True,
            reason=f"Réponse oEmbed YouTube inattendue (HTTP {status}).",
        )

    try:
        data = resp.json()
    except ValueError:
        return UrlProbeResult(
            input_url=input_url,
            canonical_url=canonical_url,
            source_domain="youtube.com",
            status=status,
            ok=False,
            verdict="error",
            exit_code=ExitCode.UPSTREAM_NOT_FOUND,
            is_youtube=True,
            reason="JSON oEmbed YouTube invalide.",
        )

    title = WHITESPACE_RE.sub(" ", str(data.get("title") or "")).strip() or None
    author_url = str(data.get("author_url") or "").strip()
    if not author_url or not sources.is_allowed_youtube_channel(author_url):
        return UrlProbeResult(
            input_url=input_url,
            canonical_url=canonical_url,
            source_domain="youtube.com",
            status=status,
            ok=False,
            verdict="disallowed",
            exit_code=ExitCode.LICENSE_DISALLOWED,
            title=title,
            channel_url=author_url or None,
            is_youtube=True,
            reason=(
                f"Chaîne YouTube `{author_url or 'inconnue'}` absente de "
                "`allowed_youtube_channel_urls`."
            ),
        )

    if expected_channel_url and normalize_channel_url(author_url) != normalize_channel_url(
        expected_channel_url
    ):
        return UrlProbeResult(
            input_url=input_url,
            canonical_url=canonical_url,
            source_domain="youtube.com",
            status=status,
            ok=False,
            verdict="disallowed",
            exit_code=ExitCode.LICENSE_DISALLOWED,
            title=title,
            channel_url=author_url,
            is_youtube=True,
            reason=(
                f"`channel_url` déclaré ({expected_channel_url}) différent de "
                f"l'`author_url` oEmbed ({author_url})."
            ),
        )

    return UrlProbeResult(
        input_url=input_url,
        canonical_url=canonical_url,
        source_domain="youtube.com",
        status=200,
        ok=True,
        verdict="ok",
        exit_code=ExitCode.OK,
        title=title,
        channel_url=author_url,
        is_youtube=True,
    )


async def _probe_standard_url(
    client: httpx.AsyncClient,
    semaphores: dict[str, asyncio.Semaphore],
    input_url: str,
    sources: SourcesPolicy,
) -> UrlProbeResult:
    cleaned_initial = _strip_tracking_query(input_url.strip())
    parsed_init = urlparse(cleaned_initial)
    if parsed_init.scheme != "https" or not parsed_init.netloc:
        return UrlProbeResult(
            input_url=input_url,
            canonical_url=cleaned_initial,
            source_domain=normalize_hostname(cleaned_initial),
            status=None,
            ok=False,
            verdict="disallowed",
            exit_code=ExitCode.LICENSE_DISALLOWED,
            reason="Schéma `https://` obligatoire.",
        )

    initial_path = parsed_init.path
    current_url = cleaned_initial

    for _hop in range(MAX_REDIRECTS + 1):
        curr_parsed = urlparse(current_url)
        curr_host = normalize_hostname(current_url)
        if curr_parsed.scheme != "https" or not curr_parsed.netloc:
            return UrlProbeResult(
                input_url=input_url,
                canonical_url=current_url,
                source_domain=curr_host,
                status=None,
                ok=False,
                verdict="disallowed",
                exit_code=ExitCode.LICENSE_DISALLOWED,
                reason=f"Redirection vers une URL non-HTTPS interdite : {current_url}",
            )
        if not sources.is_allowed_resource_domain(current_url):
            return UrlProbeResult(
                input_url=input_url,
                canonical_url=current_url,
                source_domain=curr_host,
                status=None,
                ok=False,
                verdict="disallowed",
                exit_code=ExitCode.LICENSE_DISALLOWED,
                reason=f"Domaine `{curr_host}` non autorisé dans `sources.yaml`.",
            )

        rule = sources.find_domain_rule(current_url)
        canonical_domain = rule.domain if rule is not None else curr_host
        sem = semaphores.setdefault(canonical_domain, asyncio.Semaphore(2))

        async with sem:
            try:
                async with client.stream("GET", current_url) as resp:
                    status = resp.status_code
                    if status in REDIRECT_STATUSES:
                        loc = resp.headers.get("location", "").strip()
                        if not loc:
                            return UrlProbeResult(
                                input_url=input_url,
                                canonical_url=current_url,
                                source_domain=canonical_domain,
                                status=status,
                                ok=False,
                                verdict="disallowed",
                                exit_code=ExitCode.LICENSE_DISALLOWED,
                                reason=f"Redirection HTTP {status} sans en-tête `Location`.",
                            )
                        current_url = _strip_tracking_query(urljoin(current_url, loc))
                        continue

                    if status in {403, 429}:
                        retry = _parse_retry_after(resp.headers)
                        return UrlProbeResult(
                            input_url=input_url,
                            canonical_url=current_url,
                            source_domain=canonical_domain,
                            status=status,
                            ok=False,
                            verdict="rate_limited",
                            exit_code=ExitCode.RATE_LIMITED,
                            reason=f"Filtrage ou limitation distante (HTTP {status}).",
                            retry_after_seconds=retry,
                        )

                    if status in {404, 410}:
                        return UrlProbeResult(
                            input_url=input_url,
                            canonical_url=current_url,
                            source_domain=canonical_domain,
                            status=status,
                            ok=False,
                            verdict="dead",
                            exit_code=ExitCode.UPSTREAM_NOT_FOUND,
                            reason=f"Page introuvable (HTTP {status}).",
                        )

                    if status >= 500 or status != 200:
                        return UrlProbeResult(
                            input_url=input_url,
                            canonical_url=current_url,
                            source_domain=canonical_domain,
                            status=status,
                            ok=False,
                            verdict="error",
                            exit_code=ExitCode.UPSTREAM_NOT_FOUND,
                            reason=f"Statut HTTP {status} inattendu.",
                        )

                    buffer = bytearray()
                    async for chunk in resp.aiter_bytes():
                        remaining = MAX_PROBE_HTML_BYTES - len(buffer)
                        if remaining <= 0:
                            break
                        buffer.extend(chunk[:remaining])
                        if len(buffer) >= MAX_PROBE_HTML_BYTES:
                            break
            except httpx.HTTPError as exc:
                return UrlProbeResult(
                    input_url=input_url,
                    canonical_url=current_url,
                    source_domain=canonical_domain,
                    status=None,
                    ok=False,
                    verdict="error",
                    exit_code=ExitCode.UPSTREAM_NOT_FOUND,
                    reason=f"Erreur réseau : {exc}",
                )

        head_html = bytes(buffer).decode("utf-8", errors="replace")
        parser = _TitleAndH1Parser()
        parser.feed(head_html)
        parser.close()

        final_path = urlparse(current_url).path
        soft_404, soft_reason = _is_soft_404(
            initial_path, final_path, parser.title, parser.first_h1
        )
        if soft_404:
            return UrlProbeResult(
                input_url=input_url,
                canonical_url=current_url,
                source_domain=canonical_domain,
                status=200,
                ok=False,
                verdict="soft_404",
                exit_code=ExitCode.UPSTREAM_NOT_FOUND,
                title=parser.title or None,
                h1=parser.first_h1 or None,
                reason=soft_reason,
            )

        return UrlProbeResult(
            input_url=input_url,
            canonical_url=current_url,
            source_domain=canonical_domain,
            status=200,
            ok=True,
            verdict="ok",
            exit_code=ExitCode.OK,
            title=parser.title or None,
            h1=parser.first_h1 or None,
        )

    return UrlProbeResult(
        input_url=input_url,
        canonical_url=current_url,
        source_domain=normalize_hostname(current_url),
        status=None,
        ok=False,
        verdict="disallowed",
        exit_code=ExitCode.LICENSE_DISALLOWED,
        reason=f"Trop de redirections HTTP (> {MAX_REDIRECTS}).",
    )


async def _probe_single_item(
    client: httpx.AsyncClient,
    semaphores: dict[str, asyncio.Semaphore],
    raw_url: str,
    sources: SourcesPolicy,
    expected_channel_url: str | None = None,
) -> UrlProbeResult:
    cleaned = raw_url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.netloc:
        return UrlProbeResult(
            input_url=raw_url,
            canonical_url=cleaned,
            source_domain=normalize_hostname(cleaned),
            status=None,
            ok=False,
            verdict="disallowed",
            exit_code=ExitCode.LICENSE_DISALLOWED,
            reason="Schéma `https://` requis.",
        )

    host = normalize_hostname(cleaned)
    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        vid = _extract_youtube_video_id(parsed)
        if vid is None:
            return UrlProbeResult(
                input_url=raw_url,
                canonical_url=cleaned,
                source_domain="youtube.com",
                status=None,
                ok=False,
                verdict="dead",
                exit_code=ExitCode.UPSTREAM_NOT_FOUND,
                is_youtube=True,
                reason="Identifiant vidéo YouTube de 11 caractères introuvable.",
            )
        yt_sem = semaphores.setdefault("youtube.com", asyncio.Semaphore(2))
        return await _probe_youtube_oembed(
            client,
            yt_sem,
            raw_url,
            vid,
            sources,
            expected_channel_url=expected_channel_url,
        )

    return await _probe_standard_url(client, semaphores, cleaned, sources)


async def probe_urls(urls: Sequence[str], sources: SourcesPolicy) -> list[UrlProbeResult]:
    """Sonde une liste d'URL candidates sans jamais retourner le texte des pages."""
    if not urls:
        return []
    semaphores: dict[str, asyncio.Semaphore] = {}
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=15.0,
    ) as client:
        tasks = [_probe_single_item(client, semaphores, u, sources) for u in urls]
        return list(await asyncio.gather(*tasks))


def _git_output(repo_root: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _load_old_resources_urls(
    repo_root: Path,
    base_sha: str,
    rel_posix: str,
) -> set[tuple[str, str | None]]:
    raw_content = _git_output(repo_root, ["show", f"{base_sha}:{rel_posix}"])
    if not raw_content.strip():
        return set()
    yaml = YAML(typ="safe")
    yaml.version = (1, 2)
    doc = yaml.load(raw_content)
    if not isinstance(doc, dict):
        return set()
    entries = doc.get("resources") or []
    result: set[tuple[str, str | None]] = set()
    for item in entries:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            ch = item.get("channel_url")
            result.add((item["url"], str(ch) if ch else None))
    return result


async def check_repository_urls(
    repo_root: Path,
    sources: SourcesPolicy,
    diff_ref: str | None = None,
    json_report: Path | None = None,
) -> UrlCheckSummary:
    """Vérifie les liens externes de `resources.yaml` (complets ou modifiés vs `diff_ref`)."""
    checked_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    summary = UrlCheckSummary(checked_at=checked_at)

    content_root = repo_root / "content"
    if not content_root.is_dir():
        if json_report is not None:
            json_report.parent.mkdir(parents=True, exist_ok=True)
            json_report.write_text(
                json.dumps(summary.to_report_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return summary

    base_sha: str | None = None
    sources_changed = False
    changed_files: set[str] = set()
    if diff_ref is not None:
        base_sha = resolve_merge_base(repo_root, diff_ref)
        diff_names = _git_output(repo_root, ["diff", "--name-only", base_sha])
        changed_files = {line.strip() for line in diff_names.splitlines() if line.strip()}
        sources_changed = "sources.yaml" in changed_files

    # Collecter `(theme_slug_path, url, channel_url, is_newly_added_or_modified)`
    targets: list[tuple[str, str, str | None, bool]] = []
    for res_path in sorted(content_root.glob("cycle-*/*/*/resources.yaml")):
        rel_posix = res_path.resolve().relative_to(repo_root.resolve()).as_posix()
        theme_key = "/".join(rel_posix.split("/")[1:4])

        if diff_ref is not None and not sources_changed and rel_posix not in changed_files:
            continue

        raw_res = load_yaml(res_path)
        res_file = ResourcesFile.model_validate(
            raw_res,
            context={"allow_empty_resources": True},
        )
        old_pairs = (
            _load_old_resources_urls(repo_root, base_sha, rel_posix)
            if base_sha is not None
            else set()
        )

        for entry in res_file.resources:
            pair = (entry.url, entry.channel_url)
            is_new_or_changed = base_sha is not None and pair not in old_pairs
            if diff_ref is not None and not sources_changed and not is_new_or_changed:
                continue
            targets.append((theme_key, entry.url, entry.channel_url, is_new_or_changed))

    summary.checked_count = len(targets)
    if targets:
        semaphores: dict[str, asyncio.Semaphore] = {}
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
            timeout=15.0,
        ) as client:
            probes = await asyncio.gather(
                *[
                    _probe_single_item(
                        client,
                        semaphores,
                        url,
                        sources,
                        expected_channel_url=ch_url,
                    )
                    for (_th, url, ch_url, _is_new) in targets
                ]
            )

        for (theme_key, url, _ch_url, is_new), probe in zip(targets, probes, strict=True):
            if probe.ok:
                continue

            record = {
                "theme": theme_key,
                "url": url,
                "status": probe.status,
                "reason": probe.reason or probe.verdict,
            }

            if probe.verdict == "disallowed":
                summary.dead_links.append(record)
                summary.exit_code = ExitCode.LICENSE_DISALLOWED
                continue

            # Sur `--diff`, tout échec oEmbed d'un lien YouTube neuf ou modifié est bloquant
            if diff_ref is not None and is_new and probe.is_youtube:
                summary.dead_links.append(record)
                if summary.exit_code == ExitCode.OK:
                    summary.exit_code = (
                        ExitCode.RATE_LIMITED
                        if probe.verdict == "rate_limited"
                        else ExitCode.UPSTREAM_NOT_FOUND
                    )
                continue

            if probe.verdict in {"dead", "soft_404"}:
                summary.dead_links.append(record)
                if summary.exit_code == ExitCode.OK:
                    summary.exit_code = ExitCode.UPSTREAM_NOT_FOUND
            else:
                summary.warnings.append(record)

    if json_report is not None:
        json_report.parent.mkdir(parents=True, exist_ok=True)
        json_report.write_text(
            json.dumps(summary.to_report_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return summary
