"""Tests unitaires et d'intégration simulés (`respx` + `asyncio.run`) du Jalon 2."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from osarai import ExitCode, OsaraiError
from osarai.bo_sync import discover_eduscol_pdfs, sync_and_extract_bo
from osarai.commons_fetcher import fetch_commons_image, search_commons
from osarai.grounding_fetcher import fetch_grounding, search_grounding
from osarai.occlusion_preview import generate_occlusion_previews
from osarai.schemas import SourcesPolicy
from osarai.url_checker import check_repository_urls, probe_urls
from osarai.yaml_io import dump_yaml_roundtrip, load_yaml


def _load_root_sources() -> SourcesPolicy:
    return SourcesPolicy.model_validate(load_yaml(Path("sources.yaml")))


def _make_png_bytes(
    width: int = 800, height: int = 500, color: tuple[int, int, int] = (200, 220, 240)
) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=color)
    img.save(buf, format="PNG")
    return buf.getvalue()


@respx.mock
def test_bo_sync_discover_and_extract_tabular_pdf(
    sample_repo: Path, sample_tabular_pdf: Path
) -> None:
    sources = _load_root_sources()
    pdf_bytes = sample_tabular_pdf.read_bytes()
    page_url = "https://eduscol.education.gouv.fr/4362/enseigner-au-cycle-4"
    html_body = """
    <html><body>
      <a href="/files/programme-svt-cycle4.pdf">Programme SVT Cycle 4</a>
      <a href="/document/12345/download">Attendus SVT 5e</a>
      <a href="/document/99999/download">Page HTML non PDF</a>
      <a href="https://evil.example.org/piege.pdf">Lien externe ignoré</a>
    </body></html>
    """
    respx.get(page_url).mock(return_value=httpx.Response(200, text=html_body))
    respx.head("https://eduscol.education.gouv.fr/document/12345/download").mock(
        return_value=httpx.Response(405)
    )
    respx.get("https://eduscol.education.gouv.fr/document/12345/download").mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=pdf_bytes,
        )
    )
    respx.head("https://eduscol.education.gouv.fr/document/99999/download").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/html; charset=utf-8"})
    )

    links = discover_eduscol_pdfs(page_url, sources)
    assert len(links) == 2
    assert links[0].source_kind == "pdf_ext"
    assert links[0].url == "https://eduscol.education.gouv.fr/files/programme-svt-cycle4.pdf"
    assert links[1].source_kind == "drupal_download"
    assert links[1].title == "Attendus SVT 5e"

    # Mettre sha256 à null dans bo_manifest.yaml puis extraire via pdfplumber
    manifest_path = sample_repo / "curriculum" / "sources" / "bo_manifest.yaml"
    dump_yaml_roundtrip(
        manifest_path,
        lambda doc: doc["subjects"][0]["documents"][0].__setitem__("sha256", None),
    )

    expected_sha = hashlib.sha256(pdf_bytes).hexdigest()
    respx.get("https://eduscol.education.gouv.fr/document/12345/download").mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=pdf_bytes,
        )
    )

    extracted = sync_and_extract_bo(manifest_path, "cycle-4", "svt", sources)
    assert len(extracted) == 1
    meta = extracted[0]
    assert meta.sha256 == expected_sha
    assert meta.pages == 1
    assert meta.tables_extracted >= 1

    md_path = Path(meta.markdown_path)
    assert md_path.name.startswith("01-")
    assert md_path.suffix == ".md"
    md_content = md_path.read_text(encoding="utf-8")
    assert "| 5e | 4e |" in md_content
    assert "| Respiration | Reproduction |" in md_content
    assert "Programme officiel SVT Cycle 4" in md_content

    # Vérifier que sha256 a été enregistré dans bo_manifest.yaml
    updated_manifest = load_yaml(manifest_path)
    assert updated_manifest["subjects"][0]["documents"][0]["sha256"] == expected_sha

    # Vérifier le rejet si le serveur renvoie un PDF au sha256 modifié
    respx.get("https://eduscol.education.gouv.fr/document/12345/download").mock(
        return_value=httpx.Response(200, content=pdf_bytes + b"%tampered")
    )
    with pytest.raises(OsaraiError) as exc_info:
        sync_and_extract_bo(manifest_path, "cycle-4", "svt", sources)
    assert exc_info.value.exit_code == ExitCode.VALIDATION_ERROR

    # Rejet d'une redirection 302 vers un domaine hors eduscol_bo
    respx.get(page_url).mock(
        return_value=httpx.Response(302, headers={"Location": "https://www.lumni.fr/bo.pdf"})
    )
    with pytest.raises(OsaraiError) as redir_exc:
        discover_eduscol_pdfs(page_url, sources)
    assert redir_exc.value.exit_code == ExitCode.LICENSE_DISALLOWED


@respx.mock
def test_grounding_fetcher_rightsinfo_section_40kb_and_redirect_block(sample_repo: Path) -> None:
    sources = _load_root_sources()
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"

    # 1) Recherche MediaWiki nettoyant les balises HTML des extraits
    snippet_html = 'Les <span class="searchmatch">alvéoles</span> assurent les échanges.'
    respx.get("https://fr.vikidia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "search": [
                        {
                            "title": "Alvéole pulmonaire",
                            "snippet": snippet_html,
                            "wordcount": 420,
                        }
                    ]
                }
            },
        )
    )
    hits = search_grounding("alvéoles", sources, domain="fr.vikidia.org")
    assert len(hits) == 1
    assert "<span" not in hits[0].snippet
    assert hits[0].url == "https://fr.vikidia.org/wiki/Alv%C3%A9ole_pulmonaire"

    # 2) Récupération Wikipédia FR en CC-BY-SA-4.0 avec découpage `== Échanges gazeux ==` et > 40 Ko
    long_paragraph = "Les échanges gazeux alvéolaires reposent sur la diffusion. " * 900
    wiki_extract = (
        "Introduction générale.\n\n"
        "== Anatomie ==\nTexte anatomie.\n\n"
        f"== Échanges gazeux ==\n<script>alert(1)</script>{long_paragraph}\n"
        "=== Sous-partie ===\nDétails utiles.\n\n"
        "== Pathologies ==\nHors sujet.\n"
    )
    respx.get("https://fr.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "rightsinfo": {
                        "url": "//creativecommons.org/licenses/by-sa/4.0/",
                        "text": "Creative Commons Attribution-ShareAlike 4.0",
                    },
                    "pages": {
                        "100": {
                            "pageid": 100,
                            "title": "Poumon",
                            "extract": wiki_extract,
                            "revisions": [
                                {"revid": 210987654, "timestamp": "2026-10-01T12:00:00Z"}
                            ],
                        }
                    },
                }
            },
        )
    )

    doc = fetch_grounding(
        "https://fr.wikipedia.org/wiki/Poumon",
        sources,
        section="Échanges gazeux",
        theme_dir=theme_dir,
    )
    assert doc.credit.license_spdx == "CC-BY-SA-4.0"
    assert doc.credit.license_url == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert (
        doc.credit.authors_or_history_url == "https://fr.wikipedia.org/wiki/Special:History/Poumon"
    )
    assert doc.truncated is True
    assert doc.byte_length <= 40 * 1024
    assert "alert(1)" not in doc.text
    assert "Pathologies" not in doc.text

    # Vérifier l'idempotence dans meta.yaml -> sources_used
    fetch_grounding(
        "https://fr.wikipedia.org/wiki/Poumon",
        sources,
        section="Échanges gazeux",
        theme_dir=theme_dir,
    )
    meta_after = load_yaml(theme_dir / "meta.yaml")
    wiki_entries = [
        s for s in meta_after["sources_used"] if s["url"] == "https://fr.wikipedia.org/wiki/Poumon"
    ]
    assert len(wiki_entries) == 1

    # Section absente -> UPSTREAM_NOT_FOUND (code 5)
    with pytest.raises(OsaraiError) as sec_exc:
        fetch_grounding("https://fr.wikipedia.org/wiki/Poumon", sources, section="Section inconnue")
    assert sec_exc.value.exit_code == ExitCode.UPSTREAM_NOT_FOUND

    # 3) Vikidia en CC-BY-SA-3.0
    respx.get("https://fr.vikidia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "rightsinfo": {
                        "url": "https://creativecommons.org/licenses/by-sa/3.0/deed.fr",
                        "text": "CC BY-SA 3.0",
                    },
                    "pages": {
                        "42": {
                            "pageid": 42,
                            "title": "Digestion",
                            "extract": "La digestion transforme les aliments en nutriments.",
                            "revisions": [{"revid": 999, "timestamp": "2026-09-10T08:00:00Z"}],
                        }
                    },
                }
            },
        )
    )
    vik_doc = fetch_grounding("https://fr.vikidia.org/wiki/Digestion", sources)
    assert vik_doc.credit.license_spdx == "CC-BY-SA-3.0"

    # 4) Redirection 302 vers un domaine hors allow_grounding -> LICENSE_DISALLOWED (code 4)
    respx.get("https://fr.vikidia.org/w/api.php").mock(
        return_value=httpx.Response(
            302,
            headers={"Location": "https://www.lelivrescolaire.fr/page"},
        )
    )
    with pytest.raises(OsaraiError) as redir_err:
        fetch_grounding("https://fr.vikidia.org/wiki/Digestion", sources)
    assert redir_err.value.exit_code == ExitCode.LICENSE_DISALLOWED


@respx.mock
def test_commons_fetcher_svg_fallback_pdm_gfdl_and_grid(sample_repo: Path) -> None:
    sources = _load_root_sources()
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    png_bytes = _make_png_bytes(1280, 900)

    def _commons_router(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("generator") == "search":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "1": {
                                "title": "File:Valid_PD.png",
                                "imageinfo": [
                                    {
                                        "mime": "image/png",
                                        "width": 1000,
                                        "height": 800,
                                        "url": "https://upload.wikimedia.org/wikipedia/commons/1/11/Valid_PD.png",
                                        "extmetadata": {
                                            "LicenseShortName": {"value": "Public domain"},
                                            "Copyrighted": {"value": "False"},
                                            "Artist": {"value": "<b>Auteur</b>"},
                                        },
                                    }
                                ],
                            },
                            "2": {
                                "title": "File:GFDL_Only.png",
                                "imageinfo": [
                                    {
                                        "mime": "image/png",
                                        "width": 1000,
                                        "height": 800,
                                        "url": "https://upload.wikimedia.org/wikipedia/commons/2/22/GFDL_Only.png",
                                        "extmetadata": {
                                            "LicenseShortName": {"value": "GFDL"},
                                            "UsageTerms": {
                                                "value": "GNU Free Documentation License"
                                            },
                                        },
                                    }
                                ],
                            },
                        }
                    }
                },
            )

        title = params.get("titles", "")
        if title == "File:GFDL Only.svg":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "9": {
                                "title": "File:GFDL Only.svg",
                                "imageinfo": [
                                    {
                                        "mime": "image/svg+xml",
                                        "width": 800,
                                        "height": 600,
                                        "url": "https://upload.wikimedia.org/gfdl.svg",
                                        "extmetadata": {
                                            "LicenseShortName": {"value": "GFDL"},
                                            "UsageTerms": {
                                                "value": "GNU Free Documentation License 1.2"
                                            },
                                        },
                                    }
                                ],
                            }
                        }
                    }
                },
            )

        if title == "File:Poumons schema.svg":
            if "extmetadata" in params.get("iiprop", ""):
                return httpx.Response(
                    200,
                    json={
                        "query": {
                            "pages": {
                                "10": {
                                    "title": "File:Poumons schema.svg",
                                    "imageinfo": [
                                        {
                                            "mime": "image/svg+xml",
                                            "width": 900,
                                            "height": 700,
                                            "url": "https://upload.wikimedia.org/orig.svg",
                                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Poumons_schema.svg",
                                            "extmetadata": {
                                                "LicenseShortName": {"value": "Public domain"},
                                                "Copyrighted": {"value": "False"},
                                                "Artist": {
                                                    "value": "<script>evil()</script>Jean Dupont"
                                                },
                                                "ObjectName": {"value": "<i>Schéma pulmonaire</i>"},
                                            },
                                        }
                                    ],
                                }
                            }
                        }
                    },
                )
            if params.get("iiurlparam") == "langfr-1280px":
                return httpx.Response(
                    200,
                    json={
                        "query": {
                            "pages": {
                                "10": {
                                    "imageinfo": [
                                        {
                                            "thumburl": "https://upload.wikimedia.org/thumb/langfr-fail.png"
                                        }
                                    ]
                                }
                            }
                        }
                    },
                )
            assert "iiurlparam" not in params
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "10": {
                                "imageinfo": [
                                    {
                                        "thumburl": "https://upload.wikimedia.org/thumb/std-1280px.png"
                                    }
                                ]
                            }
                        }
                    }
                },
            )

        # Cas matriciel PNG > 1280 px : ne doit jamais envoyer iiurlparam
        assert "iiurlparam" not in params
        if "extmetadata" in params.get("iiprop", ""):
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "11": {
                                "title": "File:Carte monde.png",
                                "imageinfo": [
                                    {
                                        "mime": "image/png",
                                        "width": 2400,
                                        "height": 1600,
                                        "url": "https://upload.wikimedia.org/orig-2400.png",
                                        "extmetadata": {
                                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                            "LicenseUrl": {
                                                "value": "//creativecommons.org/licenses/by-sa/4.0/"
                                            },
                                            "Artist": {"value": "Cartographe"},
                                        },
                                    }
                                ],
                            }
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "11": {
                            "imageinfo": [
                                {"thumburl": "https://upload.wikimedia.org/thumb/carte-1280.png"}
                            ]
                        }
                    }
                }
            },
        )

    respx.get("https://commons.wikimedia.org/w/api.php").mock(side_effect=_commons_router)
    respx.get("https://upload.wikimedia.org/thumb/langfr-fail.png").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://upload.wikimedia.org/thumb/std-1280px.png").mock(
        return_value=httpx.Response(200, content=png_bytes)
    )
    respx.get("https://upload.wikimedia.org/thumb/carte-1280.png").mock(
        return_value=httpx.Response(200, content=png_bytes)
    )

    # 1) Recherche filtrant GFDL-only
    found = search_commons("poumons", sources)
    assert len(found) == 1
    assert found[0].license_spdx == "CC-PDM-1.0"
    assert found[0].author == "Auteur"

    # 2) Rejet GFDL-only à l'import
    with pytest.raises(OsaraiError) as gfdl_exc:
        fetch_commons_image("File:GFDL_Only.svg", theme_dir, "gfdl", sources)
    assert gfdl_exc.value.exit_code == ExitCode.LICENSE_DISALLOWED

    # 3) Import SVG avec repli langfr-1280px -> 1280px, CC-PDM-1.0, nettoyage <script> et grille
    entry = fetch_commons_image("File:Poumons_schema.svg", theme_dir, "poumons", sources)
    assert entry.license_spdx == "CC-PDM-1.0"
    assert entry.hitl_verified is False
    assert "evil" not in entry.author
    assert entry.author == "Jean Dupont"
    assert entry.title == "Schéma pulmonaire"
    assert (theme_dir / "assets" / entry.filename).is_file()
    grid_path = sample_repo / ".osarai_tmp" / "previews" / f"{entry.filename}--grid.png"
    assert grid_path.is_file()

    # 4) Import PNG matriciel > 1280 px sans iiurlparam
    raster_entry = fetch_commons_image("File:Carte_monde.png", theme_dir, "carte", sources)
    assert raster_entry.license_spdx == "CC-BY-SA-4.0"
    assert raster_entry.width == 1280

    # 5) Plafond bloquant > 300 Ko sur une image très bruitée
    huge_noisy = Image.effect_noise((1280, 1280), 255.0).convert("RGB")
    noisy_buf = io.BytesIO()
    huge_noisy.save(noisy_buf, format="PNG")
    respx.get("https://upload.wikimedia.org/thumb/carte-1280.png").mock(
        return_value=httpx.Response(200, content=noisy_buf.getvalue())
    )
    with pytest.raises(OsaraiError) as size_exc:
        fetch_commons_image("File:Carte_monde.png", theme_dir, "trop-lourd", sources)
    assert size_exc.value.exit_code == ExitCode.VALIDATION_ERROR


def test_occlusion_preview_generates_full_and_mobile_320w(sample_repo: Path) -> None:
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    out_dir = sample_repo / ".osarai_tmp" / "previews"

    generated = generate_occlusion_previews(
        theme_dir,
        out_dir,
        item_id="c4-svt-la-respiration-c0001",
    )
    assert len(generated) == 2
    full_png, mobile_png = generated
    assert full_png.name == "c4-svt-la-respiration-c0001--full.png"
    assert mobile_png.name == "c4-svt-la-respiration-c0001--mobile-320w.png"

    with Image.open(full_png) as img_full:
        assert img_full.size == (640, 480)
        # Vérifier l'opacité totale (alpha=255, zéro transparence) et la distinction target/mask
        target_px = img_full.getpixel((int(0.16 * 640), int(0.22 * 480)))
        mask_px = img_full.getpixel((int(0.56 * 640), int(0.62 * 480)))
        assert target_px == (180, 83, 9)
        assert mask_px == (71, 85, 105)

    with Image.open(mobile_png) as img_mob:
        assert img_mob.width == 320


@respx.mock
def test_url_checker_youtube_oembed_soft404_and_diff_blocking(git_sample_repo: Path) -> None:
    sources = _load_root_sources()

    # 1) Sondage YouTube exclusivement via oEmbed + canonisation youtu.be/<id>?si=...
    oembed_route = respx.get("https://www.youtube.com/oembed").mock(
        return_value=httpx.Response(
            200,
            json={
                "title": "Les échanges gazeux — Lumni",
                "author_url": "https://www.youtube.com/@lumni",
            },
        )
    )
    # Toute requête directe vers youtube.com/watch échouerait si elle était émise
    watch_route = respx.get("https://www.youtube.com/watch").mock(return_value=httpx.Response(500))

    # Pages standards : 200 valide > 64 Ko, Soft-404 par titre, Soft-404 redirection vers `/`
    big_valid_html = (
        b"<html><head><title>Cours complet sur la respiration</title></head>"
        b"<body><h1>La respiration humaine</h1>" + (b"A" * 90000) + b"</body></html>"
    )
    respx.get("https://www.lumni.fr/video/la-respiration-humaine").mock(
        return_value=httpx.Response(200, content=big_valid_html)
    )
    respx.get("https://www.lumni.fr/video/supprimee").mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>Oups - Page introuvable</title></head><body></body></html>",
        )
    )
    respx.get("https://www.lelivrescolaire.fr/page/ancienne").mock(
        return_value=httpx.Response(302, headers={"Location": "https://www.lelivrescolaire.fr/"})
    )
    respx.get("https://www.lelivrescolaire.fr/").mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>Accueil Lelivrescolaire</title></head></html>",
        )
    )

    probed = asyncio.run(
        probe_urls(
            [
                "https://youtu.be/dQw4w9WgXcQ?si=tracking123&utm_source=share",
                "https://www.lumni.fr/video/la-respiration-humaine",
                "https://www.lumni.fr/video/supprimee",
                "https://www.lelivrescolaire.fr/page/ancienne",
            ],
            sources,
        )
    )
    assert oembed_route.called
    assert not watch_route.called
    assert probed[0].ok is True
    assert probed[0].canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert probed[1].ok is True
    assert probed[1].title == "Cours complet sur la respiration"
    assert probed[2].verdict == "soft_404"
    assert probed[3].verdict == "soft_404"

    # 2) check_repository_urls global avec link-report.json : 429 -> warning (OK)
    respx.get("https://fr.vikidia.org/wiki/Appareil_respiratoire").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "15"})
    )
    report_path = git_sample_repo / ".osarai_tmp" / "link-report.json"
    summary = asyncio.run(check_repository_urls(git_sample_repo, sources, json_report=report_path))
    assert summary.ok is True
    assert len(summary.dead_links) == 0
    assert len(summary.warnings) == 1
    report_json = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(report_json.keys()) == {"checked_at", "dead_links", "warnings"}

    # 3) En mode `--diff origin/main`, tout échec oEmbed (même 429) d'un nouveau lien YouTube bloque
    subprocess.run(
        ["git", "-C", str(git_sample_repo), "checkout", "-b", "pr-new-yt"],
        check=True,
        capture_output=True,
    )
    res_yaml = git_sample_repo / "content" / "cycle-4" / "svt" / "la-respiration" / "resources.yaml"
    dump_yaml_roundtrip(
        res_yaml,
        lambda d: d["resources"].append(
            {
                "title": "Nouvelle vidéo YouTube",
                "url": "https://www.youtube.com/watch?v=12345678901",
                "source_domain": "youtube.com",
                "type": "video",
                "channel_url": "https://www.youtube.com/@Lumni",
                "last_verified_at": "2026-11-20",
            }
        ),
    )
    respx.get("https://www.youtube.com/oembed").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )
    diff_summary = asyncio.run(
        check_repository_urls(git_sample_repo, sources, diff_ref="origin/main")
    )
    assert diff_summary.ok is False
    assert diff_summary.exit_code == ExitCode.RATE_LIMITED
    assert len(diff_summary.dead_links) == 1


@respx.mock
def test_jalon2_edge_cases_and_error_branches(sample_repo: Path, tmp_path: Path) -> None:
    sources = _load_root_sources()
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"

    # 1) occlusion_preview sur un QCM avec front_occluded + erreurs d'entrées
    dump_yaml_roundtrip(
        theme_dir / "quiz.yaml",
        lambda d: (
            d["questions"][0].__setitem__("asset_id", "alveoles"),
            d["questions"][0].__setitem__("asset_role", "front_occluded"),
            d["questions"][0].__setitem__(
                "occlusions",
                [
                    {
                        "id": "q-occ",
                        "x": 10.0,
                        "y": 15.0,
                        "w": 20.0,
                        "h": 15.0,
                        "role": "target",
                        "badge": "?",
                    }
                ],
            ),
        ),
    )
    all_previews = generate_occlusion_previews(theme_dir, tmp_path / "previews")
    assert len(all_previews) == 4  # 1 carte + 1 QCM -> 4 fichiers PNG

    with pytest.raises(OsaraiError):
        generate_occlusion_previews(tmp_path / "absent", tmp_path / "previews")
    with pytest.raises(OsaraiError):
        generate_occlusion_previews(
            theme_dir, tmp_path / "previews", item_id="c4-svt-la-respiration-c9999"
        )

    # 2) url_checker : liste vide, non-HTTPS, domaine interdit, YouTube shorts/erreur/chaîne bannie,
    #    boucle de redirections > 5 sauts, Soft-404 titre vide & H1 404, dépôt sans content/
    assert asyncio.run(probe_urls([], sources)) == []

    respx.get("https://www.youtube.com/oembed").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "title": "Chaîne non autorisée",
                    "author_url": "https://www.youtube.com/@Pirate",
                },
            ),
            httpx.Response(404),
            httpx.Response(500),
        ]
    )
    respx.get("https://www.lumni.fr/vide").mock(
        return_value=httpx.Response(200, text="<html><head><title>   </title></head></html>")
    )
    respx.get("https://www.lumni.fr/h1-404").mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>Lumni</title><style>body{}</style></head>"
            "<body><h1>Erreur 404</h1></body></html>",
        )
    )
    respx.get("https://www.lumni.fr/loop").mock(
        return_value=httpx.Response(302, headers={"Location": "https://www.lumni.fr/loop"})
    )
    respx.get("https://www.lumni.fr/to-http").mock(
        return_value=httpx.Response(301, headers={"Location": "http://www.lumni.fr/insecure"})
    )
    respx.get("https://www.lumni.fr/err500").mock(return_value=httpx.Response(500))

    edge_probes = asyncio.run(
        probe_urls(
            [
                "http://www.lumni.fr/non-https",
                "https://domaine-interdit.example/page",
                "https://www.youtube.com/watch?v=invalide",
                "https://www.youtube.com/shorts/abcdefghijk",
                "https://www.youtube.com/watch?v=11111111111",
                "https://www.youtube.com/watch?v=22222222222",
                "https://www.lumni.fr/vide",
                "https://www.lumni.fr/h1-404",
                "https://www.lumni.fr/loop",
                "https://www.lumni.fr/to-http",
                "https://www.lumni.fr/err500",
            ],
            sources,
        )
    )
    verdicts = [p.verdict for p in edge_probes]
    assert verdicts == [
        "disallowed",
        "disallowed",
        "dead",
        "disallowed",
        "dead",
        "error",
        "soft_404",
        "soft_404",
        "disallowed",
        "disallowed",
        "error",
    ]

    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    empty_rep_file = tmp_path / "empty-report.json"
    empty_sum = asyncio.run(check_repository_urls(empty_repo, sources, json_report=empty_rep_file))
    assert empty_sum.ok is True
    assert empty_rep_file.is_file()

    # 3) grounding_fetcher : recherche multi-domaines, ?title=, 429 RATE_LIMITED, page manquante
    respx.get("https://fr.vikidia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={"query": {"search": [{"title": "A", "snippet": "S", "wordcount": 10}]}},
        )
    )
    respx.get("https://fr.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={"query": {"search": [{"title": "B", "snippet": "S", "wordcount": 20}]}},
        )
    )
    multi_hits = search_grounding("test", sources)
    assert len(multi_hits) == 2

    respx.get("https://fr.vikidia.org/w/api.php").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "12"})
    )
    with pytest.raises(OsaraiError) as rl_exc:
        fetch_grounding("https://fr.vikidia.org/w/index.php?title=Respiration", sources)
    assert rl_exc.value.exit_code == ExitCode.RATE_LIMITED
    assert rl_exc.value.details["retry_after_seconds"] == 12

    respx.get("https://fr.vikidia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "rightsinfo": {
                        "url": "https://creativecommons.org/licenses/by-sa/3.0/",
                        "text": "CC BY-SA 3.0",
                    },
                    "pages": {"-1": {"missing": ""}},
                }
            },
        )
    )
    with pytest.raises(OsaraiError) as miss_exc:
        fetch_grounding("https://fr.vikidia.org/wiki/Inexistant", sources)
    assert miss_exc.value.exit_code == ExitCode.UPSTREAM_NOT_FOUND

    # 4) bo_sync & commons_fetcher : 429 / 404 / Fichier: prefix
    respx.get("https://eduscol.education.gouv.fr/404.pdf").mock(return_value=httpx.Response(404))
    with pytest.raises(OsaraiError) as bo_404:
        discover_eduscol_pdfs("https://eduscol.education.gouv.fr/404.pdf", sources)
    assert bo_404.value.exit_code == ExitCode.UPSTREAM_NOT_FOUND

    respx.get("https://commons.wikimedia.org/w/api.php").mock(
        return_value=httpx.Response(403, headers={"Retry-After": "20"})
    )
    with pytest.raises(OsaraiError) as cm_403:
        fetch_commons_image("Fichier:Schéma.svg", theme_dir, "schema", sources)
    assert cm_403.value.exit_code == ExitCode.RATE_LIMITED
