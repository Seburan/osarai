"""Tests CLI (`typer.testing.CliRunner`) pour le Jalon 1 (`assign-ids` et `validate`)."""

from __future__ import annotations

import json
from pathlib import Path

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

    missing = runner.invoke(app, ["validate", "--feedback", str(tmp_path / "absent.json"), "--json"])
    assert missing.exit_code == 2
    assert json.loads(missing.stdout)["ok"] is False
