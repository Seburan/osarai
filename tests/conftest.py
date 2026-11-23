"""Fixtures partagées pour la suite de tests Osarai (dépôt miniature valide et dépôt Git)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def create_webp_image(path: Path, width: int = 640, height: int = 480) -> str:
    """Génère une image `.webp` valide aux dimensions données et retourne son SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=(235, 245, 255))
    img.save(path, format="WEBP", quality=80)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    """Construit un dépôt miniature Osarai complet et valide dans `tmp_path`."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    # Copier le `sources.yaml` canonique de la racine du projet
    shutil.copy2(WORKSPACE_ROOT / "sources.yaml", repo / "sources.yaml")

    # Manifeste BO et curriculum SVT Cycle 4
    bo_dir = repo / "curriculum" / "sources"
    bo_dir.mkdir(parents=True, exist_ok=True)
    dummy_bo_sha = "a" * 64
    (bo_dir / "bo_manifest.yaml").write_text(
        f"""schema_version: 1
subjects:
  - cycle: "cycle-4"
    subject: "svt"
    documents:
      - title: "Programme du Cycle 4 — SVT"
        url: "https://eduscol.education.gouv.fr/document/12345/download"
        doc_type: "programme"
        publication_date: 2020-07-30
        sha256: "{dummy_bo_sha}"
""",
        encoding="utf-8",
    )

    curr_dir = repo / "curriculum" / "cycle-4"
    curr_dir.mkdir(parents=True, exist_ok=True)
    (curr_dir / "svt.yaml").write_text(
        f"""schema_version: 1
cycle: "cycle-4"
subject: "svt"
subject_code: "svt"
subject_label: "Sciences de la Vie et de la Terre (SVT)"
bo_sources:
  - title: "Programme du Cycle 4 — SVT (BO n°31)"
    producer: "Ministère de l'Éducation nationale (Éduscol)"
    publication_date: 2020-07-30
    url: "https://eduscol.education.gouv.fr/document/12345/download"
    license_spdx: "Etalab-2.0"
    license_url: "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"
    sha256: "{dummy_bo_sha}"
themes:
  - theme_slug: "la-respiration"
    title: "La respiration et les échanges gazeux"
    macro_theme_bo: "Le corps humain et la santé"
    reperes_levels: ["5eme"]
    attendus_bo:
      - "Relier les besoins des cellules d'un organe et l'approvisionnement en dioxygène."
      - "Expliquer le rôle des alvéoles pulmonaires dans les échanges gazeux."
    scope_exclusions:
      - "Respiration cellulaire mitochondriale et synthèse d'ATP (Lycée)."
""",
        encoding="utf-8",
    )

    theme_dir = repo / "content" / "cycle-4" / "svt" / "la-respiration"
    assets_dir = theme_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_filename = "c4-svt-la-respiration--alveoles.webp"
    asset_sha = create_webp_image(assets_dir / asset_filename, width=640, height=480)

    (theme_dir / "meta.yaml").write_text(
        """schema_version: 1
cycle: "cycle-4"
subject: "svt"
subject_code: "svt"
theme_slug: "la-respiration"
title: "La respiration et les échanges gazeux"
reperes_levels: ["5eme"]
scope_exclusions:
  - "Respiration cellulaire mitochondriale et synthèse d'ATP (Lycée)."
qa_status: "hitl_verified"
key_concepts:
  - concept_id: "echanges-alveolaires"
    label: "Échanges gazeux dans les alvéoles pulmonaires"
    reperes_level: "5eme"
  - concept_id: "besoins-organes"
    label: "Besoins en dioxygène et rejet de dioxyde de carbone"
    reperes_level: "5eme"
sources_used:
  - title: "Respiration — Vikidia"
    url: "https://fr.vikidia.org/wiki/Respiration"
    source_domain: "fr.vikidia.org"
    authors_or_history_url: "https://fr.vikidia.org/w/index.php?title=Respiration&action=history"
    license_spdx: "CC-BY-SA-3.0"
    license_url: "https://creativecommons.org/licenses/by-sa/3.0/deed.fr"
    revision_or_date: "1987654"
last_card_seq: 20
last_quiz_seq: 10
retired_ids: []
""",
        encoding="utf-8",
    )

    (theme_dir / "assets.yaml").write_text(
        f"""schema_version: 1
assets:
  - asset_id: "alveoles"
    filename: "{asset_filename}"
    width: 640
    height: 480
    sha256: "{asset_sha}"
    commons_title: "File:Alveoli_diagram_fr.svg"
    source_url: "https://commons.wikimedia.org/wiki/File:Alveoli_diagram_fr.svg"
    license_spdx: "CC-BY-SA-4.0"
    license_url: "https://creativecommons.org/licenses/by-sa/4.0/"
    author: "Wikimedia Contributor"
    title: "Schéma d'une alvéole pulmonaire"
    modifications_note: "Redimensionné à 1280 px et converti en WebP sans modification éditoriale"
    hitl_verified: true
""",
        encoding="utf-8",
    )

    (theme_dir / "summary.md").write_text(
        f"""## L'essentiel à retenir

Les organes prélèvent en permanence du dioxygène \\(\\text{{O}}_2\\) dans le sang et y rejettent
du dioxyde de carbone \\(\\text{{CO}}_2\\).

## Définitions clés

- **Alvéole pulmonaire** : petit sac à paroi très fine situé à l'extrémité des bronchioles.

## Schémas et repères

![Schéma des échanges gazeux dans une alvéole pulmonaire](assets/{asset_filename})

\\[
\\text{{Volume courant}} \\approx \\frac{{1}}{{2}}\\text{{ L}}
\\]

## Pièges fréquents au contrôle

Ne pas confondre la ventilation pulmonaire (mouvements d'air) et les échanges gazeux sang-organes.
""",
        encoding="utf-8",
    )

    cards_lines = ["schema_version: 1", "cards:"]
    # Carte 1 : basic avec occlusion
    cards_lines.append(
        """  - id: "c4-svt-la-respiration-c0001"
    concept_id: "echanges-alveolaires"
    reperes_level: "5eme"
    priority: "essentiel"
    type: "basic"
    front: "Quel gaz passe de l'air alvéolaire vers le sang au niveau de la zone `?` ?"
    back: "Le dioxygène \\\\(\\\\text{O}_2\\\\)"
    explanation: "La paroi fine et richement vascularisée favorise ce passage."
    asset_id: "alveoles"
    asset_role: "front_occluded"
    occlusions:
      - id: "occ-1"
        x: 15.0
        y: 20.0
        w: 25.0
        h: 12.0
        role: "target"
        badge: "?"
      - id: "occ-2"
        x: 55.0
        y: 60.0
        w: 20.0
        h: 10.0
        role: "mask"
        badge: "A" """
    )
    # Carte 2 : cloze à 2 indices avec formule mathématique
    cloze_front = (
        "Un muscle en activité consomme {{c1::du dioxygène::gaz}} "
        "et rejette {{c2::\\\\(\\\\text{CO}_2\\\\) ::formule}}."
    )
    cards_lines.append(
        f"""  - id: "c4-svt-la-respiration-c0002"
    concept_id: "besoins-organes"
    reperes_level: "5eme"
    priority: "essentiel"
    type: "cloze"
    front: "{cloze_front}"
    back: "" """
    )
    for idx in range(3, 21):
        concept = "echanges-alveolaires" if idx % 2 == 0 else "besoins-organes"
        cards_lines.append(
            f"""  - id: "c4-svt-la-respiration-c{idx:04d}"
    concept_id: "{concept}"
    reperes_level: "5eme"
    priority: "essentiel"
    type: "basic"
    front: "Question de révision numéro {idx} sur {concept} ?"
    back: "Réponse concise numéro {idx}." """
        )
    (theme_dir / "flashcards.yaml").write_text("\n".join(cards_lines) + "\n", encoding="utf-8")

    quiz_lines = ["schema_version: 1", "questions:"]
    for q_idx in range(1, 11):
        concept = "echanges-alveolaires" if q_idx <= 5 else "besoins-organes"
        quiz_lines.append(
            f"""  - id: "c4-svt-la-respiration-q{q_idx:04d}"
    concept_id: "{concept}"
    reperes_level: "5eme"
    difficulty: "facile"
    question: "Question QCM numéro {q_idx} concernant {concept} ?"
    choices:
      - "Proposition exacte {q_idx}"
      - "Distracteur A {q_idx}"
      - "Distracteur B {q_idx}"
      - "Distracteur C {q_idx}"
    answer_index: 0
    explanation: "Explication pédagogique de la question {q_idx}." """
        )
    (theme_dir / "quiz.yaml").write_text("\n".join(quiz_lines) + "\n", encoding="utf-8")

    (theme_dir / "resources.yaml").write_text(
        """schema_version: 1
resources:
  - title: "La respiration — Lumni Collège"
    url: "https://www.lumni.fr/video/la-respiration-humaine"
    source_domain: "lumni.fr"
    type: "video"
    last_verified_at: 2026-11-15
  - title: "Article Vikidia — Appareil respiratoire"
    url: "https://fr.vikidia.org/wiki/Appareil_respiratoire"
    source_domain: "fr.vikidia.org"
    type: "article"
    last_verified_at: 2026-11-15
  - title: "Vidéo Lumni sur YouTube — Les échanges gazeux"
    url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    source_domain: "youtube.com"
    type: "video"
    channel_url: "https://www.youtube.com/@Lumni"
    last_verified_at: 2026-11-15
""",
        encoding="utf-8",
    )

    return repo


def build_tabular_pdf_bytes() -> bytes:
    """Construit en mémoire un PDF 1.4 minimal contenant un titre et un tableau 2x2."""
    stream = (
        "BT /F1 14 Tf 60 780 Td (Programme officiel SVT Cycle 4) Tj ET\n"
        "1 w\n"
        "60 720 m 460 720 l S\n"
        "60 680 m 460 680 l S\n"
        "60 640 m 460 640 l S\n"
        "60 640 m 60 720 l S\n"
        "260 640 m 260 720 l S\n"
        "460 640 m 460 720 l S\n"
        "BT /F1 11 Tf 70 695 Td (5e) Tj ET\n"
        "BT /F1 11 Tf 270 695 Td (4e) Tj ET\n"
        "BT /F1 11 Tf 70 655 Td (Respiration) Tj ET\n"
        "BT /F1 11 Tf 270 655 Td (Reproduction) Tj ET\n"
    ).encode("latin-1")

    page_obj = (
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
    )
    font_obj = (
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >> endobj\n"
    )
    content_obj = (
        f"5 0 obj << /Length {len(stream)} >>\nstream\n".encode("ascii")
        + stream
        + b"endstream\nendobj\n"
    )
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        page_obj,
        font_obj,
        content_obj,
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    trailer = f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    out.extend(trailer.encode("ascii"))
    return bytes(out)


@pytest.fixture()
def sample_tabular_pdf(tmp_path: Path) -> Path:
    """Écrit le PDF tabulaire minimal dans `tmp_path` et retourne son chemin."""
    pdf_path = tmp_path / "bo_svt_cycle4.pdf"
    pdf_path.write_bytes(build_tabular_pdf_bytes())
    return pdf_path


@pytest.fixture()
def git_sample_repo(sample_repo: Path) -> Path:
    """Initialise un dépôt Git dans `sample_repo` avec `user.name`/`email` et `origin/main`."""

    def _git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(sample_repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    _git("init", "-b", "main")
    _git("config", "user.name", "Osarai CI Test")
    _git("config", "user.email", "ci-test@osarai.example")
    _git("add", ".")
    _git("commit", "-m", "Initial baseline commit")
    _git("update-ref", "refs/remotes/origin/main", "HEAD")
    return sample_repo
