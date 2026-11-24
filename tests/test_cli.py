"""Tests CLI (`typer.testing.CliRunner`) pour les Jalons 1 et 2."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import respx
from PIL import Image
from typer.testing import CliRunner

from osarai import __version__
from osarai.cli import app
from osarai.yaml_io import dump_yaml_roundtrip

runner = CliRunner()


def test_cli_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_validate_text_and_json_modes(sample_repo: Path) -> None:
    res_txt = runner.invoke(app, ["validate", "--repo-root", str(sample_repo)])
    assert res_txt.exit_code == 0
    assert "Validation réussie" in res_txt.stdout

    res_json = runner.invoke(app, ["validate", "--repo-root", str(sample_repo), "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["ok"] is True
    assert data["checked_themes"] == 1
    assert data["error_count"] == 0


def test_cli_assign_ids_and_validate_failure_exit_code_2(sample_repo: Path) -> None:
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"

    def _add_items_without_id(doc: dict) -> None:
        doc["cards"].append(
            {
                "concept_id": "echanges-alveolaires",
                "reperes_level": "5eme",
                "priority": "essentiel",
                "type": "basic",
                "front": "Nouvelle carte via CLI ?",
                "back": "Réponse CLI.",
            }
        )

    dump_yaml_roundtrip(theme_dir / "flashcards.yaml", _add_items_without_id)

    fail_res = runner.invoke(app, ["validate", "--repo-root", str(sample_repo), "--json"])
    assert fail_res.exit_code == 2
    fail_payload = json.loads(fail_res.stdout)
    assert fail_payload["ok"] is False
    assert fail_payload["issues"][0]["expected_id"] == "c4-svt-la-respiration-c0021"

    assign_res = runner.invoke(app, ["assign-ids", "--theme", str(theme_dir), "--json"])
    assert assign_res.exit_code == 0
    assign_payload = json.loads(assign_res.stdout)
    assert assign_payload["assigned_card_ids"] == ["c4-svt-la-respiration-c0021"]

    ok_res = runner.invoke(app, ["validate", "--repo-root", str(sample_repo)])
    assert ok_res.exit_code == 0


def test_cli_validate_feedback_mode(tmp_path: Path) -> None:
    fb = tmp_path / "fb.json"
    fb.write_text(
        json.dumps(
            {
                "schema": "osarai-feedback-v1",
                "exported_at": "2026-11-20T10:00:00Z",
                "items": [
                    {
                        "cycle": "cycle-4",
                        "subject": "svt",
                        "theme_slug": "la-respiration",
                        "item_id": "c4-svt-la-respiration-q0001",
                        "item_type": "quiz",
                        "content_hash": "abcdef12",
                        "build_sha": "12345678",
                        "reason": "coquille",
                        "note": "Petite faute d'accord.",
                        "status": "open",
                        "flagged_at": "2026-11-20T09:50:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    res = runner.invoke(app, ["validate", "--feedback", str(fb), "--json"])
    assert res.exit_code == 0
    assert json.loads(res.stdout)["item_count"] == 1

    res_txt = runner.invoke(app, ["validate", "--feedback", str(fb)])
    assert res_txt.exit_code == 0
    assert "osarai-feedback-v1" in res_txt.stdout

    missing = runner.invoke(
        app, ["validate", "--feedback", str(tmp_path / "absent.json"), "--json"]
    )
    assert missing.exit_code == 2
    assert json.loads(missing.stdout)["ok"] is False

    missing_txt = runner.invoke(app, ["validate", "--feedback", str(tmp_path / "absent.json")])
    assert missing_txt.exit_code == 2

    bad_assign = runner.invoke(app, ["assign-ids", "--theme", str(tmp_path / "no-theme")])
    assert bad_assign.exit_code == 2


@respx.mock
def test_cli_jalon2_subcommands(sample_repo: Path, sample_tabular_pdf: Path) -> None:
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"

    # 1) preview-occlusions
    prev_res = runner.invoke(
        app,
        [
            "preview-occlusions",
            "--repo-root",
            str(sample_repo),
            "--theme",
            str(theme_dir),
            "--json",
        ],
    )
    assert prev_res.exit_code == 0
    assert json.loads(prev_res.stdout)["count"] == 2

    # 2) sync-bo --discover-url et erreurs d'options
    bad_bo = runner.invoke(app, ["sync-bo", "--repo-root", str(sample_repo)])
    assert bad_bo.exit_code == 2

    respx.get("https://eduscol.education.gouv.fr/4362/enseigner-au-cycle-4").mock(
        return_value=httpx.Response(
            200,
            text='<a href="/doc/prog.pdf">Programme</a>',
        )
    )
    bo_disc = runner.invoke(
        app,
        [
            "sync-bo",
            "--repo-root",
            str(sample_repo),
            "--discover-url",
            "https://eduscol.education.gouv.fr/4362/enseigner-au-cycle-4",
            "--json",
        ],
    )
    assert bo_disc.exit_code == 0
    assert json.loads(bo_disc.stdout)["count"] == 1

    pdf_bytes = sample_tabular_pdf.read_bytes()
    dump_yaml_roundtrip(
        sample_repo / "curriculum" / "sources" / "bo_manifest.yaml",
        lambda d: d["subjects"][0]["documents"][0].__setitem__("sha256", None),
    )
    respx.get("https://eduscol.education.gouv.fr/document/12345/download").mock(
        return_value=httpx.Response(200, content=pdf_bytes)
    )
    bo_sync = runner.invoke(
        app,
        [
            "sync-bo",
            "--repo-root",
            str(sample_repo),
            "--cycle",
            "cycle-4",
            "--subject",
            "svt",
            "--json",
        ],
    )
    assert bo_sync.exit_code == 0
    assert len(json.loads(bo_sync.stdout)["documents"]) == 1

    # 3) fetch-grounding --search et --url
    respx.get("https://fr.vikidia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "search": [{"title": "Respiration", "snippet": "Texte", "wordcount": 120}],
                    "rightsinfo": {
                        "url": "https://creativecommons.org/licenses/by-sa/3.0/deed.fr",
                        "text": "CC BY-SA 3.0",
                    },
                    "pages": {
                        "1": {
                            "pageid": 1,
                            "title": "Respiration",
                            "extract": "Contenu libre Vikidia.",
                            "revisions": [{"revid": 123, "timestamp": "2026-11-01T00:00:00Z"}],
                        }
                    },
                }
            },
        )
    )
    fg_search = runner.invoke(
        app,
        [
            "fetch-grounding",
            "--repo-root",
            str(sample_repo),
            "--search",
            "respiration",
            "--domain",
            "fr.vikidia.org",
            "--json",
        ],
    )
    assert fg_search.exit_code == 0
    assert json.loads(fg_search.stdout)["count"] == 1

    fg_url = runner.invoke(
        app,
        [
            "fetch-grounding",
            "--repo-root",
            str(sample_repo),
            "--url",
            "https://fr.vikidia.org/wiki/Respiration",
            "--json",
        ],
    )
    assert fg_url.exit_code == 0
    assert json.loads(fg_url.stdout)["credit"]["license_spdx"] == "CC-BY-SA-3.0"

    # 4) fetch-commons --search et --file
    img_buf = io.BytesIO()
    Image.new("RGB", (600, 400), color=(250, 250, 250)).save(img_buf, format="PNG")
    respx.get("https://commons.wikimedia.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {
                    "pages": {
                        "7": {
                            "title": "File:Test_img.png",
                            "imageinfo": [
                                {
                                    "mime": "image/png",
                                    "width": 600,
                                    "height": 400,
                                    "url": "https://upload.wikimedia.org/test_img.png",
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC0"},
                                        "Artist": {"value": "Auteur Libre"},
                                    },
                                }
                            ],
                        }
                    }
                }
            },
        )
    )
    respx.get("https://upload.wikimedia.org/test_img.png").mock(
        return_value=httpx.Response(200, content=img_buf.getvalue())
    )
    fc_search = runner.invoke(
        app,
        ["fetch-commons", "--repo-root", str(sample_repo), "--search", "poumon", "--json"],
    )
    assert fc_search.exit_code == 0
    assert json.loads(fc_search.stdout)["count"] == 1

    fc_import = runner.invoke(
        app,
        [
            "fetch-commons",
            "--repo-root",
            str(sample_repo),
            "--file",
            "File:Test_img.png",
            "--theme",
            str(theme_dir),
            "--asset-id",
            "schema-test",
            "--json",
        ],
    )
    assert fc_import.exit_code == 0
    assert json.loads(fc_import.stdout)["asset"]["hitl_verified"] is False

    # 5) probe-links (code 0 pour tri HITL même sur lien candidat mort) et check-urls
    respx.get("https://www.lumni.fr/video/la-respiration-humaine").mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>La respiration — Lumni</title></head></html>",
        )
    )
    respx.get("https://fr.vikidia.org/wiki/Appareil_respiratoire").mock(
        return_value=httpx.Response(
            200,
            text="<html><head><title>Appareil respiratoire — Vikidia</title></head></html>",
        )
    )
    respx.get("https://www.youtube.com/oembed").mock(
        return_value=httpx.Response(
            200,
            json={"title": "Vidéo Lumni", "author_url": "https://www.youtube.com/@Lumni"},
        )
    )
    respx.get("https://www.lumni.fr/video/introuvable").mock(return_value=httpx.Response(404))

    probe_res = runner.invoke(
        app,
        [
            "probe-links",
            "--repo-root",
            str(sample_repo),
            "--url",
            "https://www.lumni.fr/video/la-respiration-humaine",
            "--url",
            "https://www.lumni.fr/video/introuvable",
            "--json",
        ],
    )
    assert probe_res.exit_code == 0
    probe_data = json.loads(probe_res.stdout)
    assert probe_data["results"][0]["ok"] is True
    assert probe_data["results"][1]["ok"] is False

    chk_res = runner.invoke(
        app,
        ["check-urls", "--repo-root", str(sample_repo), "--json"],
    )
    assert chk_res.exit_code == 0
    assert json.loads(chk_res.stdout)["ok"] is True

    # Sorties humaines sans --json et erreurs d'options CLI
    chk_txt = runner.invoke(app, ["check-urls", "--repo-root", str(sample_repo)])
    assert chk_txt.exit_code == 0
    assert "Liens vérifiés" in chk_txt.stdout

    probe_err = runner.invoke(app, ["probe-links", "--repo-root", str(sample_repo), "--json"])
    assert probe_err.exit_code == 2

    fg_err = runner.invoke(app, ["fetch-grounding", "--repo-root", str(sample_repo), "--json"])
    assert fg_err.exit_code == 2

    fc_err = runner.invoke(
        app, ["fetch-commons", "--repo-root", str(sample_repo), "--file", "File:X.png", "--json"]
    )
    assert fc_err.exit_code == 2


def test_cli_build_site_text_and_json(sample_repo: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "dist_cli"
    res_json = runner.invoke(
        app,
        [
            "build-site",
            "--repo-root",
            str(sample_repo),
            "--output",
            str(out_dir),
            "--base-url",
            "/osarai",
            "--json",
        ],
    )
    assert res_json.exit_code == 0
    payload = json.loads(res_json.stdout)
    assert payload["ok"] is True
    assert payload["themes_count"] == 1
    assert (out_dir / "assets" / "vendor" / "katex" / "LICENSE").is_file()

    res_txt = runner.invoke(
        app,
        [
            "build-site",
            "--repo-root",
            str(sample_repo),
            "--output",
            str(tmp_path / "dist_txt"),
            "--base-url",
            "/",
        ],
    )
    assert res_txt.exit_code == 0
    assert "Portail statique compilé" in res_txt.stdout
