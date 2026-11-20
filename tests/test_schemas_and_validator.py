"""Tests unitaires et d'intégration du Jalon 1 (`yaml_io`, `schemas`, `id_manager`, `validator`)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest
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
    """Un badge `'1'` est autorisé quand la réponse vaut `'12 organes'`, mais la réponse dans badge échoue."""
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
    """Si `c0030` est dans `retired_ids` avec `last_card_seq: 30`, la nouvelle carte reçoit `c0031`."""
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    dump_yaml_roundtrip(
        theme_dir / "meta.yaml",
        lambda doc: (
            doc.__setitem__("last_card_seq", 30),
            doc.__setitem__("retired_ids", ["c4-svt-la-respiration-c0030"]),
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

    dump_yaml_roundtrip(theme_dir / "flashcards.yaml", _append_unnumbered)

    # Avant `assign-ids`, `validate` signale l'ID exact attendu (`c0031`) et `last_card_seq: 31`
    pre_report = validate_target(sample_repo)
    assert not pre_report.ok
    missing_err = next(e for e in pre_report.errors if e.code == "MISSING_CARD_ID")
    assert missing_err.expected_id == "c4-svt-la-respiration-c0031"
    assert missing_err.expected_seq_value == 31
    assert missing_err.line is not None

    # Exécuter `assign-ids` puis revalider
    res = assign_missing_ids(theme_dir)
    assert res.assigned_card_ids == ["c4-svt-la-respiration-c0031"]
    assert res.last_card_seq == 31
    assert validate_target(sample_repo).ok


def test_allow_empty_resources_flag(sample_repo: Path) -> None:
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    (theme_dir / "resources.yaml").write_text("schema_version: 1\nresources: []\n", encoding="utf-8")

    assert not validate_target(sample_repo, allow_empty_resources=False).ok
    assert validate_target(sample_repo, allow_empty_resources=True).ok


def test_asset_size_warning_vs_ceiling_and_summary_checks(sample_repo: Path) -> None:
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    asset_path = theme_dir / "assets" / "c4-svt-la-respiration--alveoles.webp"

    # 1) Image de ~200 Ko -> avertissement non bloquant (`ok == True`)
    base_bytes = asset_path.read_bytes()
    # Créer un fichier PNG/WebP ou binaire simulé ? Utilisons une image PNG bruitée renommée ou
    # vérifions la taille en générant un bruit aléatoire RGB compressé en WebP lossless :
    noisy = Image.effect_noise((640, 480), 100.0).convert("RGB")
    noisy.save(asset_path, format="WEBP", lossless=True)
    if asset_path.stat().st_size <= 150 * 1024:
        # Agrandir avec une image bruitée plus large tout en synchronisant width/height/sha256
        noisy_big = Image.effect_noise((900, 700), 120.0).convert("RGB")
        noisy_big.save(asset_path, format="WEBP", lossless=True)
        w, h = 900, 700
    else:
        w, h = 640, 480

    import hashlib

    sha = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    assert 150 * 1024 < asset_path.stat().st_size < 300 * 1024 or w == 900

    # Si le bruit dépasse 300 Ko, tester d'abord le plafond > 300 Ko puis réduire pour 150..300 Ko
    if asset_path.stat().st_size > 300 * 1024:
        dump_yaml_roundtrip(
            theme_dir / "assets.yaml",
            lambda d: (
                d["assets"][0].__setitem__("width", w),
                d["assets"][0].__setitem__("height", h),
                d["assets"][0].__setitem__("sha256", sha),
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

    # Restaurer l'image initiale et vérifier le rejet d'une URL distante et d'un `# H1` dans summary.md
    asset_path.write_bytes(base_bytes)
    orig_sha = hashlib.sha256(base_bytes).hexdigest()
    dump_yaml_roundtrip(
        theme_dir / "assets.yaml",
        lambda d: (
            d["assets"][0].__setitem__("width", 640),
            d["assets"][0].__setitem__("height", 480),
            d["assets"][0].__setitem__("sha256", orig_sha),
        ),
    )
    (theme_dir / "summary.md").write_text(
        "# Titre H1 interdit\n\n## L'essentiel à retenir\n![ext](https://example.org/x.png)\n",
        encoding="utf-8",
    )
    bad_sum_report = validate_target(sample_repo)
    codes = {e.code for e in bad_sum_report.errors}
    assert "SUMMARY_H1_FORBIDDEN" in codes
    assert "SUMMARY_REMOTE_OR_INVALID_IMAGE" in codes
    assert "SUMMARY_MISSING_SECTION" in codes


def test_git_immutability_merge_base_checks(git_sample_repo: Path) -> None:
    """Vérifie `--against-ref origin/main` via `merge-base` : retrait sans `retired_ids`, type flip, suppression."""
    theme_dir = git_sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"

    # Avancer `origin/main` d'un commit indépendant (ex. README) pour exercer `git merge-base`
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

    # 1) Retirer `c0020` sans l'inscrire dans `retired_ids` et muter `c0002` de `cloze` -> `basic`
    def _mutate_cards(doc: dict) -> None:
        doc["cards"].pop()  # retire c0020 (il reste 19 cartes -> ajoutons c0021 valide)
        doc["cards"].append(
            {
                "id": "c4-svt-la-respiration-c0021",
                "concept_id": "besoins-organes",
                "reperes_level": "5eme",
                "priority": "essentiel",
                "type": "basic",
                "front": "Remplacement ?",
                "back": "Oui.",
            }
        )
        doc["cards"][1]["type"] = "basic"
        doc["cards"][1]["front"] = "Ancienne carte cloze convertie en basic ?"
        doc["cards"][1]["back"] = "Interdit sur le même ID."

    dump_yaml_roundtrip(theme_dir / "flashcards.yaml", _mutate_cards)
    dump_yaml_roundtrip(theme_dir / "meta.yaml", lambda d: d.__setitem__("last_card_seq", 21))

    rep = validate_target(git_sample_repo, against_ref="origin/main")
    err_codes = {e.code for e in rep.errors}
    assert "ID_DELETED_WITHOUT_RETIRING" in err_codes
    assert "CARD_TYPE_CHANGED" in err_codes

    # 2) Supprimer tout le dossier du thème -> `THEME_DELETED`
    shutil.rmtree(theme_dir)
    del_rep = validate_target(git_sample_repo, against_ref="origin/main")
    assert any(e.code == "THEME_DELETED" for e in del_rep.errors)


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
    md_file.write_text(
        f"Bonjour,\nVoici le signalement :\n\n```osarai-feedback-v1\n{json.dumps(payload_obj, indent=2)}\n```\n",
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
