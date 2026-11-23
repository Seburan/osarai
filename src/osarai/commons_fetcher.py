"""Recherche, import `1280 px` et contrôle de licence d'illustrations Wikimedia Commons."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont

from osarai import USER_AGENT, ExitCode, OsaraiError
from osarai.grounding_fetcher import strip_html_tags
from osarai.schemas import (
    SLUG_RE,
    WHITESPACE_RE,
    AssetEntry,
    SourcesPolicy,
    ThemeMeta,
    normalize_hostname,
)
from osarai.yaml_io import dump_yaml_roundtrip, load_yaml

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
STANDARD_WIDTH_PX = 1280
TARGET_WEBP_BYTES = 150 * 1024
MAX_WEBP_BYTES = 300 * 1024
RASTER_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})


@dataclass(frozen=True)
class CommonsCandidate:
    """Candidat d'illustration libre retourné par `search_commons`."""

    commons_title: str
    source_url: str
    mime: str
    width: int
    height: int
    license_spdx: str
    license_url: str
    author: str
    title: str
    thumb_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "commons_title": self.commons_title,
            "source_url": self.source_url,
            "mime": self.mime,
            "width": self.width,
            "height": self.height,
            "license_spdx": self.license_spdx,
            "license_url": self.license_url,
            "author": self.author,
            "title": self.title,
            "thumb_url": self.thumb_url,
        }


def _parse_retry_after(headers: httpx.Headers) -> int:
    raw = headers.get("retry-after", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return 60


def _assert_commons_media_url(url: str, sources: SourcesPolicy) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise OsaraiError(
            f"URL HTTPS requise pour Wikimedia Commons : {url!r}",
            ExitCode.LICENSE_DISALLOWED,
            details={"url": url},
        )
    rule = sources.find_domain_rule(url)
    if rule is None or not rule.allow_embed_media or rule.adapter != "wikimedia_commons":
        raise OsaraiError(
            f"Domaine `{normalize_hostname(url)}` interdit pour `fetch-commons` (`sources.yaml`).",
            ExitCode.LICENSE_DISALLOWED,
            details={"url": url},
        )


def _commons_get(
    client: httpx.Client,
    url: str,
    sources: SourcesPolicy,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    current_url = url
    current_params = params
    for _hop in range(MAX_REDIRECTS + 1):
        _assert_commons_media_url(current_url, sources)
        try:
            resp = client.get(current_url, params=current_params)
        except httpx.HTTPError as exc:
            raise OsaraiError(
                f"Erreur réseau Wikimedia sur {current_url} : {exc}",
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
                f"Limitation de débit Wikimedia (HTTP {resp.status_code}) sur {current_url}.",
                ExitCode.RATE_LIMITED,
                details={
                    "url": current_url,
                    "status_code": resp.status_code,
                    "retry_after_seconds": _parse_retry_after(resp.headers),
                },
            )
        if resp.status_code in {404, 410}:
            raise OsaraiError(
                f"Fichier Wikimedia introuvable (HTTP {resp.status_code}) : {current_url}",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"url": current_url, "status_code": resp.status_code},
            )
        if resp.status_code >= 400:
            raise OsaraiError(
                f"Erreur HTTP {resp.status_code} depuis Wikimedia ({current_url}).",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"url": current_url, "status_code": resp.status_code},
            )
        return resp

    raise OsaraiError(
        f"Trop de redirections HTTP (> {MAX_REDIRECTS}) depuis {url}.",
        ExitCode.LICENSE_DISALLOWED,
        details={"url": url},
    )


def _ext_val(extmetadata: dict[str, Any], key: str) -> str:
    node = extmetadata.get(key)
    if isinstance(node, dict):
        raw = str(node.get("value") or "")
        return WHITESPACE_RE.sub(" ", strip_html_tags(raw)).strip()
    return ""


def normalize_commons_license(
    extmetadata: dict[str, Any],
    sources: SourcesPolicy,
) -> tuple[str, str]:
    """Mappe `extmetadata` vers un identifiant de `sources.allowed_licenses` + URL de licence."""
    short_name = _ext_val(extmetadata, "LicenseShortName")
    usage_terms = _ext_val(extmetadata, "UsageTerms")
    raw_url = _ext_val(extmetadata, "LicenseUrl")
    copyrighted = _ext_val(extmetadata, "Copyrighted").lower()

    if raw_url.startswith("//"):
        raw_url = f"https:{raw_url}"

    combined = f"{short_name} | {usage_terms} | {raw_url}".lower()

    # Correspondances ordonnées de la version la plus précise à la plus générale
    license_rules: list[tuple[tuple[str, ...], str, str]] = [
        (
            ("cc-by-sa-4.0", "cc by-sa 4.0", "by-sa/4.0"),
            "CC-BY-SA-4.0",
            "https://creativecommons.org/licenses/by-sa/4.0/",
        ),
        (
            ("cc-by-sa-3.0", "cc by-sa 3.0", "by-sa/3.0"),
            "CC-BY-SA-3.0",
            "https://creativecommons.org/licenses/by-sa/3.0/",
        ),
        (
            ("cc-by-sa-2.5", "cc by-sa 2.5", "by-sa/2.5"),
            "CC-BY-SA-2.5",
            "https://creativecommons.org/licenses/by-sa/2.5/",
        ),
        (
            ("cc-by-sa-2.0", "cc by-sa 2.0", "by-sa/2.0"),
            "CC-BY-SA-2.0",
            "https://creativecommons.org/licenses/by-sa/2.0/",
        ),
        (
            ("cc-by-4.0", "cc by 4.0", "licenses/by/4.0"),
            "CC-BY-4.0",
            "https://creativecommons.org/licenses/by/4.0/",
        ),
        (
            ("cc-by-3.0", "cc by 3.0", "licenses/by/3.0"),
            "CC-BY-3.0",
            "https://creativecommons.org/licenses/by/3.0/",
        ),
        (
            ("cc-by-2.5", "cc by 2.5", "licenses/by/2.5"),
            "CC-BY-2.5",
            "https://creativecommons.org/licenses/by/2.5/",
        ),
        (
            ("cc-by-2.0", "cc by 2.0", "licenses/by/2.0"),
            "CC-BY-2.0",
            "https://creativecommons.org/licenses/by/2.0/",
        ),
        (
            ("cc0", "publicdomain/zero/1.0", "cc-zero"),
            "CC0-1.0",
            "https://creativecommons.org/publicdomain/zero/1.0/",
        ),
        (
            ("etalab", "licence ouverte", "open licence"),
            "Etalab-2.0",
            "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
        ),
    ]

    matched_spdx: str | None = None
    fallback_url = ""
    for patterns, spdx, default_url in license_rules:
        if any(pat in combined for pat in patterns):
            matched_spdx = spdx
            fallback_url = default_url
            break

    if matched_spdx is None:
        is_pd = (
            copyrighted == "false"
            or "public domain" in combined
            or "domaine public" in combined
            or "cc-pdm" in combined
            or "publicdomain/mark/1.0" in combined
            or short_name.lower().startswith("pd")
        )
        if is_pd:
            matched_spdx = "CC-PDM-1.0"
            fallback_url = "https://creativecommons.org/publicdomain/mark/1.0/"

    if matched_spdx is None or matched_spdx not in set(sources.allowed_licenses):
        raise OsaraiError(
            f"Licence Wikimedia non autorisée (`{short_name or usage_terms or 'inconnue'}`) ; "
            "seules les licences de `sources.yaml -> allowed_licenses` sont admises.",
            ExitCode.LICENSE_DISALLOWED,
            details={"license_short_name": short_name, "usage_terms": usage_terms},
        )

    final_license_url = raw_url if raw_url.startswith("https://") else fallback_url
    return matched_spdx, final_license_url


def _normalize_commons_file_title(commons_file: str) -> str:
    cleaned = strip_html_tags(commons_file).strip().replace("_", " ")
    if cleaned.lower().startswith("fichier:"):
        cleaned = "File:" + cleaned[len("fichier:") :].strip()
    elif cleaned.lower().startswith("file:"):
        cleaned = "File:" + cleaned[len("file:") :].strip()
    else:
        cleaned = f"File:{cleaned}"
    if len(cleaned) < 6 or ".." in cleaned or "/" in cleaned:
        raise OsaraiError(
            f"Titre Wikimedia Commons invalide : {commons_file!r}.",
            ExitCode.VALIDATION_ERROR,
        )
    return cleaned


def _extract_clean_title_and_author(
    commons_title: str,
    extmetadata: dict[str, Any],
) -> tuple[str, str]:
    obj_name = _ext_val(extmetadata, "ObjectName")
    desc = _ext_val(extmetadata, "ImageDescription")
    fallback_stem = commons_title[len("File:") :].rsplit(".", 1)[0].strip()
    title = (obj_name or desc or fallback_stem or commons_title)[:200].strip()

    artist = _ext_val(extmetadata, "Artist") or _ext_val(extmetadata, "Credit")
    author = (artist or "Contributeurs Wikimedia Commons")[:200].strip()
    return title, author


def search_commons(
    query: str,
    sources: SourcesPolicy,
    limit: int = 8,
) -> list[CommonsCandidate]:
    """Recherche des schémas/cartes libres sur Wikimedia Commons (`gsrnamespace=6`)."""
    cleaned_query = query.strip()
    if not cleaned_query:
        raise OsaraiError("La requête `--search` ne peut pas être vide.", ExitCode.VALIDATION_ERROR)

    params = {
        "action": "query",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": cleaned_query,
        "gsrlimit": max(1, min(limit, 25)),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": str(STANDARD_WIDTH_PX),
        "format": "json",
    }

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=20.0,
    ) as client:
        resp = _commons_get(client, COMMONS_API_URL, sources, params=params)
        payload = resp.json()

    pages = payload.get("query", {}).get("pages", {})
    if not isinstance(pages, dict):
        return []

    candidates: list[CommonsCandidate] = []
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        c_title = str(page.get("title") or "").strip()
        info_list = page.get("imageinfo")
        if not c_title.startswith("File:") or not isinstance(info_list, list) or not info_list:
            continue
        info = info_list[0]
        if not isinstance(info, dict):
            continue
        mime = str(info.get("mime") or "")
        if mime != "image/svg+xml" and mime not in RASTER_MIMES:
            continue
        extmeta = info.get("extmetadata")
        if not isinstance(extmeta, dict):
            continue
        try:
            lic_spdx, lic_url = normalize_commons_license(extmeta, sources)
        except OsaraiError:
            continue

        title, author = _extract_clean_title_and_author(c_title, extmeta)
        encoded_file = quote(c_title.replace(" ", "_"), safe=":_()-.")
        desc_url = str(info.get("descriptionurl") or "")
        source_url = (
            desc_url
            if desc_url.startswith("https://commons.wikimedia.org/")
            else f"https://commons.wikimedia.org/wiki/{encoded_file}"
        )
        candidates.append(
            CommonsCandidate(
                commons_title=c_title,
                source_url=source_url,
                mime=mime,
                width=int(info.get("width") or 0),
                height=int(info.get("height") or 0),
                license_spdx=lic_spdx,
                license_url=lic_url,
                author=author,
                title=title,
                thumb_url=str(info.get("thumburl")) if info.get("thumburl") else None,
            )
        )
    return candidates[:limit]


def _query_thumb_url(
    client: httpx.Client,
    commons_title: str,
    sources: SourcesPolicy,
    *,
    url_param: str | None = None,
) -> str | None:
    params: dict[str, str] = {
        "action": "query",
        "titles": commons_title,
        "prop": "imageinfo",
        "iiprop": "url|size",
        "iiurlwidth": str(STANDARD_WIDTH_PX),
        "format": "json",
    }
    if url_param is not None:
        params["iiurlparam"] = url_param

    resp = _commons_get(client, COMMONS_API_URL, sources, params=params)
    pages = resp.json().get("query", {}).get("pages", {})
    if not isinstance(pages, dict) or not pages:
        return None
    page = next(iter(pages.values()))
    if not isinstance(page, dict):
        return None
    info_list = page.get("imageinfo")
    if not isinstance(info_list, list) or not info_list or not isinstance(info_list[0], dict):
        return None
    thumb = info_list[0].get("thumburl")
    return str(thumb) if thumb else None


def _encode_webp_within_budget(raw_bytes: bytes) -> tuple[bytes, int, int, int]:
    """Encode l'image au format `.webp` (`quality=85`, repli `75`, `65`) sous `<= 300 Ko`."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as src_img:
            has_alpha = src_img.mode in {"RGBA", "LA"} or (
                src_img.mode == "P" and "transparency" in src_img.info
            )
            working = src_img.convert("RGBA" if has_alpha else "RGB")
    except OSError as exc:
        raise OsaraiError(
            f"Données d'image Wikimedia illisibles par Pillow : {exc}",
            ExitCode.UPSTREAM_NOT_FOUND,
        ) from exc

    if working.width > STANDARD_WIDTH_PX:
        scaled_h = max(1, round(working.height * (STANDARD_WIDTH_PX / working.width)))
        working = working.resize((STANDARD_WIDTH_PX, scaled_h), Image.Resampling.LANCZOS)

    best_bytes = b""
    used_quality = 85
    for quality in (85, 75, 65):
        buf = io.BytesIO()
        working.save(buf, format="WEBP", quality=quality, method=6)
        candidate = buf.getvalue()
        best_bytes = candidate
        used_quality = quality
        if len(candidate) <= TARGET_WEBP_BYTES:
            break

    if len(best_bytes) > MAX_WEBP_BYTES:
        raise OsaraiError(
            f"L'illustration compressée dépasse le plafond de 300 Ko "
            f"({len(best_bytes) / 1024:.1f} Ko).",
            ExitCode.VALIDATION_ERROR,
            details={"size_bytes": len(best_bytes), "max_bytes": MAX_WEBP_BYTES},
        )

    with Image.open(io.BytesIO(best_bytes)) as verify_img:
        real_w, real_h = verify_img.size

    return best_bytes, real_w, real_h, used_quality


def _render_percentage_grid(webp_bytes: bytes, out_path: Path) -> None:
    """Génère hors Git une grille graduée `0..100 %` pour le placement HITL des masques."""
    with Image.open(io.BytesIO(webp_bytes)) as img:
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        composed = Image.alpha_composite(bg, rgba)

    width, height = composed.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    try:
        font = ImageFont.load_default(size=max(10, min(18, width // 65)))
    except TypeError:  # pragma: no cover
        font = ImageFont.load_default()

    for pct in range(5, 100, 5):
        x = round((pct / 100.0) * width)
        y = round((pct / 100.0) * height)
        if pct == 50:
            color = (220, 38, 38, 175)
            line_w = 2
        elif pct % 10 == 0:
            color = (37, 99, 235, 145)
            line_w = 1
        else:
            color = (100, 116, 139, 75)
            line_w = 1

        draw.line([(x, 0), (x, height)], fill=color, width=line_w)
        draw.line([(0, y), (width, y)], fill=color, width=line_w)

        if pct % 10 == 0:
            label = f"{pct}%"
            draw.rectangle([x + 2, 2, x + 32, 18], fill=(255, 255, 255, 210))
            draw.text((x + 4, 3), label, fill=(15, 23, 42, 255), font=font)
            draw.rectangle([2, y + 2, 32, y + 18], fill=(255, 255, 255, 210))
            draw.text((4, y + 3), label, fill=(15, 23, 42, 255), font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(composed, overlay).convert("RGB").save(out_path, format="PNG")


def _infer_repo_root_from_theme(theme_dir: Path) -> Path:
    resolved = theme_dir.resolve()
    if len(resolved.parts) >= 4 and resolved.parts[-4] == "content":
        return resolved.parents[3]
    return resolved.parent


def fetch_commons_image(
    commons_file: str,
    theme_dir: Path,
    asset_id: str,
    sources: SourcesPolicy,
) -> AssetEntry:
    """Importe une illustration Wikimedia Commons au palier `1280 px` dans `<theme>/assets/`."""
    if not SLUG_RE.match(asset_id):
        raise OsaraiError(
            f"`asset_id` invalide ({asset_id!r}) ; attendu un slug minuscule `a-z0-9-`.",
            ExitCode.VALIDATION_ERROR,
        )
    commons_title = _normalize_commons_file_title(commons_file)

    meta_path = theme_dir / "meta.yaml"
    try:
        meta = ThemeMeta.model_validate(load_yaml(meta_path))
    except Exception as exc:
        if isinstance(exc, OsaraiError):
            raise
        raise OsaraiError(
            f"`meta.yaml` invalide dans {theme_dir} : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(meta_path)},
        ) from exc

    meta_params = {
        "action": "query",
        "titles": commons_title,
        "prop": "imageinfo",
        "iiprop": "url|size|sha1|mime|extmetadata",
        "format": "json",
    }

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=False,
        timeout=30.0,
    ) as client:
        meta_resp = _commons_get(client, COMMONS_API_URL, sources, params=meta_params)
        pages = meta_resp.json().get("query", {}).get("pages", {})
        if not isinstance(pages, dict) or not pages:
            raise OsaraiError(
                f"Fichier Wikimedia introuvable : `{commons_title}`.",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"commons_title": commons_title},
            )
        page_obj = next(iter(pages.values()))
        if not isinstance(page_obj, dict) or "missing" in page_obj:
            raise OsaraiError(
                f"Fichier Wikimedia inexistant : `{commons_title}`.",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"commons_title": commons_title},
            )
        info_list = page_obj.get("imageinfo")
        if not isinstance(info_list, list) or not info_list or not isinstance(info_list[0], dict):
            raise OsaraiError(
                f"Métadonnées `imageinfo` absentes pour `{commons_title}`.",
                ExitCode.UPSTREAM_NOT_FOUND,
                details={"commons_title": commons_title},
            )

        info = info_list[0]
        canonical_commons_title = str(page_obj.get("title") or commons_title).strip()
        mime = str(info.get("mime") or "").lower()
        orig_width = int(info.get("width") or 0)
        orig_url = str(info.get("url") or "").strip()
        extmetadata = info.get("extmetadata")
        if not isinstance(extmetadata, dict):
            raise OsaraiError(
                f"Métadonnées de licence `extmetadata` absentes pour `{canonical_commons_title}`.",
                ExitCode.LICENSE_DISALLOWED,
            )

        license_spdx, license_url = normalize_commons_license(extmetadata, sources)
        clean_title, clean_author = _extract_clean_title_and_author(
            canonical_commons_title, extmetadata
        )

        # Chaîne de repli officielle au palier 1280 px selon le type MIME
        raw_image_bytes: bytes | None = None
        render_variant = "1280 px"
        if mime == "image/svg+xml":
            langfr_url = _query_thumb_url(
                client,
                canonical_commons_title,
                sources,
                url_param=f"langfr-{STANDARD_WIDTH_PX}px",
            )
            if langfr_url:
                try:
                    dl_resp = _commons_get(client, langfr_url, sources)
                    raw_image_bytes = dl_resp.content
                    render_variant = "SVG langfr 1280 px"
                except OsaraiError as exc:
                    if exc.exit_code in {ExitCode.LICENSE_DISALLOWED, ExitCode.RATE_LIMITED}:
                        raise
                    raw_image_bytes = None

            if raw_image_bytes is None:
                std_svg_url = _query_thumb_url(
                    client,
                    canonical_commons_title,
                    sources,
                    url_param=None,
                )
                if not std_svg_url:
                    raise OsaraiError(
                        f"Aucune vignette SVG 1280 px disponible pour `{canonical_commons_title}`.",
                        ExitCode.UPSTREAM_NOT_FOUND,
                    )
                raw_image_bytes = _commons_get(client, std_svg_url, sources).content
                render_variant = "SVG standard 1280 px"
        elif mime in RASTER_MIMES:
            if 0 < orig_width <= STANDARD_WIDTH_PX and orig_url:
                raw_image_bytes = _commons_get(client, orig_url, sources).content
                render_variant = f"original {orig_width} px"
            else:
                raster_thumb = _query_thumb_url(
                    client,
                    canonical_commons_title,
                    sources,
                    url_param=None,
                )
                target_dl_url = raster_thumb or orig_url
                if not target_dl_url:
                    raise OsaraiError(
                        f"URL d'image introuvable pour `{canonical_commons_title}`.",
                        ExitCode.UPSTREAM_NOT_FOUND,
                    )
                raw_image_bytes = _commons_get(client, target_dl_url, sources).content
                render_variant = "vignette 1280 px"
        else:
            raise OsaraiError(
                f"Format MIME `{mime}` non pris en charge pour `{canonical_commons_title}`.",
                ExitCode.VALIDATION_ERROR,
                details={"mime": mime},
            )

    webp_bytes, real_w, real_h, used_quality = _encode_webp_within_budget(raw_image_bytes)
    sha256_hex = hashlib.sha256(webp_bytes).hexdigest()

    filename = f"{meta.id_prefix}--{asset_id}.webp"
    assets_dir = theme_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_file_path = assets_dir / filename
    asset_file_path.write_bytes(webp_bytes)

    encoded_file = quote(canonical_commons_title.replace(" ", "_"), safe=":_()-.")
    desc_url = str(info.get("descriptionurl") or "")
    source_url = (
        desc_url
        if desc_url.startswith("https://commons.wikimedia.org/")
        else f"https://commons.wikimedia.org/wiki/{encoded_file}"
    )
    modifications_note = (
        f"Rendu Wikimedia Commons ({render_variant}) converti en WebP "
        f"(qualité {used_quality}) sans modification éditoriale."
    )

    entry = AssetEntry(
        asset_id=asset_id,
        filename=filename,
        width=real_w,
        height=real_h,
        sha256=sha256_hex,
        commons_title=canonical_commons_title,
        source_url=source_url,
        license_spdx=license_spdx,
        license_url=license_url,
        author=clean_author,
        title=clean_title,
        modifications_note=modifications_note,
        hitl_verified=False,
    )

    assets_yaml_path = theme_dir / "assets.yaml"
    if not assets_yaml_path.is_file():
        assets_yaml_path.write_text("schema_version: 1\nassets: []\n", encoding="utf-8")

    entry_dict = entry.model_dump(mode="json")

    def _upsert_asset(doc: Any) -> None:
        if not isinstance(doc, dict):
            return
        assets_list = doc.setdefault("assets", [])
        for idx, existing in enumerate(assets_list):
            if isinstance(existing, dict) and existing.get("asset_id") == asset_id:
                assets_list[idx] = entry_dict
                return
        assets_list.append(entry_dict)

    dump_yaml_roundtrip(assets_yaml_path, _upsert_asset)

    repo_root = _infer_repo_root_from_theme(theme_dir)
    grid_path = repo_root / ".osarai_tmp" / "previews" / f"{filename}--grid.png"
    _render_percentage_grid(webp_bytes, grid_path)

    return entry
