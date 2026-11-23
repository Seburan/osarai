"""Tests unitaires et d'intégration du Jalon 1 (`yaml_io`, `schemas`, `id_manager`, `validator`)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from osarai import ExitCode, OsaraiError
from osarai.id_manager import assign_missing_ids
from osarai.schemas import (
    BackupPayload,
    FeedbackPayload,
    Flashcard,
    OcclusionBox,
    QuizQuestion,
    ResourceEntry,
    normalize_search_text,
)
from osarai.validator import validate_feedback_file, validate_target
from osarai.yaml_io import (
    card_canonical_fields,
    compute_content_hash,
    dump_yaml_roundtrip,
    load_yaml,
    quiz_canonical_fields,
)


def test_yaml_1_2_preserves_scientific_tokens_and_roundtrip_quotes(tmp_path: Path) -> None:
    """Vérifie que YAML 1.2 ne convertit pas `NO`, `ON` ni `1:20` en booléen/sexagésimal."""
    sample = tmp_path / "chem.yaml"
    sample.write_text(
        '# Commentaire conservé\nmonoxyde: NO\nactif: ON\nrapport: 1:20\ncite: "valeur"\n',
        encoding="utf-8",
    )
    loaded = load_yaml(sample)
    assert loaded["monoxyde"] == "NO"
    assert loaded["actif"] == "ON"
    assert loaded["rapport"] == "1:20"

    dump_yaml_roundtrip(sample, lambda doc: doc.__setitem__("ajout", 42))
    updated_text = sample.read_text(encoding="utf-8")
    assert "# Commentaire conservé" in updated_text
    assert '"valeur"' in updated_text
    assert load_yaml(sample)["ajout"] == 42


def test_normalize_search_text_folds_ligatures_and_accents() -> None:
    assert normalize_search_text("L’Œsophage du Cœur et l'Écœurement d'Ægir") == (
        "l'oesophage du coeur et l'ecoeurement d'aegir"
    )


def test_compute_content_hash_is_canonical_across_int_and_float_occlusions() -> None:
    card_int = Flashcard(
        id="c4-svt-la-respiration-c0001",
        concept_id="c1",
        reperes_level="5eme",
        priority="essentiel",
        type="basic",
        front="Question ?",
        back="Réponse",
        asset_id="alveoles",
        asset_role="front_occluded",
        occlusions=[OcclusionBox(id="b1", x=10, y=20, w=30, h=15, role="target", badge="?")],
    )
    card_float = Flashcard(
        id="c4-svt-la-respiration-c0099",
        concept_id="autre",
        reperes_level="4eme",
        priority="approfondissement",
        type="basic",
        front="Question ?",
        back="Réponse",
        asset_id="alveoles",
        asset_role="front_occluded",
        occlusions=[
            OcclusionBox(id="b1", x=10.0, y=20.0, w=30.0, h=15.0, role="target", badge="?")
        ],
    )
    h1 = compute_content_hash(card_canonical_fields(card_int.model_dump(mode="json")))
    h2 = compute_content_hash(card_canonical_fields(card_float.model_dump(mode="json")))
    assert len(h1) == 8
    assert h1 == h2

    q = QuizQuestion(
        concept_id="c1",
        reperes_level="5eme",
        difficulty="facile",
        question="Q ?",
        choices=["A", "B", "C", "D"],
        answer_index=0,
        explanation="Explication",
    )
    qh = compute_content_hash(quiz_canonical_fields(q.model_dump(mode="json")))
    assert len(qh) == 8


def test_flashcard_rejects_cloze_with_front_occluded_and_invalid_latex() -> None:
    # Interdiction `type: cloze` + `asset_role: front_occluded`
    with pytest.raises(ValidationError, match="front_occluded"):
        Flashcard(
            concept_id="c1",
            reperes_level="5eme",
            priority="essentiel",
            type="cloze",
            front="Le gaz est {{c1::le dioxygène}}.",
            back="",
            asset_id="alveoles",
            asset_role="front_occluded",
            occlusions=[OcclusionBox(id="b1", x=10, y=10, w=20, h=20, role="target", badge="?")],
        )

    # Interdiction de `\ce{...}`
    with pytest.raises(ValidationError, match=r"\\ce"):
        Flashcard(
            concept_id="c1",
            reperes_level="5eme",
            priority="essentiel",
            type="basic",
            front="Formule du dioxyde de carbone ?",
            back=r"\(\ce{CO2}\)",
        )

    # Interdiction de couper `\(...\)` par `{{c1::...}}`
    with pytest.raises(ValidationError, match="Délimiteur"):
        Flashcard(
            concept_id="c1",
            reperes_level="5eme",
            priority="essentiel",
            type="cloze",
            front=r"La fraction vaut \({{c1::\frac{1}{2} }}\).",
            back="",
        )

    # Espace obligatoire avant `}}` lorsque la réponse se termine par `}`
    with pytest.raises(ValidationError, match="espace avant"):
        Flashcard(
            concept_id="c1",
            reperes_level="5eme",
            priority="essentiel",
            type="cloze",
            front=r"La fraction vaut {{c1::\(\frac{1}{2}\)}} ou {{c2::\text{O}}}.",
            back="",
        )

    # Indices Cloze non contigus (`c1` et `c3` sans `c2`)
    with pytest.raises(ValidationError, match="contigus"):
        Flashcard(
            concept_id="c1",
            reperes_level="5eme",
            priority="essentiel",
            type="cloze",
            front="Test {{c1::alpha}} et {{c3::gamma}}.",
            back="",
        )


def test_badge_anti_disclosure_direction() -> None:
    """Badge `'1'` autorisé si réponse `'12 organes'`, mais réponse dans badge rejetée."""
    valid_card = Flashcard(
        concept_id="c1",
        reperes_level="5eme",
        priority="essentiel",
        type="basic",
        front="Combien d'éléments en 1 ?",
        back="12 organes",
        asset_id="alveoles",
        asset_role="front_occluded",
        occlusions=[OcclusionBox(id="b1", x=10, y=10, w=20, h=20, role="target", badge="1")],
    )
    assert valid_card.occlusions[0].badge == "1"

    with pytest.raises(ValidationError, match="Anti-divulgation"):
        Flashcard(
            concept_id="c1",
            reperes_level="5eme",
            priority="essentiel",
            type="basic",
            front="Quel gaz ?",
            back="O2",
            asset_id="alveoles",
            asset_role="front_occluded",
            occlusions=[OcclusionBox(id="b1", x=10, y=10, w=20, h=20, role="target", badge="O2")],
        )


def test_resource_entry_rejects_trackers_and_non_canonical_youtube() -> None:
    with pytest.raises(ValidationError, match="pistage"):
        ResourceEntry(
            title="Lien pisté",
            url="https://www.lumni.fr/video/test?fbclid=123",
            source_domain="lumni.fr",
            type="video",
            last_verified_at="2026-11-15",
        )

    with pytest.raises(ValidationError, match="canonique"):
        ResourceEntry(
            title="YouTube court",
            url="https://youtu.be/dQw4w9WgXcQ",
            source_domain="youtu.be",
            type="video",
            channel_url="https://www.youtube.com/@Lumni",
            last_verified_at="2026-11-15",
        )


def test_validate_happy_path_and_empty_repo_tolerance(sample_repo: Path, tmp_path: Path) -> None:
    report = validate_target(sample_repo)
    assert report.ok, [i.to_dict() for i in report.issues]
    assert report.checked_themes == 1
    assert report.warnings == []

    # Jalon 1–3 : tolérance à l'absence de `curriculum/` et `content/`
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    shutil.copy2(sample_repo / "sources.yaml", empty_repo / "sources.yaml")
    empty_report = validate_target(empty_repo)
    assert empty_report.ok
    assert empty_report.checked_themes == 0


def test_assign_ids_monotonic_after_retiring_last_card(sample_repo: Path) -> None:
    """Si `c0030` est dans `retired_ids` (`last_card_seq: 30`), la suivante reçoit `c0031`."""
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    dump_yaml_roundtrip(
        theme_dir / "meta.yaml",
        lambda doc: (
            doc.__setitem__("last_card_seq", 30),
            doc.__setitem__("last_quiz_seq", 11),
            doc.__setitem__(
                "retired_ids",
                ["c4-svt-la-respiration-c0030", "c4-svt-la-respiration-q0011"],
            ),
        ),
    )

    def _append_unnumbered(doc: dict) -> None:
        doc["cards"].append(
            {
                "concept_id": "besoins-organes",
                "reperes_level": "5eme",
                "priority": "approfondissement",
                "type": "basic",
                "front": "Nouvelle carte ajoutée sans identifiant ?",
                "back": "Elle reçoit c0031.",
            }
        )

    def _append_unnumbered_quiz(doc: dict) -> None:
        doc["questions"].append(
            {
                "concept_id": "besoins-organes",
                "reperes_level": "5eme",
                "difficulty": "moyen",
                "question": "Nouveau QCM sans identifiant ?",
                "choices": ["Choix 1", "Choix 2", "Choix 3", "Choix 4"],
                "answer_index": 0,
                "explanation": "Il reçoit q0012 car q0011 est retiré.",
            }
        )

    dump_yaml_roundtrip(theme_dir / "flashcards.yaml", _append_unnumbered)
    dump_yaml_roundtrip(theme_dir / "quiz.yaml", _append_unnumbered_quiz)

    # Avant `assign-ids`, `validate` signale l'ID exact attendu (`c0031` / `q0012`)
    pre_report = validate_target(sample_repo)
    assert not pre_report.ok
    missing_err = next(e for e in pre_report.errors if e.code == "MISSING_CARD_ID")
    assert missing_err.expected_id == "c4-svt-la-respiration-c0031"
    assert missing_err.expected_seq_value == 31
    assert missing_err.line is not None
    missing_q = next(e for e in pre_report.errors if e.code == "MISSING_QUIZ_ID")
    assert missing_q.expected_id == "c4-svt-la-respiration-q0012"
    assert missing_q.expected_seq_value == 12

    # Exécuter `assign-ids` puis revalider
    res = assign_missing_ids(theme_dir)
    assert res.assigned_card_ids == ["c4-svt-la-respiration-c0031"]
    assert res.assigned_quiz_ids == ["c4-svt-la-respiration-q0012"]
    assert res.last_card_seq == 31
    assert res.last_quiz_seq == 12
    assert validate_target(sample_repo).ok


def test_allow_empty_resources_flag(sample_repo: Path) -> None:
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    (theme_dir / "resources.yaml").write_text(
        "schema_version: 1\nresources: []\n", encoding="utf-8"
    )

    assert not validate_target(sample_repo, allow_empty_resources=False).ok
    assert validate_target(sample_repo, allow_empty_resources=True).ok


def test_asset_size_warning_vs_ceiling_and_summary_checks(sample_repo: Path) -> None:
    import hashlib

    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    asset_path = theme_dir / "assets" / "c4-svt-la-respiration--alveoles.webp"

    base_bytes = asset_path.read_bytes()
    noisy_big = Image.effect_noise((900, 700), 120.0).convert("RGB")
    noisy_big.save(asset_path, format="WEBP", lossless=True)
    sha_big = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    assert asset_path.stat().st_size > 300 * 1024
    dump_yaml_roundtrip(
        theme_dir / "assets.yaml",
        lambda d: (
            d["assets"][0].__setitem__("width", 900),
            d["assets"][0].__setitem__("height", 700),
            d["assets"][0].__setitem__("sha256", sha_big),
        ),
    )
    over_report = validate_target(sample_repo)
    assert any(e.code == "ASSET_TOO_LARGE" for e in over_report.errors)

    # Générer une image exactement entre 150 Ko et 300 Ko
    med_img = Image.effect_noise((520, 420), 100.0).convert("RGB")
    med_img.save(asset_path, format="WEBP", lossless=True)
    med_sha = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    assert 150 * 1024 < asset_path.stat().st_size <= 300 * 1024
    dump_yaml_roundtrip(
        theme_dir / "assets.yaml",
        lambda d: (
            d["assets"][0].__setitem__("width", 520),
            d["assets"][0].__setitem__("height", 420),
            d["assets"][0].__setitem__("sha256", med_sha),
        ),
    )
    warn_report = validate_target(sample_repo)
    assert warn_report.ok
    assert any(w_iss.code == "ASSET_SIZE_WARNING" for w_iss in warn_report.warnings)

    # Restaurer l'image et vérifier les erreurs summary.md + fichier orphelin
    asset_path.write_bytes(base_bytes)
    orig_sha = hashlib.sha256(base_bytes).hexdigest()
    (theme_dir / "assets" / "orphelin.webp").write_bytes(base_bytes)
    dump_yaml_roundtrip(
        theme_dir / "assets.yaml",
        lambda d: (
            d["assets"][0].__setitem__("width", 640),
            d["assets"][0].__setitem__("height", 480),
            d["assets"][0].__setitem__("sha256", orig_sha),
        ),
    )
    (theme_dir / "summary.md").write_text(
        "# Titre H1 interdit\n\n## L'essentiel à retenir\n"
        "![ext](https://example.org/x.png)\n![](assets/inconnu.webp)\n"
        "<div>html</div> \\(\\ce{CO2}\\)\n",
        encoding="utf-8",
    )
    bad_sum_report = validate_target(sample_repo)
    codes = {e.code for e in bad_sum_report.errors}
    assert "ORPHAN_ASSET_FILE" in codes
    assert "SUMMARY_H1_FORBIDDEN" in codes
    assert "SUMMARY_REMOTE_OR_INVALID_IMAGE" in codes
    assert "SUMMARY_EMPTY_ALT" in codes
    assert "SUMMARY_UNDECLARED_ASSET" in codes
    assert "SUMMARY_RAW_HTML" in codes
    assert "SUMMARY_INVALID_LATEX" in codes
    assert "SUMMARY_MISSING_SECTION" in codes


def test_git_immutability_merge_base_checks(git_sample_repo: Path) -> None:
    """Vérifie `--against-ref origin/main` via `merge-base` (retraits, compteurs, suppression)."""
    theme_dir = git_sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"

    # Enregistrer un ID retiré dans l'état initial de `main` pour tester RETIRED_ID_REMOVED/REUSED
    dump_yaml_roundtrip(
        theme_dir / "meta.yaml",
        lambda d: (
            d.__setitem__("last_card_seq", 21),
            d.__setitem__("last_quiz_seq", 11),
            d.__setitem__(
                "retired_ids",
                ["c4-svt-la-respiration-c0021", "c4-svt-la-respiration-q0011"],
            ),
        ),
    )
    subprocess.run(["git", "-C", str(git_sample_repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(git_sample_repo), "commit", "-m", "record retired ids"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(git_sample_repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )

    # Avancer `origin/main` d'un commit indépendant pour exercer `git merge-base`
    subprocess.run(
        ["git", "-C", str(git_sample_repo), "checkout", "-b", "feature-pr"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(git_sample_repo), "checkout", "main"],
        check=True,
        capture_output=True,
    )
    (git_sample_repo / "NOTE.txt").write_text("commit sur main parallèle\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(git_sample_repo), "add", "NOTE.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(git_sample_repo), "commit", "-m", "parallel main advance"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(git_sample_repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(git_sample_repo), "checkout", "feature-pr"],
        check=True,
        capture_output=True,
    )

    # 1) Retirer c0020/q0010 sans retired_ids, réactiver c0021/q0011, muter c0002 et baisser seq
    def _mutate_cards(doc: dict) -> None:
        doc["cards"].pop()
        doc["cards"].append(
            {
                "id": "c4-svt-la-respiration-c0021",
                "concept_id": "besoins-organes",
                "reperes_level": "5eme",
                "priority": "essentiel",
                "type": "basic",
                "front": "Réactivation interdite ?",
                "back": "Oui.",
            }
        )
        doc["cards"][1]["type"] = "basic"
        doc["cards"][1]["front"] = "Ancienne carte cloze convertie en basic ?"
        doc["cards"][1]["back"] = "Interdit sur le même ID."

    def _mutate_quiz(doc: dict) -> None:
        doc["questions"].pop()
        doc["questions"].append(
            {
                "id": "c4-svt-la-respiration-q0011",
                "concept_id": "besoins-organes",
                "reperes_level": "5eme",
                "difficulty": "facile",
                "question": "QCM réactivé ?",
                "choices": ["A", "B", "C", "D"],
                "answer_index": 0,
                "explanation": "Explication.",
            }
        )

    dump_yaml_roundtrip(theme_dir / "flashcards.yaml", _mutate_cards)
    dump_yaml_roundtrip(theme_dir / "quiz.yaml", _mutate_quiz)
    dump_yaml_roundtrip(
        theme_dir / "meta.yaml",
        lambda d: (
            d.__setitem__("last_card_seq", 20),
            d.__setitem__("last_quiz_seq", 10),
            d.__setitem__("retired_ids", []),
        ),
    )

    rep = validate_target(git_sample_repo, against_ref="origin/main")
    err_codes = {e.code for e in rep.errors}
    assert "ID_DELETED_WITHOUT_RETIRING" in err_codes
    assert "CARD_TYPE_CHANGED" in err_codes
    assert "COUNTER_DECREASED" in err_codes
    assert "RETIRED_ID_REMOVED" in err_codes
    assert "RETIRED_ID_REUSED" in err_codes

    # 2) Supprimer tout le dossier du thème -> `THEME_DELETED`
    shutil.rmtree(theme_dir)
    del_rep = validate_target(git_sample_repo, against_ref="origin/main")
    assert any(e.code == "THEME_DELETED" for e in del_rep.errors)

    # 3) Référence Git inconnue -> `OsaraiError`
    with pytest.raises(OsaraiError):
        validate_target(git_sample_repo, against_ref="refs/heads/inexistant")


def test_validate_feedback_raw_json_markdown_fence_and_security(tmp_path: Path) -> None:
    payload_obj = {
        "schema": "osarai-feedback-v1",
        "exported_at": "2026-11-20T10:00:00Z",
        "items": [
            {
                "cycle": "cycle-4",
                "subject": "svt",
                "theme_slug": "la-respiration",
                "item_id": "c4-svt-la-respiration-c0002#c1",
                "item_type": "flashcard",
                "content_hash": "0123abcd",
                "build_sha": "deadbeef",
                "reason": "formulation_ambigue",
                "note": "Indice légèrement ambigu.",
                "status": "open",
                "flagged_at": "2026-11-20T09:55:00Z",
            }
        ],
    }

    raw_file = tmp_path / "feedback.json"
    raw_file.write_text(json.dumps(payload_obj), encoding="utf-8")
    parsed_raw = validate_feedback_file(raw_file)
    assert isinstance(parsed_raw, FeedbackPayload)
    assert parsed_raw.items[0].item_id.endswith("#c1")

    md_file = tmp_path / "issue_body.md"
    formatted_json = json.dumps(payload_obj, indent=2)
    md_file.write_text(
        f"Bonjour,\nVoici le signalement :\n\n```osarai-feedback-v1\n{formatted_json}\n```\n",
        encoding="utf-8",
    )
    parsed_md = validate_feedback_file(md_file)
    assert len(parsed_md.items) == 1

    # Rejet de traversée de chemin `../` dans `theme_slug` et note > 300 car.
    bad_obj = json.loads(json.dumps(payload_obj))
    bad_obj["items"][0]["theme_slug"] = "../secret"
    bad_obj["items"][0]["note"] = "x" * 305
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps(bad_obj), encoding="utf-8")
    with pytest.raises(OsaraiError) as exc_info:
        validate_feedback_file(bad_file)
    assert exc_info.value.exit_code == ExitCode.VALIDATION_ERROR

    # Fichier vide, bloc absent et JSON mal formé
    empty_fb = tmp_path / "empty.txt"
    empty_fb.write_text("   \n", encoding="utf-8")
    with pytest.raises(OsaraiError):
        validate_feedback_file(empty_fb)

    no_fence = tmp_path / "nofence.md"
    no_fence.write_text("Texte sans bloc feedback", encoding="utf-8")
    with pytest.raises(OsaraiError):
        validate_feedback_file(no_fence)

    broken_json = tmp_path / "broken.json"
    broken_json.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(OsaraiError):
        validate_feedback_file(broken_json)


def test_backup_payload_validation() -> None:
    backup = BackupPayload.model_validate(
        {
            "schema": "osarai-backup-v1",
            "exported_at": "2026-11-20T12:00:00Z",
            "grade": "5eme",
            "progress": {
                "cycle-4:svt:la-respiration": {
                    "cards": {
                        "c4-svt-la-respiration-c0001": {
                            "state": "a_revoir",
                            "updated_at": "2026-11-20T11:59:00Z",
                        }
                    },
                    "quiz": {
                        "best_score": 8,
                        "total": 10,
                        "missed_ids": ["c4-svt-la-respiration-q0003"],
                        "updated_at": "2026-11-20T11:59:00Z",
                    },
                }
            },
            "flags": [],
        }
    )
    assert backup.grade == "5eme"

    with pytest.raises(ValidationError, match="progress"):
        BackupPayload.model_validate(
            {
                "schema": "osarai-backup-v1",
                "exported_at": "2026-11-20T12:00:00Z",
                "grade": "5eme",
                "progress": {"cle_invalide": {}},
                "flags": [],
            }
        )


def test_yaml_io_errors_and_schema_edge_cases(tmp_path: Path) -> None:
    from osarai.schemas import (
        AssetEntry,
        CurriculumFile,
        FeedbackItem,
        SourcesPolicy,
        ThemeMeta,
        parse_cloze_tokens,
        validate_latex_fragment,
        validate_no_raw_html,
    )
    from osarai.yaml_io import get_yaml_line, load_yaml_with_lines

    missing = tmp_path / "missing.yaml"
    with pytest.raises(OsaraiError):
        load_yaml(missing)
    with pytest.raises(OsaraiError):
        load_yaml_with_lines(missing)
    with pytest.raises(OsaraiError):
        dump_yaml_roundtrip(missing, lambda d: None)

    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_yaml.write_text("a: [unclosed\n", encoding="utf-8")
    with pytest.raises(OsaraiError):
        load_yaml(invalid_yaml)
    with pytest.raises(OsaraiError):
        load_yaml_with_lines(invalid_yaml)
    with pytest.raises(OsaraiError):
        dump_yaml_roundtrip(invalid_yaml, lambda d: None)

    assert get_yaml_line({"a": 1}, "a") is None

    # HTML brut autorisé dans code span, rejeté hors code span
    validate_no_raw_html("Utilisez `<span>` en exemple.")
    with pytest.raises(ValueError, match="HTML brut"):
        validate_no_raw_html("Texte <b>gras</b> interdit")

    # Cas limites LaTeX et Cloze
    for bad_tex in [
        r"\(a \(b\)\)",
        r"a \)",
        r"\[a \[b\]\]",
        r"a \]",
        r"\[non ferme",
        r"\(\frac{1}{2}}\)",
        r"\(\frac{1}{2\)",
    ]:
        with pytest.raises(ValueError):
            validate_latex_fragment(bad_tex, allow_block=True)
    with pytest.raises(ValueError, match="bloc"):
        validate_latex_fragment(r"\[x=1\]", allow_block=False)

    for bad_cloze in [
        "{{mauvais}}",
        "{{c1::unclosed",
        "{{c1::a}b}}",
        "{{c1::   }}",
        "{{c1::a::b::c}}",
    ]:
        with pytest.raises(ValueError):
            parse_cloze_tokens(bad_cloze)

    # OcclusionBox bornes et badge
    assert OcclusionBox(id="b1", x=0, y=0, w=10, h=10, role="mask", badge="   ").badge is None
    with pytest.raises(ValidationError):
        OcclusionBox(id="b1", x=90, y=10, w=20, h=10, role="target", badge="?")
    with pytest.raises(ValidationError):
        OcclusionBox(id="b1", x=10, y=10, w=20, h=10, role="target", badge="TROP_LONG")

    # SourcesPolicy sous-domaines et erreurs
    sources = SourcesPolicy.model_validate(load_yaml(Path("sources.yaml")))
    assert sources.find_domain_rule("https://m.lumni.fr/video/x") is not None
    assert sources.find_domain_rule("https://inconnu.example.org/x") is None
    assert not sources.is_allowed_resource_domain("https://commons.wikimedia.org/wiki/File:X.svg")

    # AssetEntry, CurriculumFile, ThemeMeta, FeedbackItem cas d'erreur
    with pytest.raises(ValidationError):
        AssetEntry(
            asset_id="alveoles",
            filename="c4-svt-la-respiration--autre.webp",
            width=100,
            height=100,
            sha256="a" * 64,
            commons_title="File:Test.svg",
            source_url="https://commons.wikimedia.org/wiki/File:Test.svg",
            license_spdx="CC0-1.0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            author="Auteur",
            title="Titre",
            modifications_note=" WebP ",
        )

    with pytest.raises(ValidationError):
        CurriculumFile(
            schema_version=1,
            cycle="cycle-4",
            subject="svt",
            subject_code="svt",
            subject_label="SVT",
            bo_sources=[
                {
                    "title": "BO",
                    "producer": "MEN",
                    "publication_date": "2020-07-30",
                    "url": "https://eduscol.education.gouv.fr/doc.pdf",
                    "license_spdx": "Etalab-2.0",
                    "license_url": "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
                    "sha256": "b" * 64,
                }
            ],
            themes=[
                {
                    "theme_slug": "t1",
                    "title": "T1",
                    "macro_theme_bo": "M",
                    "reperes_levels": ["6eme"],
                    "attendus_bo": ["A"],
                    "scope_exclusions": ["E"],
                }
            ],
        )

    with pytest.raises(ValidationError):
        ThemeMeta(
            schema_version=1,
            cycle="cycle-4",
            subject="svt",
            subject_code="svt",
            theme_slug="la-respiration",
            title="Titre",
            reperes_levels=["5eme"],
            scope_exclusions=["Excl"],
            qa_status="hitl_verified",
            key_concepts=[{"concept_id": "c1", "label": "L", "reperes_level": "4eme"}],
            last_card_seq=1,
            last_quiz_seq=1,
        )

    with pytest.raises(ValidationError):
        FeedbackItem(
            cycle="cycle-4",
            subject="svt",
            theme_slug="la-respiration",
            item_id="c4-svt-la-respiration-c0001",
            item_type="quiz",
            content_hash="0123abcd",
            build_sha="deadbeef",
            reason="coquille",
            flagged_at="2026-11-20T10:00:00Z",
        )


def test_validator_cross_file_invariants_and_warnings(sample_repo: Path) -> None:
    """Exerce les contrôles croisés de `validator.py` (avertissements Cloze/longueur, conflits)."""
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"

    # Avertissements non bloquants : réponse > 250 car. et auto-divulgation Cloze dans `front`
    def _inject_warnings(doc: dict) -> None:
        doc["cards"][2]["back"] = "x" * 260
        doc["cards"][1]["front"] = (
            "Le dioxygène est vital : un muscle consomme {{c1::dioxygène}} "
            "et rejette {{c2::" + ("y" * 255) + "}}."
        )

    dump_yaml_roundtrip(theme_dir / "flashcards.yaml", _inject_warnings)
    warn_rep = validate_target(sample_repo, theme_dir=theme_dir)
    assert warn_rep.ok
    warn_codes = {w.code for w in warn_rep.warnings}
    assert "ANSWER_LENGTH_WARNING" in warn_codes
    assert "CLOZE_SELF_DISCLOSURE_WARNING" in warn_codes

    # Conflits bloquants : `active_ids ∩ retired_ids`, concept non couvert, licence interdite
    dump_yaml_roundtrip(
        theme_dir / "meta.yaml",
        lambda d: (
            d.__setitem__(
                "retired_ids",
                ["c4-svt-la-respiration-c0001", "c4-svt-la-respiration-q0001"],
            ),
            d["key_concepts"].append(
                {"concept_id": "non-couvert", "label": "Orphelin", "reperes_level": "5eme"}
            ),
            d["sources_used"][0].__setitem__("license_spdx", "CC-BY-NC-SA-4.0"),
            d["sources_used"][0].__setitem__("url", "https://www.lumni.fr/article/test"),
            d["sources_used"][0].__setitem__("source_domain", "vikidia.org"),
        ),
    )
    dump_yaml_roundtrip(
        theme_dir / "assets.yaml",
        lambda d: (
            d["assets"][0].__setitem__("hitl_verified", False),
            d["assets"][0].__setitem__("width", 999),
            d["assets"][0].__setitem__("sha256", "0" * 64),
        ),
    )
    dump_yaml_roundtrip(
        theme_dir / "resources.yaml",
        lambda d: (
            d["resources"][2].__setitem__("channel_url", "https://www.youtube.com/@ChaineInconnue"),
        ),
    )
    dump_yaml_roundtrip(
        sample_repo / "curriculum" / "sources" / "bo_manifest.yaml",
        lambda d: d["subjects"][0]["documents"][0].__setitem__("sha256", None),
    )

    err_rep = validate_target(sample_repo)
    assert not err_rep.ok
    codes = {e.code for e in err_rep.errors}
    assert "ACTIVE_ID_IN_RETIRED" in codes
    assert "UNCOVERED_CONCEPT" in codes
    assert "DISALLOWED_LICENSE" in codes
    assert "SOURCE_DOMAIN_MISMATCH" in codes
    assert "DISALLOWED_GROUNDING_DOMAIN" in codes
    assert "ASSET_NOT_HITL_VERIFIED" in codes
    assert "ASSET_DIMENSIONS_MISMATCH" in codes
    assert "ASSET_SHA256_MISMATCH" in codes
    assert "DISALLOWED_YOUTUBE_CHANNEL" in codes
    assert "BO_SHA256_MISSING" in codes
