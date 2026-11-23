"""Point d'entrée CLI `Typer` (`osarai`) — Jalon 1 (`assign-ids`, `validate`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from osarai import ExitCode, OsaraiError, __version__
from osarai.id_manager import assign_missing_ids
from osarai.validator import validate_feedback_file, validate_target

app = typer.Typer(
    name="osarai",
    help="Outillage Python déterministe sans appel LLM pour la plateforme éducative Osarai.",
    no_args_is_help=True,
    add_completion=False,
)

JsonOpt = Annotated[
    bool,
    typer.Option("--json", help="Émettre la sortie au format JSON structuré."),
]
RepoRootOpt = Annotated[
    Path,
    typer.Option(
        "--repo-root",
        help="Racine du dépôt Osarai (par défaut : répertoire courant).",
        exists=False,
    ),
]


def _emit(payload: dict[str, Any], *, as_json: bool, human_lines: list[str]) -> None:
    if as_json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in human_lines:
            typer.echo(line)


def _handle_error(exc: OsaraiError, *, as_json: bool) -> None:
    if as_json:
        body = {
            "ok": False,
            "exit_code": int(exc.exit_code),
            "error": exc.message,
            **exc.details,
        }
        typer.echo(json.dumps(body, ensure_ascii=False, indent=2))
    else:
        typer.echo(f"Erreur : {exc.message}", err=True)
    raise typer.Exit(code=int(exc.exit_code))


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"osarai {__version__}")
        raise typer.Exit(code=int(ExitCode.OK))


@app.callback()
def _main_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Afficher la version d'Osarai et quitter.",
        ),
    ] = False,
) -> None:
    """Point d'entrée principal de la CLI `osarai`."""


@app.command("assign-ids")
def cmd_assign_ids(
    theme: Annotated[
        Path,
        typer.Option(
            "--theme", help="Chemin du dossier de thème (`content/<cycle>/<matiere>/<theme>`)."
        ),
    ],
    as_json: JsonOpt = False,
) -> None:
    """Attribue de façon monotone les identifiants `cNNNN` / `qNNNN` manquants d'un thème."""
    try:
        result = assign_missing_ids(theme)
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    payload = {"ok": True, **result.to_dict()}
    human = [
        f"Thème : {result.theme_dir}",
        (
            f"Cartes numérotées : {len(result.assigned_card_ids)} "
            f"(last_card_seq={result.last_card_seq})"
        ),
        f"QCM numérotés : {len(result.assigned_quiz_ids)} (last_quiz_seq={result.last_quiz_seq})",
    ]
    _emit(payload, as_json=as_json, human_lines=human)
    raise typer.Exit(code=int(ExitCode.OK))


@app.command("validate")
def cmd_validate(
    theme: Annotated[
        Path | None,
        typer.Option("--theme", help="Valider uniquement ce dossier de thème."),
    ] = None,
    against_ref: Annotated[
        str | None,
        typer.Option(
            "--against-ref", help="Vérifier l'immuabilité des ID contre cette référence Git."
        ),
    ] = None,
    allow_empty_resources: Annotated[
        bool,
        typer.Option(
            "--allow-empty-resources",
            help="Autoriser temporairement `resources: []` (fin de Phase 1 d'`author-theme`).",
        ),
    ] = False,
    feedback: Annotated[
        Path | None,
        typer.Option(
            "--feedback", help="Valider uniquement un fichier ou bloc `osarai-feedback-v1`."
        ),
    ] = None,
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Valide hors-ligne les schémas YAML 1.2, formules LaTeX/Cloze, licences ou un signalement."""
    try:
        if feedback is not None:
            fb_payload = validate_feedback_file(feedback)
            out = {
                "ok": True,
                "schema": fb_payload.schema_name,
                "item_count": len(fb_payload.items),
                "items": [item.model_dump(mode="json") for item in fb_payload.items],
            }
            _emit(
                out,
                as_json=as_json,
                human_lines=[
                    f"Signalement `{fb_payload.schema_name}` valide "
                    f"({len(fb_payload.items)} élément(s))."
                ],
            )
            raise typer.Exit(code=int(ExitCode.OK))

        report = validate_target(
            repo_root=repo_root,
            theme_dir=theme,
            against_ref=against_ref,
            allow_empty_resources=allow_empty_resources,
        )
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    human_lines: list[str] = []
    for iss in report.issues:
        loc = f"{iss.file}:{iss.line}" if iss.line is not None else iss.file
        prefix = "ERREUR" if iss.severity == "error" else "AVERTISSEMENT"
        human_lines.append(f"[{prefix}] {loc} ({iss.code}) — {iss.message}")
    summary = (
        f"Validation {'réussie' if report.ok else 'en échec'} : "
        f"{report.checked_themes} thème(s), {len(report.errors)} erreur(s), "
        f"{len(report.warnings)} avertissement(s)."
    )
    human_lines.append(summary)

    _emit(report.to_dict(), as_json=as_json, human_lines=human_lines)
    raise typer.Exit(code=int(ExitCode.OK if report.ok else ExitCode.VALIDATION_ERROR))
