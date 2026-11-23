"""Validateur hors-ligne déterministe du dépôt Osarai et des blocs `osarai-feedback-v1`."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from osarai import ExitCode, OsaraiError
from osarai.id_manager import ValidationIssue, check_immutable_ids_against_git
from osarai.schemas import (
    CARD_ID_RE,
    FENCED_CODE_RE,
    QUIZ_ID_RE,
    AssetsFile,
    BoManifest,
    CurriculumFile,
    CurriculumTheme,
    FeedbackPayload,
    FlashcardsFile,
    QuizFile,
    ResourcesFile,
    SourcesPolicy,
    ThemeMeta,
    normalize_hostname,
    normalize_search_text,
    parse_cloze_tokens,
    validate_latex_fragment,
    validate_no_raw_html,
)
from osarai.yaml_io import get_yaml_line, load_yaml_with_lines

ASSET_WARN_BYTES = 150 * 1024
ASSET_MAX_BYTES = 300 * 1024
MAX_FEEDBACK_BYTES = 256 * 1024

REQUIRED_SUMMARY_SECTIONS: tuple[str, ...] = (
    "## L'essentiel à retenir",
    "## Définitions clés",
    "## Schémas et repères",
    "## Pièges fréquents au contrôle",
)

MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FEEDBACK_BLOCK_RE = re.compile(r"```osarai-feedback-v1[ \t]*\r?\n([\s\S]*?)\r?\n```")


@dataclass
class ValidationReport:
    """Rapport structuré d'exécution de `validate_target`."""

    issues: list[ValidationIssue] = field(default_factory=list)
    checked_themes: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [iss for iss in self.issues if iss.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [iss for iss in self.issues if iss.severity == "warning"]

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked_themes": self.checked_themes,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [iss.to_dict() for iss in self.issues],
        }


def _rel_str(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_loc_line(raw_node: Any, loc: tuple[int | str, ...]) -> int | None:
    curr = raw_node
    line = get_yaml_line(curr)
    for step in loc:
        step_line = get_yaml_line(curr, step)
        if step_line is not None:
            line = step_line
        if isinstance(curr, dict) and isinstance(step, str) and step in curr:
            curr = curr[step]
        elif isinstance(curr, list) and isinstance(step, int) and 0 <= step < len(curr):
            curr = curr[step]
        else:
            break
    return line


def _pydantic_issues(
    exc: ValidationError,
    raw_node: Any,
    rel_file: str,
    code: str = "SCHEMA_VALIDATION_ERROR",
) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []
    for err in exc.errors():
        loc = tuple(err.get("loc", ()))
        loc_str = ".".join(str(p) for p in loc) or "<racine>"
        line = _resolve_loc_line(raw_node, loc)
        out.append(
            ValidationIssue(
                severity="error",
                code=code,
                file=rel_file,
                line=line,
                message=f"[{loc_str}] {err.get('msg', 'Valeur invalide')}",
            )
        )
    return out


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_summary_markdown(
    summary_path: Path,
    rel_file: str,
    meta: ThemeMeta,
    declared_asset_filenames: set[str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not summary_path.is_file():
        issues.append(
            ValidationIssue(
                severity="error",
                code="MISSING_FILE",
                file=rel_file,
                line=None,
                message="Fichier `summary.md` manquant.",
            )
        )
        return issues

    text = summary_path.read_text(encoding="utf-8")
    if not text.strip():
        issues.append(
            ValidationIssue(
                severity="error",
                code="EMPTY_SUMMARY",
                file=rel_file,
                line=1,
                message="Le fichier `summary.md` ne peut pas être vide.",
            )
        )
        return issues

    stripped_fences = FENCED_CODE_RE.sub("", text)
    for idx, line_text in enumerate(stripped_fences.splitlines(), start=1):
        if line_text.startswith("# "):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SUMMARY_H1_FORBIDDEN",
                    file=rel_file,
                    line=idx,
                    message=(
                        "Titre `# ` de niveau 1 interdit dans `summary.md` "
                        "(démarrez directement par `## L'essentiel à retenir`)."
                    ),
                )
            )
            break

    for section_heading in REQUIRED_SUMMARY_SECTIONS:
        if section_heading not in stripped_fences:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SUMMARY_MISSING_SECTION",
                    file=rel_file,
                    line=None,
                    message=f"Section obligatoire absente de `summary.md` : `{section_heading}`.",
                )
            )

    if len(meta.reperes_levels) > 1 and "### Approfondissement" not in stripped_fences:
        issues.append(
            ValidationIssue(
                severity="error",
                code="SUMMARY_MISSING_APPROFONDISSEMENT",
                file=rel_file,
                line=None,
                message=(
                    "Thème multi-niveaux : ajoutez une sous-section "
                    "`### Approfondissement ...` dans `summary.md`."
                ),
            )
        )

    try:
        validate_no_raw_html(text, allow_fenced=True)
    except ValueError as exc:
        issues.append(
            ValidationIssue(
                severity="error",
                code="SUMMARY_RAW_HTML",
                file=rel_file,
                line=None,
                message=str(exc),
            )
        )

    try:
        validate_latex_fragment(text, allow_block=True, allow_fenced=True)
    except ValueError as exc:
        issues.append(
            ValidationIssue(
                severity="error",
                code="SUMMARY_INVALID_LATEX",
                file=rel_file,
                line=None,
                message=str(exc),
            )
        )

    for match in MD_IMAGE_RE.finditer(stripped_fences):
        alt_text, target = match.group(1).strip(), match.group(2).strip()
        if not alt_text:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SUMMARY_EMPTY_ALT",
                    file=rel_file,
                    line=None,
                    message=f"Texte alternatif obligatoire sur l'illustration `{target}`.",
                )
            )
        if (
            target.startswith(("http://", "https://", "//", "/"))
            or ".." in target.split("/")
            or not target.startswith("assets/")
        ):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SUMMARY_REMOTE_OR_INVALID_IMAGE",
                    file=rel_file,
                    line=None,
                    message=(
                        f"Illustration `{target}` invalide dans `summary.md` : "
                        "seuls les chemins locaux `assets/<filename>` sont autorisés."
                    ),
                )
            )
            continue
        fname = target[len("assets/") :]
        if "/" in fname or fname not in declared_asset_filenames:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SUMMARY_UNDECLARED_ASSET",
                    file=rel_file,
                    line=None,
                    message=(
                        f"L'illustration `{target}` référencée dans `summary.md` "
                        "n'est pas déclarée dans `assets.yaml`."
                    ),
                )
            )

    return issues


def _validate_single_theme(
    repo_root: Path,
    theme_dir: Path,
    sources: SourcesPolicy,
    curriculum_theme: CurriculumTheme | None,
    allow_empty_resources: bool,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    meta_path = theme_dir / "meta.yaml"
    assets_path = theme_dir / "assets.yaml"
    summary_path = theme_dir / "summary.md"
    cards_path = theme_dir / "flashcards.yaml"
    quiz_path = theme_dir / "quiz.yaml"
    resources_path = theme_dir / "resources.yaml"

    for req_path in (meta_path, assets_path, summary_path, cards_path, quiz_path, resources_path):
        if not req_path.is_file():
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="MISSING_FILE",
                    file=_rel_str(req_path, repo_root),
                    line=None,
                    message=f"Fichier obligatoire manquant : `{req_path.name}`.",
                )
            )
    if not meta_path.is_file():
        return issues

    raw_meta = load_yaml_with_lines(meta_path)
    rel_meta = _rel_str(meta_path, repo_root)
    try:
        meta = ThemeMeta.model_validate(raw_meta)
    except ValidationError as exc:
        issues.extend(_pydantic_issues(exc, raw_meta, rel_meta))
        return issues

    # Vérifier la cohérence du chemin `content/<cycle>/<subject>/<theme_slug>`
    rel_parts = _rel_str(theme_dir, repo_root).split("/")
    if len(rel_parts) == 4 and rel_parts[0] == "content":
        _, dir_cycle, dir_subject, dir_slug = rel_parts
        if (meta.cycle, meta.subject, meta.theme_slug) != (dir_cycle, dir_subject, dir_slug):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="META_PATH_MISMATCH",
                    file=rel_meta,
                    line=1,
                    message=(
                        f"`meta.yaml` ({meta.cycle}/{meta.subject}/{meta.theme_slug}) "
                        f"ne correspond pas au dossier `{dir_cycle}/{dir_subject}/{dir_slug}`."
                    ),
                )
            )

    if curriculum_theme is not None:
        if meta.title != curriculum_theme.title:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="CURRICULUM_TITLE_MISMATCH",
                    file=rel_meta,
                    line=get_yaml_line(raw_meta, "title"),
                    message=(
                        f"`meta.title` ({meta.title!r}) diffère du titre officiel "
                        f"dans `curriculum/` ({curriculum_theme.title!r})."
                    ),
                )
            )
        if set(meta.reperes_levels) != set(curriculum_theme.reperes_levels):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="CURRICULUM_LEVELS_MISMATCH",
                    file=rel_meta,
                    line=get_yaml_line(raw_meta, "reperes_levels"),
                    message=(
                        f"`meta.reperes_levels` ({meta.reperes_levels}) diffère de "
                        f"`curriculum/` ({curriculum_theme.reperes_levels})."
                    ),
                )
            )

    # Contrôle hors-ligne de `meta.yaml -> sources_used` contre `sources.yaml`
    allowed_licenses = set(sources.allowed_licenses)
    for idx, src_credit in enumerate(meta.sources_used):
        src_line = _resolve_loc_line(raw_meta, ("sources_used", idx))
        if src_credit.license_spdx not in allowed_licenses:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DISALLOWED_LICENSE",
                    file=rel_meta,
                    line=src_line,
                    message=(
                        f"Licence `{src_credit.license_spdx}` absente de "
                        "`sources.yaml -> allowed_licenses`."
                    ),
                )
            )
        rule = sources.find_domain_rule(src_credit.url)
        url_host = normalize_hostname(src_credit.url)
        if not (
            url_host == src_credit.source_domain
            or url_host.endswith(f".{src_credit.source_domain}")
        ):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SOURCE_DOMAIN_MISMATCH",
                    file=rel_meta,
                    line=src_line,
                    message=(
                        f"`source_domain` ({src_credit.source_domain!r}) ne correspond pas "
                        f"à l'URL `{src_credit.url}`."
                    ),
                )
            )
        if rule is None or not rule.allow_grounding:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DISALLOWED_GROUNDING_DOMAIN",
                    file=rel_meta,
                    line=src_line,
                    message=(
                        f"Le domaine `{url_host}` n'est pas autorisé comme source d'appui "
                        "(`allow_grounding: true`) dans `sources.yaml`."
                    ),
                )
            )

    # Validation de `assets.yaml` et des fichiers binaires `assets/`
    declared_assets: dict[str, str] = {}
    if assets_path.is_file():
        raw_assets = load_yaml_with_lines(assets_path)
        rel_assets = _rel_str(assets_path, repo_root)
        try:
            assets_file = AssetsFile.model_validate(raw_assets)
        except ValidationError as exc:
            issues.extend(_pydantic_issues(exc, raw_assets, rel_assets))
            assets_file = None

        if assets_file is not None:
            expected_asset_prefix = f"{meta.id_prefix}--"
            for idx, asset in enumerate(assets_file.assets):
                declared_assets[asset.asset_id] = asset.filename
                asset_line = _resolve_loc_line(raw_assets, ("assets", idx))
                if not asset.filename.startswith(expected_asset_prefix):
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="ASSET_PREFIX_MISMATCH",
                            file=rel_assets,
                            line=asset_line,
                            message=(
                                f"`filename` ({asset.filename!r}) doit commencer par "
                                f"`{expected_asset_prefix}{asset.asset_id}.`."
                            ),
                        )
                    )
                if asset.license_spdx not in allowed_licenses:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="DISALLOWED_LICENSE",
                            file=rel_assets,
                            line=asset_line,
                            message=(
                                f"Licence média `{asset.license_spdx}` non autorisée "
                                "par `sources.yaml`."
                            ),
                        )
                    )
                media_rule = sources.find_domain_rule(asset.source_url)
                if media_rule is None or not media_rule.allow_embed_media:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="DISALLOWED_MEDIA_DOMAIN",
                            file=rel_assets,
                            line=asset_line,
                            message=(
                                f"Domaine média `{normalize_hostname(asset.source_url)}` "
                                "non marqué `allow_embed_media: true` dans `sources.yaml`."
                            ),
                        )
                    )
                if not asset.hitl_verified:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="ASSET_NOT_HITL_VERIFIED",
                            file=rel_assets,
                            line=asset_line,
                            message=(
                                f"L'illustration `{asset.asset_id}` a `hitl_verified: false` ; "
                                "vérifiez `preview-occlusions` puis passez `hitl_verified: true`."
                            ),
                        )
                    )

                img_path = theme_dir / "assets" / asset.filename
                if not img_path.is_file():
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="MISSING_ASSET_FILE",
                            file=rel_assets,
                            line=asset_line,
                            message=f"Fichier image introuvable : `assets/{asset.filename}`.",
                        )
                    )
                    continue

                size_bytes = img_path.stat().st_size
                if size_bytes > ASSET_MAX_BYTES:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="ASSET_TOO_LARGE",
                            file=rel_assets,
                            line=asset_line,
                            message=(
                                f"`assets/{asset.filename}` dépasse le plafond de 300 Ko "
                                f"({size_bytes / 1024:.1f} Ko)."
                            ),
                        )
                    )
                elif size_bytes > ASSET_WARN_BYTES:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="ASSET_SIZE_WARNING",
                            file=rel_assets,
                            line=asset_line,
                            message=(
                                f"`assets/{asset.filename}` dépasse la cible de 150 Ko "
                                f"({size_bytes / 1024:.1f} Ko <= 300 Ko)."
                            ),
                        )
                    )

                actual_sha = _sha256_file(img_path)
                if actual_sha != asset.sha256:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="ASSET_SHA256_MISMATCH",
                            file=rel_assets,
                            line=asset_line,
                            message=(
                                f"`sha256` discordant pour `assets/{asset.filename}` "
                                f"(attendu {actual_sha}, déclaré {asset.sha256})."
                            ),
                        )
                    )

                try:
                    with Image.open(img_path) as img:
                        real_w, real_h = img.size
                except (UnidentifiedImageError, OSError) as exc:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="INVALID_IMAGE_BINARY",
                            file=rel_assets,
                            line=asset_line,
                            message=f"Image illisible `assets/{asset.filename}` : {exc}",
                        )
                    )
                else:
                    if (real_w, real_h) != (asset.width, asset.height):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="ASSET_DIMENSIONS_MISMATCH",
                                file=rel_assets,
                                line=asset_line,
                                message=(
                                    f"Dimensions réelles ({real_w}x{real_h}) différentes de "
                                    f"`assets.yaml` ({asset.width}x{asset.height}) pour "
                                    f"`{asset.filename}`."
                                ),
                            )
                        )

            assets_dir = theme_dir / "assets"
            if assets_dir.is_dir():
                declared_filenames = set(declared_assets.values())
                for child in sorted(assets_dir.iterdir()):
                    if child.name.startswith("."):
                        continue
                    if child.name not in declared_filenames:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="ORPHAN_ASSET_FILE",
                                file=_rel_str(child, repo_root),
                                line=None,
                                message=(
                                    f"Fichier média orphelin `{child.name}` non déclaré "
                                    "dans `assets.yaml`."
                                ),
                            )
                        )

    # Validation de `summary.md`
    issues.extend(
        _validate_summary_markdown(
            summary_path,
            _rel_str(summary_path, repo_root),
            meta,
            set(declared_assets.values()),
        )
    )

    concept_levels = {c.concept_id: c.reperes_level for c in meta.key_concepts}
    covered_concepts: set[str] = set()
    retired_set = set(meta.retired_ids)
    prefix = meta.id_prefix

    # Validation de `flashcards.yaml`
    if cards_path.is_file():
        raw_cards = load_yaml_with_lines(cards_path)
        rel_cards = _rel_str(cards_path, repo_root)
        try:
            cards_file = FlashcardsFile.model_validate(raw_cards)
        except ValidationError as exc:
            issues.extend(_pydantic_issues(exc, raw_cards, rel_cards))
            cards_file = None

        if cards_file is not None:
            existing_card_seqs = [
                int(m.group(1))
                for c in cards_file.cards
                if c.id and c.id.startswith(f"{prefix}-c") and (m := CARD_ID_RE.match(c.id))
            ]
            running_seq = max([meta.last_card_seq, *existing_card_seqs])
            missing_assignments: list[tuple[int, str]] = []
            for idx, card in enumerate(cards_file.cards):
                if card.id is None:
                    running_seq += 1
                    while f"{prefix}-c{running_seq:04d}" in retired_set:
                        running_seq += 1
                    missing_assignments.append((idx, f"{prefix}-c{running_seq:04d}"))
            final_expected_card_seq = running_seq
            missing_map = dict(missing_assignments)

            seen_card_ids: set[str] = set()
            for idx, card in enumerate(cards_file.cards):
                card_line = _resolve_loc_line(raw_cards, ("cards", idx))
                if card.concept_id not in concept_levels:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="UNKNOWN_CONCEPT_ID",
                            file=rel_cards,
                            line=card_line,
                            message=(
                                f"`concept_id` inconnu ({card.concept_id!r}) ; "
                                "déclarez-le dans `meta.yaml -> key_concepts`."
                            ),
                        )
                    )
                else:
                    covered_concepts.add(card.concept_id)
                    expected_lvl = concept_levels[card.concept_id]
                    if card.reperes_level != expected_lvl:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="CONCEPT_LEVEL_MISMATCH",
                                file=rel_cards,
                                line=card_line,
                                message=(
                                    f"`reperes_level` ({card.reperes_level!r}) diffère du niveau "
                                    f"du concept `{card.concept_id}` ({expected_lvl!r})."
                                ),
                            )
                        )

                if card.asset_id is not None and card.asset_id not in declared_assets:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="UNKNOWN_ASSET_ID",
                            file=rel_cards,
                            line=card_line,
                            message=(f"`asset_id` ({card.asset_id!r}) absent de `assets.yaml`."),
                        )
                    )

                if card.id is None:
                    exp_id = missing_map[idx]
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="MISSING_CARD_ID",
                            file=rel_cards,
                            line=card_line,
                            message=(
                                f'Champ `id` manquant : renseignez `id: "{exp_id}"` et mettez '
                                f"à jour `last_card_seq: {final_expected_card_seq}` dans "
                                f"`meta.yaml` (ou exécutez `uv run osarai assign-ids --theme "
                                f"{_rel_str(theme_dir, repo_root)}`)."
                            ),
                            expected_id=exp_id,
                            expected_seq_field="last_card_seq",
                            expected_seq_value=final_expected_card_seq,
                        )
                    )
                else:
                    if not card.id.startswith(f"{prefix}-c"):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="CARD_ID_PREFIX_MISMATCH",
                                file=rel_cards,
                                line=card_line,
                                message=(f"`id` ({card.id!r}) ne commence pas par `{prefix}-c`."),
                            )
                        )
                    else:
                        seq = int(CARD_ID_RE.match(card.id).group(1))  # type: ignore[union-attr]
                        if seq < 1 or seq > meta.last_card_seq:
                            issues.append(
                                ValidationIssue(
                                    severity="error",
                                    code="CARD_SEQ_OUT_OF_RANGE",
                                    file=rel_cards,
                                    line=card_line,
                                    message=(
                                        f"`{card.id}` dépasse `meta.last_card_seq` "
                                        f"({meta.last_card_seq}) ; réglez `last_card_seq: "
                                        f"{max(existing_card_seqs)}` dans `meta.yaml`."
                                    ),
                                    expected_seq_field="last_card_seq",
                                    expected_seq_value=max(existing_card_seqs),
                                )
                            )
                    if card.id in seen_card_ids:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="DUPLICATE_CARD_ID",
                                file=rel_cards,
                                line=card_line,
                                message=f"Identifiant de carte dupliqué : `{card.id}`.",
                            )
                        )
                    seen_card_ids.add(card.id)
                    if card.id in retired_set:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="ACTIVE_ID_IN_RETIRED",
                                file=rel_cards,
                                line=card_line,
                                message=(
                                    f"Conflit `active_ids ∩ retired_ids` : `{card.id}` figure "
                                    "à la fois dans `flashcards.yaml` et `retired_ids`."
                                ),
                            )
                        )

                # Avertissements non bloquants (longueur > 250 et répétition Cloze dans `front`)
                if card.type == "basic" and len(card.back) > 250:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="ANSWER_LENGTH_WARNING",
                            file=rel_cards,
                            line=card_line,
                            message=(
                                f"Réponse `back` longue ({len(card.back)} > 250 car.) sur "
                                f"`{card.id or f'carte #{idx + 1}'}`."
                            ),
                        )
                    )
                elif card.type == "cloze":
                    tokens = parse_cloze_tokens(card.front)
                    for tok in tokens:
                        if len(tok.answer) > 250:
                            issues.append(
                                ValidationIssue(
                                    severity="warning",
                                    code="ANSWER_LENGTH_WARNING",
                                    file=rel_cards,
                                    line=card_line,
                                    message=(
                                        f"Segment `c{tok.index}` long ({len(tok.answer)} > 250 "
                                        f"car.) sur `{card.id or f'carte #{idx + 1}'}`."
                                    ),
                                )
                            )
                    by_index: dict[int, list[str]] = {}
                    for tok in tokens:
                        by_index.setdefault(tok.index, []).append(tok.answer)
                    for c_idx, answers in sorted(by_index.items()):
                        visible_chunks: list[str] = []
                        pos = 0
                        for tok in tokens:
                            visible_chunks.append(card.front[pos : tok.start])
                            if tok.index != c_idx:
                                visible_chunks.append(tok.answer)
                            pos = tok.end
                        visible_chunks.append(card.front[pos:])
                        visible_norm = normalize_search_text(" ".join(visible_chunks))
                        for ans in answers:
                            ans_norm = normalize_search_text(ans)
                            if len(ans_norm) >= 3 and re.search(
                                rf"\b{re.escape(ans_norm)}\b", visible_norm
                            ):
                                issues.append(
                                    ValidationIssue(
                                        severity="warning",
                                        code="CLOZE_SELF_DISCLOSURE_WARNING",
                                        file=rel_cards,
                                        line=card_line,
                                        message=(
                                            f"Le segment caché `{ans}` (`c{c_idx}`) réapparaît "
                                            "en clair dans le reste du recto (vérification HITL)."
                                        ),
                                    )
                                )
                                break

            for concept in meta.key_concepts:
                if concept.concept_id not in covered_concepts:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="UNCOVERED_CONCEPT",
                            file=rel_cards,
                            line=None,
                            message=(
                                f"Le concept clé `{concept.concept_id}` de `meta.yaml` n'est "
                                "couvert par aucune carte dans `flashcards.yaml`."
                            ),
                        )
                    )

    # Validation de `quiz.yaml`
    if quiz_path.is_file():
        raw_quiz = load_yaml_with_lines(quiz_path)
        rel_quiz = _rel_str(quiz_path, repo_root)
        try:
            quiz_file = QuizFile.model_validate(raw_quiz)
        except ValidationError as exc:
            issues.extend(_pydantic_issues(exc, raw_quiz, rel_quiz))
            quiz_file = None

        if quiz_file is not None:
            existing_quiz_seqs = [
                int(m.group(1))
                for q in quiz_file.questions
                if q.id and q.id.startswith(f"{prefix}-q") and (m := QUIZ_ID_RE.match(q.id))
            ]
            running_q_seq = max([meta.last_quiz_seq, *existing_quiz_seqs])
            missing_q_assignments: list[tuple[int, str]] = []
            for idx, question in enumerate(quiz_file.questions):
                if question.id is None:
                    running_q_seq += 1
                    while f"{prefix}-q{running_q_seq:04d}" in retired_set:
                        running_q_seq += 1
                    missing_q_assignments.append((idx, f"{prefix}-q{running_q_seq:04d}"))
            final_expected_quiz_seq = running_q_seq
            missing_q_map = dict(missing_q_assignments)

            seen_quiz_ids: set[str] = set()
            for idx, question in enumerate(quiz_file.questions):
                q_line = _resolve_loc_line(raw_quiz, ("questions", idx))
                if question.concept_id not in concept_levels:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="UNKNOWN_CONCEPT_ID",
                            file=rel_quiz,
                            line=q_line,
                            message=(
                                f"`concept_id` inconnu ({question.concept_id!r}) ; "
                                "déclarez-le dans `meta.yaml -> key_concepts`."
                            ),
                        )
                    )
                else:
                    expected_lvl = concept_levels[question.concept_id]
                    if question.reperes_level != expected_lvl:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="CONCEPT_LEVEL_MISMATCH",
                                file=rel_quiz,
                                line=q_line,
                                message=(
                                    f"`reperes_level` ({question.reperes_level!r}) diffère du "
                                    f"niveau du concept `{question.concept_id}` ({expected_lvl!r})."
                                ),
                            )
                        )

                if question.asset_id is not None and question.asset_id not in declared_assets:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="UNKNOWN_ASSET_ID",
                            file=rel_quiz,
                            line=q_line,
                            message=(
                                f"`asset_id` ({question.asset_id!r}) absent de `assets.yaml`."
                            ),
                        )
                    )

                if question.id is None:
                    exp_qid = missing_q_map[idx]
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="MISSING_QUIZ_ID",
                            file=rel_quiz,
                            line=q_line,
                            message=(
                                f'Champ `id` manquant : renseignez `id: "{exp_qid}"` et mettez '
                                f"à jour `last_quiz_seq: {final_expected_quiz_seq}` dans "
                                f"`meta.yaml` (ou exécutez `uv run osarai assign-ids --theme "
                                f"{_rel_str(theme_dir, repo_root)}`)."
                            ),
                            expected_id=exp_qid,
                            expected_seq_field="last_quiz_seq",
                            expected_seq_value=final_expected_quiz_seq,
                        )
                    )
                else:
                    if not question.id.startswith(f"{prefix}-q"):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="QUIZ_ID_PREFIX_MISMATCH",
                                file=rel_quiz,
                                line=q_line,
                                message=(
                                    f"`id` ({question.id!r}) ne commence pas par `{prefix}-q`."
                                ),
                            )
                        )
                    else:
                        q_seq = int(QUIZ_ID_RE.match(question.id).group(1))  # type: ignore[union-attr]
                        if q_seq < 1 or q_seq > meta.last_quiz_seq:
                            issues.append(
                                ValidationIssue(
                                    severity="error",
                                    code="QUIZ_SEQ_OUT_OF_RANGE",
                                    file=rel_quiz,
                                    line=q_line,
                                    message=(
                                        f"`{question.id}` dépasse `meta.last_quiz_seq` "
                                        f"({meta.last_quiz_seq}) ; réglez `last_quiz_seq: "
                                        f"{max(existing_quiz_seqs)}` dans `meta.yaml`."
                                    ),
                                    expected_seq_field="last_quiz_seq",
                                    expected_seq_value=max(existing_quiz_seqs),
                                )
                            )
                    if question.id in seen_quiz_ids:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="DUPLICATE_QUIZ_ID",
                                file=rel_quiz,
                                line=q_line,
                                message=f"Identifiant de QCM dupliqué : `{question.id}`.",
                            )
                        )
                    seen_quiz_ids.add(question.id)
                    if question.id in retired_set:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="ACTIVE_ID_IN_RETIRED",
                                file=rel_quiz,
                                line=q_line,
                                message=(
                                    f"Conflit `active_ids ∩ retired_ids` : `{question.id}` figure "
                                    "à la fois dans `quiz.yaml` et `retired_ids`."
                                ),
                            )
                        )

    # Validation de `resources.yaml` contre `sources.yaml`
    if resources_path.is_file():
        raw_res = load_yaml_with_lines(resources_path)
        rel_res = _rel_str(resources_path, repo_root)
        try:
            res_file = ResourcesFile.model_validate(
                raw_res,
                context={"allow_empty_resources": allow_empty_resources},
            )
        except ValidationError as exc:
            issues.extend(_pydantic_issues(exc, raw_res, rel_res))
            res_file = None

        if res_file is not None:
            for idx, entry in enumerate(res_file.resources):
                r_line = _resolve_loc_line(raw_res, ("resources", idx))
                if not sources.is_allowed_resource_domain(entry.url):
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="DISALLOWED_RESOURCE_DOMAIN",
                            file=rel_res,
                            line=r_line,
                            message=(
                                f"Le domaine `{normalize_hostname(entry.url)}` n'est pas autorisé "
                                "dans `resources.yaml` selon `sources.yaml`."
                            ),
                        )
                    )
                if entry.channel_url and not sources.is_allowed_youtube_channel(entry.channel_url):
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="DISALLOWED_YOUTUBE_CHANNEL",
                            file=rel_res,
                            line=r_line,
                            message=(
                                f"Chaîne YouTube `{entry.channel_url}` absente de "
                                "`sources.yaml -> allowed_youtube_channel_urls`."
                            ),
                        )
                    )

    return issues


def validate_target(
    repo_root: Path,
    theme_dir: Path | None = None,
    against_ref: str | None = None,
    allow_empty_resources: bool = False,
) -> ValidationReport:
    """Valide hors-ligne `sources.yaml`, `curriculum/` et un thème ou l'ensemble de `content/`."""
    report = ValidationReport()

    sources_path = repo_root / "sources.yaml"
    if not sources_path.is_file():
        report.issues.append(
            ValidationIssue(
                severity="error",
                code="MISSING_SOURCES_POLICY",
                file="sources.yaml",
                line=None,
                message="Fichier `sources.yaml` introuvable à la racine du dépôt.",
            )
        )
        return report

    raw_sources = load_yaml_with_lines(sources_path)
    try:
        sources = SourcesPolicy.model_validate(raw_sources)
    except ValidationError as exc:
        report.issues.extend(_pydantic_issues(exc, raw_sources, "sources.yaml"))
        return report

    # Validation optionnelle de `curriculum/sources/bo_manifest.yaml`
    bo_manifest_path = repo_root / "curriculum" / "sources" / "bo_manifest.yaml"
    if bo_manifest_path.is_file():
        raw_manifest = load_yaml_with_lines(bo_manifest_path)
        rel_manifest = _rel_str(bo_manifest_path, repo_root)
        try:
            manifest = BoManifest.model_validate(raw_manifest)
        except ValidationError as exc:
            report.issues.extend(_pydantic_issues(exc, raw_manifest, rel_manifest))
        else:
            for s_idx, subj in enumerate(manifest.subjects):
                for d_idx, doc in enumerate(subj.documents):
                    doc_line = _resolve_loc_line(
                        raw_manifest, ("subjects", s_idx, "documents", d_idx)
                    )
                    if not doc.sha256:
                        report.issues.append(
                            ValidationIssue(
                                severity="error",
                                code="BO_SHA256_MISSING",
                                file=rel_manifest,
                                line=doc_line,
                                message=(
                                    f"`sha256` manquant pour `{doc.title}` ; exécutez "
                                    f"`uv run osarai sync-bo --cycle {subj.cycle} "
                                    f"--subject {subj.subject}`."
                                ),
                            )
                        )
                    rule = sources.find_domain_rule(doc.url)
                    if rule is None or rule.adapter != "eduscol_bo":
                        report.issues.append(
                            ValidationIssue(
                                severity="error",
                                code="DISALLOWED_BO_DOMAIN",
                                file=rel_manifest,
                                line=doc_line,
                                message=(
                                    f"L'URL BO `{doc.url}` ne relève pas d'un domaine "
                                    "`eduscol_bo` dans `sources.yaml`."
                                ),
                            )
                        )

    # Chargement et validation de `curriculum/<cycle>/<matiere>.yaml`
    curriculum_index: dict[tuple[str, str, str], CurriculumTheme] = {}
    curriculum_root = repo_root / "curriculum"
    if curriculum_root.is_dir():
        for curr_file_path in sorted(curriculum_root.glob("cycle-*/*.yaml")):
            raw_curr = load_yaml_with_lines(curr_file_path)
            rel_curr = _rel_str(curr_file_path, repo_root)
            try:
                curr = CurriculumFile.model_validate(raw_curr)
            except ValidationError as exc:
                report.issues.extend(_pydantic_issues(exc, raw_curr, rel_curr))
                continue

            expected_cycle = curr_file_path.parent.name
            expected_subject = curr_file_path.stem
            if (curr.cycle, curr.subject) != (expected_cycle, expected_subject):
                report.issues.append(
                    ValidationIssue(
                        severity="error",
                        code="CURRICULUM_PATH_MISMATCH",
                        file=rel_curr,
                        line=1,
                        message=(
                            f"`{rel_curr}` déclare `{curr.cycle}/{curr.subject}` au lieu de "
                            f"`{expected_cycle}/{expected_subject}`."
                        ),
                    )
                )
            for b_idx, bo_src in enumerate(curr.bo_sources):
                b_rule = sources.find_domain_rule(bo_src.url)
                if b_rule is None or b_rule.adapter != "eduscol_bo":
                    report.issues.append(
                        ValidationIssue(
                            severity="error",
                            code="DISALLOWED_BO_DOMAIN",
                            file=rel_curr,
                            line=_resolve_loc_line(raw_curr, ("bo_sources", b_idx)),
                            message=(
                                f"`bo_sources[{b_idx}].url` (`{bo_src.url}`) hors domaines "
                                "`eduscol_bo` de `sources.yaml`."
                            ),
                        )
                    )
            for th in curr.themes:
                curriculum_index[(curr.cycle, curr.subject, th.theme_slug)] = th

    # Découverte des dossiers de thèmes à valider
    theme_dirs: list[Path] = []
    if theme_dir is not None:
        resolved_theme = theme_dir if theme_dir.is_absolute() else (repo_root / theme_dir)
        if not resolved_theme.is_dir():
            report.issues.append(
                ValidationIssue(
                    severity="error",
                    code="THEME_DIR_NOT_FOUND",
                    file=_rel_str(resolved_theme, repo_root),
                    line=None,
                    message=f"Dossier de thème introuvable : `{resolved_theme}`.",
                )
            )
            return report
        theme_dirs.append(resolved_theme)
    else:
        content_root = repo_root / "content"
        if content_root.is_dir():
            for cycle_dir in sorted(content_root.iterdir()):
                if not cycle_dir.is_dir() or cycle_dir.name.startswith("."):
                    continue
                for subject_dir in sorted(cycle_dir.iterdir()):
                    if not subject_dir.is_dir() or subject_dir.name.startswith("."):
                        continue
                    for candidate_theme in sorted(subject_dir.iterdir()):
                        if candidate_theme.is_dir() and not candidate_theme.name.startswith("."):
                            theme_dirs.append(candidate_theme)

    for t_dir in theme_dirs:
        report.checked_themes += 1
        rel_parts = _rel_str(t_dir, repo_root).split("/")
        curr_theme: CurriculumTheme | None = None
        if len(rel_parts) == 4 and rel_parts[0] == "content":
            key = (rel_parts[1], rel_parts[2], rel_parts[3])
            curr_theme = curriculum_index.get(key)
            if curr_theme is None:
                report.issues.append(
                    ValidationIssue(
                        severity="error",
                        code="UNREGISTERED_THEME",
                        file=_rel_str(t_dir / "meta.yaml", repo_root),
                        line=None,
                        message=(
                            f"Le thème `{'/'.join(rel_parts[1:])}` n'est pas déclaré dans "
                            f"`curriculum/{rel_parts[1]}/{rel_parts[2]}.yaml`."
                        ),
                    )
                )
        report.issues.extend(
            _validate_single_theme(
                repo_root=repo_root,
                theme_dir=t_dir,
                sources=sources,
                curriculum_theme=curr_theme,
                allow_empty_resources=allow_empty_resources,
            )
        )

    if against_ref is not None:
        report.issues.extend(check_immutable_ids_against_git(repo_root, against_ref))

    return report


def validate_feedback_file(feedback_path: Path) -> FeedbackPayload:
    """Valide un fichier JSON brut ou un texte contenant un bloc ```` ```osarai-feedback-v1 ````."""
    if not feedback_path.is_file():
        raise OsaraiError(
            f"Fichier de signalement introuvable : {feedback_path}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(feedback_path)},
        )
    size = feedback_path.stat().st_size
    if size > MAX_FEEDBACK_BYTES:
        raise OsaraiError(
            f"Fichier de signalement trop volumineux ({size} octets > 256 Ko).",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(feedback_path)},
        )

    raw_text = feedback_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise OsaraiError(
            f"Fichier de signalement vide : {feedback_path}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(feedback_path)},
        )

    if raw_text.startswith("{"):
        json_text = raw_text
    else:
        matches = FEEDBACK_BLOCK_RE.findall(raw_text)
        if len(matches) != 1:
            raise OsaraiError(
                "Attendu soit un objet JSON brut, soit exactement un bloc "
                "```` ```osarai-feedback-v1 ... ``` ````.",
                ExitCode.VALIDATION_ERROR,
                details={"file": str(feedback_path), "found_blocks": len(matches)},
            )
        json_text = matches[0].strip()

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise OsaraiError(
            f"JSON invalide dans le bloc `osarai-feedback-v1` : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(feedback_path)},
        ) from exc

    try:
        return FeedbackPayload.model_validate(parsed)
    except ValidationError as exc:
        raise OsaraiError(
            f"Schéma `osarai-feedback-v1` invalide : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={
                "file": str(feedback_path),
                "errors": [
                    {
                        "loc": ".".join(str(p) for p in err.get("loc", ())),
                        "msg": err.get("msg", ""),
                    }
                    for err in exc.errors()
                ],
            },
        ) from exc
