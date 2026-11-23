"""Lecture/écriture YAML 1.2 sûre, suivi des numéros de ligne et empreintes SHA-256."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from osarai import ExitCode, OsaraiError


def load_yaml(path: Path) -> Any:
    """Charge un fichier YAML en mode sûr (norme YAML 1.2)."""
    yaml = YAML(typ="safe")
    yaml.version = (1, 2)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.load(handle)
    except FileNotFoundError as exc:
        raise OsaraiError(
            f"Fichier YAML introuvable : {path}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(path)},
        ) from exc
    except YAMLError as exc:
        raise OsaraiError(
            f"Syntaxe YAML 1.2 invalide dans {path} : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(path)},
        ) from exc


def load_yaml_with_lines(path: Path) -> Any:
    """Charge un fichier YAML 1.2 en mode round-trip (lecture seule) avec `.lc.line`."""
    yaml = YAML(typ="rt")
    yaml.version = (1, 2)
    yaml.preserve_quotes = True
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.load(handle)
    except FileNotFoundError as exc:
        raise OsaraiError(
            f"Fichier YAML introuvable : {path}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(path)},
        ) from exc
    except YAMLError as exc:
        raise OsaraiError(
            f"Syntaxe YAML 1.2 invalide dans {path} : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(path)},
        ) from exc


def get_yaml_line(node: Any, key_or_index: str | int | None = None) -> int | None:
    """Extrait le numéro de ligne (base 1) d'un nœud `ruamel.yaml` en mode round-trip."""
    lc = getattr(node, "lc", None)
    if lc is None:
        return None
    if key_or_index is not None and getattr(lc, "data", None):
        entry = lc.data.get(key_or_index) if isinstance(lc.data, dict) else None
        if entry is None and isinstance(lc.data, list) and isinstance(key_or_index, int):
            if 0 <= key_or_index < len(lc.data):
                entry = lc.data[key_or_index]
        if entry and isinstance(entry[0], int):
            return entry[0] + 1
    line = getattr(lc, "line", None)
    return (line + 1) if isinstance(line, int) else None


def dump_yaml_roundtrip(path: Path, updater_fn: Callable[[Any], None]) -> None:
    """Met à jour un fichier YAML 1.2 sur place (commentaires, guillemets et indentation)."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle)
    except FileNotFoundError as exc:
        raise OsaraiError(
            f"Fichier YAML introuvable : {path}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(path)},
        ) from exc
    except YAMLError as exc:
        raise OsaraiError(
            f"Syntaxe YAML 1.2 invalide dans {path} : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(path)},
        ) from exc

    updater_fn(data)

    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)
    tmp_path.replace(path)


def compute_content_hash(canonical_fields: Mapping[str, Any]) -> str:
    """Retourne les 8 premiers caractères hexadécimaux du SHA-256 du JSON canonique trié."""
    serialized = json.dumps(
        dict(canonical_fields),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:8]


def card_canonical_fields(
    card_json: Mapping[str, Any],
    active_cloze_index: int | None = None,
) -> dict[str, Any]:
    """Construit les champs canoniques d'une carte depuis `model_dump(mode='json')`."""
    return {
        "type": card_json["type"],
        "front": card_json["front"],
        "back": card_json["back"],
        "explanation": card_json.get("explanation"),
        "asset_id": card_json.get("asset_id"),
        "asset_role": card_json.get("asset_role", "none"),
        "occlusions": card_json.get("occlusions") or [],
        "active_cloze_index": active_cloze_index if card_json["type"] == "cloze" else None,
    }


def quiz_canonical_fields(quiz_json: Mapping[str, Any]) -> dict[str, Any]:
    """Construit le dictionnaire canonique d'un QCM à partir de `model_dump(mode='json')`."""
    return {
        "question": quiz_json["question"],
        "choices": list(quiz_json["choices"]),
        "answer_index": quiz_json["answer_index"],
        "explanation": quiz_json["explanation"],
        "asset_id": quiz_json.get("asset_id"),
        "asset_role": quiz_json.get("asset_role", "none"),
        "occlusions": quiz_json.get("occlusions") or [],
    }
