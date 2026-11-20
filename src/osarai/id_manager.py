"""Gestion monotone des identifiants (`assign-ids`) et contrôle d'immuabilité Git."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any, Literal

from ruamel.yaml import YAML

from osarai import ExitCode, OsaraiError
from osarai.schemas import CARD_ID_RE, QUIZ_ID_RE, ThemeMeta
from osarai.yaml_io import dump_yaml_roundtrip, load_yaml


@dataclass(frozen=True)
class ValidationIssue:
    """Anomalie ou avertissement produit par la validation hors-ligne."""

    severity: Literal["error", "warning"]
    code: str
    file: str
    line: int | None
    message: str
    expected_id: str | None = None
    expected_seq_field: str | None = None
    expected_seq_value: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "file": self.file,
            "line": self.line,
            "message": self.message,
        }
        if self.expected_id is not None:
            payload["expected_id"] = self.expected_id
        if self.expected_seq_field is not None:
            payload["expected_seq_field"] = self.expected_seq_field
        if self.expected_seq_value is not None:
            payload["expected_seq_value"] = self.expected_seq_value
        return payload


@dataclass(frozen=True)
class AssignResult:
    """Bilan d'exécution de `assign_missing_ids`."""

    theme_dir: str
    assigned_card_ids: list[str]
    assigned_quiz_ids: list[str]
    last_card_seq: int
    last_quiz_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme_dir": self.theme_dir,
            "assigned_card_ids": self.assigned_card_ids,
            "assigned_quiz_ids": self.assigned_quiz_ids,
            "last_card_seq": self.last_card_seq,
            "last_quiz_seq": self.last_quiz_seq,
        }


def _extract_max_seq(items: list[Any], prefix: str, kind: Literal["c", "q"]) -> int:
    regex = CARD_ID_RE if kind == "c" else QUIZ_ID_RE
    expected_head = f"{prefix}-{kind}"
    max_seq = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if isinstance(raw_id, str) and raw_id.startswith(expected_head):
            match = regex.match(raw_id)
            if match:
                max_seq = max(max_seq, int(match.group(1)))
    return max_seq


def _insert_id_first(mapping: Any, item_id: str) -> None:
    if hasattr(mapping, "insert") and "id" not in mapping:
        mapping.insert(0, "id", item_id)
    else:
        mapping["id"] = item_id


def assign_missing_ids(theme_dir: Path) -> AssignResult:
    """Attribue les `id` manquants dans `flashcards.yaml` et `quiz.yaml` de façon monotone."""
    meta_path = theme_dir / "meta.yaml"
    cards_path = theme_dir / "flashcards.yaml"
    quiz_path = theme_dir / "quiz.yaml"

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

    prefix = meta.id_prefix
    raw_cards_doc = load_yaml(cards_path) if cards_path.exists() else {"cards": []}
    raw_quiz_doc = load_yaml(quiz_path) if quiz_path.exists() else {"questions": []}

    cards_list = raw_cards_doc.get("cards", []) if isinstance(raw_cards_doc, dict) else []
    quiz_list = raw_quiz_doc.get("questions", []) if isinstance(raw_quiz_doc, dict) else []

    next_card_seq = max(meta.last_card_seq, _extract_max_seq(cards_list, prefix, "c"))
    next_quiz_seq = max(meta.last_quiz_seq, _extract_max_seq(quiz_list, prefix, "q"))
    retired_set = set(meta.retired_ids)

    assigned_cards: list[str] = []
    assigned_quizzes: list[str] = []

    if cards_path.exists():

        def _update_cards(doc: Any) -> None:
            nonlocal next_card_seq
            seq_items = doc.get("cards", []) if isinstance(doc, dict) else []
            for item in seq_items:
                if isinstance(item, dict) and not item.get("id"):
                    next_card_seq += 1
                    candidate = f"{prefix}-c{next_card_seq:04d}"
                    while candidate in retired_set:
                        next_card_seq += 1
                        candidate = f"{prefix}-c{next_card_seq:04d}"
                    _insert_id_first(item, candidate)
                    assigned_cards.append(candidate)

        if any(isinstance(it, dict) and not it.get("id") for it in cards_list):
            dump_yaml_roundtrip(cards_path, _update_cards)

    if quiz_path.exists():

        def _update_quiz(doc: Any) -> None:
            nonlocal next_quiz_seq
            seq_items = doc.get("questions", []) if isinstance(doc, dict) else []
            for item in seq_items:
                if isinstance(item, dict) and not item.get("id"):
                    next_quiz_seq += 1
                    candidate = f"{prefix}-q{next_quiz_seq:04d}"
                    while candidate in retired_set:
                        next_quiz_seq += 1
                        candidate = f"{prefix}-q{next_quiz_seq:04d}"
                    _insert_id_first(item, candidate)
                    assigned_quizzes.append(candidate)

        if any(isinstance(it, dict) and not it.get("id") for it in quiz_list):
            dump_yaml_roundtrip(quiz_path, _update_quiz)

    if next_card_seq != meta.last_card_seq or next_quiz_seq != meta.last_quiz_seq:

        def _update_meta(doc: Any) -> None:
            doc["last_card_seq"] = next_card_seq
            doc["last_quiz_seq"] = next_quiz_seq

        dump_yaml_roundtrip(meta_path, _update_meta)

    return AssignResult(
        theme_dir=str(theme_dir),
        assigned_card_ids=assigned_cards,
        assigned_quiz_ids=assigned_quizzes,
        last_card_seq=next_card_seq,
        last_quiz_seq=next_quiz_seq,
    )


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def resolve_merge_base(repo_root: Path, git_ref: str) -> str:
    """Résout l'ancêtre commun `git merge-base <git_ref> HEAD`."""
    proc = _run_git(repo_root, ["merge-base", git_ref, "HEAD"])
    if proc.returncode != 0 or not proc.stdout.strip():
        stderr = proc.stderr.strip() or f"référence Git introuvable ({git_ref!r})"
        raise OsaraiError(
            f"Impossible de résoudre `git merge-base {git_ref} HEAD` : {stderr}",
            ExitCode.VALIDATION_ERROR,
            details={"git_ref": git_ref},
        )
    return proc.stdout.strip()


def _load_git_yaml(repo_root: Path, rev: str, rel_posix: str) -> dict[str, Any] | None:
    proc = _run_git(repo_root, ["show", f"{rev}:{rel_posix}"])
    if proc.returncode != 0:
        return None
    yaml = YAML(typ="safe")
    yaml.version = (1, 2)
    loaded = yaml.load(proc.stdout)
    return loaded if isinstance(loaded, dict) else None


def check_immutable_ids_against_git(repo_root: Path, git_ref: str) -> list[ValidationIssue]:
    """Vérifie la non-suppression de thèmes et l'immuabilité des ID contre `merge-base`."""
    base_sha = resolve_merge_base(repo_root, git_ref)
    ls_proc = _run_git(repo_root, ["ls-tree", "-r", "--name-only", base_sha, "--", "content/"])
    if ls_proc.returncode != 0 or not ls_proc.stdout.strip():
        return []

    historic_themes: set[str] = set()
    for raw_line in ls_proc.stdout.splitlines():
        parts = raw_line.strip().split("/")
        if len(parts) >= 5 and parts[0] == "content" and parts[4] == "meta.yaml":
            historic_themes.add("/".join(parts[:4]))

    issues: list[ValidationIssue] = []
    for theme_rel in sorted(historic_themes):
        theme_dir = repo_root / theme_rel
        curr_meta_path = theme_dir / "meta.yaml"
        if not theme_dir.is_dir() or not curr_meta_path.is_file():
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="THEME_DELETED",
                    file=f"{theme_rel}/meta.yaml",
                    line=None,
                    message=(
                        f"Suppression interdite du dossier de thème `{theme_rel}` "
                        f"présent dans `{git_ref}` ({base_sha[:8]})."
                    ),
                )
            )
            continue

        old_meta = _load_git_yaml(repo_root, base_sha, f"{theme_rel}/meta.yaml") or {}
        old_cards_doc = _load_git_yaml(repo_root, base_sha, f"{theme_rel}/flashcards.yaml") or {}
        old_quiz_doc = _load_git_yaml(repo_root, base_sha, f"{theme_rel}/quiz.yaml") or {}

        curr_meta = load_yaml(curr_meta_path)
        curr_cards_doc = (
            load_yaml(theme_dir / "flashcards.yaml")
            if (theme_dir / "flashcards.yaml").is_file()
            else {}
        )
        curr_quiz_doc = (
            load_yaml(theme_dir / "quiz.yaml") if (theme_dir / "quiz.yaml").is_file() else {}
        )

        if not isinstance(curr_meta, dict):
            continue

        old_last_card = int(old_meta.get("last_card_seq", 0) or 0)
        old_last_quiz = int(old_meta.get("last_quiz_seq", 0) or 0)
        curr_last_card = int(curr_meta.get("last_card_seq", 0) or 0)
        curr_last_quiz = int(curr_meta.get("last_quiz_seq", 0) or 0)

        if curr_last_card < old_last_card:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="COUNTER_DECREASED",
                    file=f"{theme_rel}/meta.yaml",
                    line=None,
                    message=(
                        f"`last_card_seq` a diminué ({curr_last_card} < {old_last_card} "
                        f"dans `{git_ref}`)."
                    ),
                    expected_seq_field="last_card_seq",
                    expected_seq_value=old_last_card,
                )
            )
        if curr_last_quiz < old_last_quiz:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="COUNTER_DECREASED",
                    file=f"{theme_rel}/meta.yaml",
                    line=None,
                    message=(
                        f"`last_quiz_seq` a diminué ({curr_last_quiz} < {old_last_quiz} "
                        f"dans `{git_ref}`)."
                    ),
                    expected_seq_field="last_quiz_seq",
                    expected_seq_value=old_last_quiz,
                )
            )

        old_retired = set(old_meta.get("retired_ids") or [])
        curr_retired = set(curr_meta.get("retired_ids") or [])
        for missing_retired in sorted(old_retired - curr_retired):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="RETIRED_ID_REMOVED",
                    file=f"{theme_rel}/meta.yaml",
                    line=None,
                    message=(
                        f"L'identifiant retiré `{missing_retired}` a été supprimé de `retired_ids`."
                    ),
                )
            )

        old_cards = {
            c["id"]: c.get("type")
            for c in (old_cards_doc.get("cards") or [])
            if isinstance(c, dict) and isinstance(c.get("id"), str)
        }
        curr_cards = {
            c["id"]: c.get("type")
            for c in (curr_cards_doc.get("cards") or [])
            if isinstance(c, dict) and isinstance(c.get("id"), str)
        }

        for cid, old_type in sorted(old_cards.items()):
            if cid not in curr_cards and cid not in curr_retired:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="ID_DELETED_WITHOUT_RETIRING",
                        file=f"{theme_rel}/flashcards.yaml",
                        line=None,
                        message=(
                            f"La carte `{cid}` a disparu sans être inscrite dans "
                            f"`{theme_rel}/meta.yaml -> retired_ids`."
                        ),
                    )
                )
            elif cid in curr_cards and old_type != curr_cards[cid]:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="CARD_TYPE_CHANGED",
                        file=f"{theme_rel}/flashcards.yaml",
                        line=None,
                        message=(
                            f"Mutation interdite du `type` de la carte `{cid}` "
                            f"({old_type!r} -> {curr_cards[cid]!r}) ; retirez `{cid}` dans "
                            "`retired_ids` et créez une nouvelle carte."
                        ),
                    )
                )

        for resurrected in sorted(old_retired & set(curr_cards)):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="RETIRED_ID_REUSED",
                    file=f"{theme_rel}/flashcards.yaml",
                    line=None,
                    message=(
                        f"L'identifiant retiré `{resurrected}` ne peut pas être réactivé."
                    ),
                )
            )

        old_quizzes = {
            q["id"]
            for q in (old_quiz_doc.get("questions") or [])
            if isinstance(q, dict) and isinstance(q.get("id"), str)
        }
        curr_quizzes = {
            q["id"]
            for q in (curr_quiz_doc.get("questions") or [])
            if isinstance(q, dict) and isinstance(q.get("id"), str)
        }

        for qid in sorted(old_quizzes):
            if qid not in curr_quizzes and qid not in curr_retired:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="ID_DELETED_WITHOUT_RETIRING",
                        file=f"{theme_rel}/quiz.yaml",
                        line=None,
                        message=(
                            f"La question `{qid}` a disparu sans être inscrite dans "
                            f"`{theme_rel}/meta.yaml -> retired_ids`."
                        ),
                    )
                )

        for resurrected_q in sorted(old_retired & curr_quizzes):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="RETIRED_ID_REUSED",
                    file=f"{theme_rel}/quiz.yaml",
                    line=None,
                    message=(
                        f"L'identifiant retiré `{resurrected_q}` ne peut pas être réactivé."
                    ),
                )
            )

    return issues
