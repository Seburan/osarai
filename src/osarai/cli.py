"""Point d'entrée CLI `Typer` (`osarai`) — Validation, utilitaires réseau et génération statique."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError

from osarai import ExitCode, OsaraiError, __version__
from osarai.bo_sync import discover_eduscol_pdfs, sync_and_extract_bo
from osarai.commons_fetcher import fetch_commons_image, search_commons
from osarai.grounding_fetcher import fetch_grounding, search_grounding
from osarai.id_manager import assign_missing_ids
from osarai.occlusion_preview import generate_occlusion_previews
from osarai.schemas import SourcesPolicy
from osarai.site_builder import build_site
from osarai.url_checker import check_repository_urls, probe_urls
from osarai.validator import validate_feedback_file, validate_target
from osarai.yaml_io import load_yaml

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


def _emit(payload: Any, *, as_json: bool, human_lines: list[str]) -> None:
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


def _resolve_theme_dir(repo_root: Path, theme: Path) -> Path:
    if theme.is_absolute() or theme.exists():
        return theme
    return repo_root / theme


def _load_sources_policy(repo_root: Path, theme: Path | None = None) -> SourcesPolicy:
    candidates: list[Path] = []
    if repo_root != Path("."):
        candidates.append(repo_root / "sources.yaml")
    if theme is not None:
        resolved = theme.resolve()
        if len(resolved.parts) >= 4 and resolved.parts[-4] == "content":
            candidates.append(resolved.parents[3] / "sources.yaml")
    candidates.append(repo_root / "sources.yaml")

    sources_path = next((p for p in candidates if p.is_file()), candidates[0])
    raw = load_yaml(sources_path)
    try:
        return SourcesPolicy.model_validate(raw)
    except ValidationError as exc:
        raise OsaraiError(
            f"`sources.yaml` invalide ({sources_path}) : {exc}",
            ExitCode.VALIDATION_ERROR,
            details={"file": str(sources_path)},
        ) from exc


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


@app.command("sync-bo")
def cmd_sync_bo(
    discover_url: Annotated[
        str | None,
        typer.Option("--discover-url", help="URL d'une page sommaire Éduscol à inspecter."),
    ] = None,
    cycle: Annotated[
        str | None,
        typer.Option("--cycle", help="Cycle officiel à extraire (`cycle-3` ou `cycle-4`)."),
    ] = None,
    subject: Annotated[
        str | None,
        typer.Option("--subject", help="Matière officielle déclarée dans `bo_manifest.yaml`."),
    ] = None,
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Découvre les PDF officiels Éduscol ou extrait en Markdown tabulaire `bo_manifest.yaml`."""
    try:
        sources = _load_sources_policy(repo_root)
        if discover_url is not None and (cycle is not None or subject is not None):
            raise OsaraiError(
                "Utilisez soit `--discover-url`, soit `--cycle` et `--subject`.",
                ExitCode.VALIDATION_ERROR,
            )
        if discover_url is not None:
            links = discover_eduscol_pdfs(discover_url, sources)
            payload = {
                "ok": True,
                "discover_url": discover_url,
                "count": len(links),
                "pdfs": [lnk.to_dict() for lnk in links],
            }
            human = [f"{len(links)} lien(s) PDF détecté(s) sur {discover_url} :"] + [
                f"- [{lnk.source_kind}] {lnk.title} -> {lnk.url}" for lnk in links
            ]
            _emit(payload, as_json=as_json, human_lines=human)
            raise typer.Exit(code=int(ExitCode.OK))

        if not cycle or not subject:
            raise OsaraiError(
                "Spécifiez `--discover-url <url>` ou le couple `--cycle <c> --subject <s>`.",
                ExitCode.VALIDATION_ERROR,
            )

        manifest_path = repo_root / "curriculum" / "sources" / "bo_manifest.yaml"
        extracted = sync_and_extract_bo(manifest_path, cycle, subject, sources)
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    payload = {
        "ok": True,
        "cycle": cycle,
        "subject": subject,
        "documents": [item.to_dict() for item in extracted],
    }
    human = [
        f"Extraction BO terminée ({len(extracted)} document(s)) :",
        *[
            f"- {it.title} ({it.pages} p., {it.tables_extracted} tableau(x)) -> {it.markdown_path}"
            for it in extracted
        ],
    ]
    _emit(payload, as_json=as_json, human_lines=human)
    raise typer.Exit(code=int(ExitCode.OK))


@app.command("fetch-grounding")
def cmd_fetch_grounding(
    search: Annotated[
        str | None,
        typer.Option("--search", help="Requête de recherche sur Vikidia / Wikipédia FR."),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option("--domain", help="Restreindre la recherche à ce domaine MediaWiki."),
    ] = None,
    url: Annotated[
        str | None,
        typer.Option("--url", help="URL d'un article MediaWiki autorisé à récupérer."),
    ] = None,
    section: Annotated[
        str | None,
        typer.Option("--section", help="Titre exact de la sous-section `== ... ==` à extraire."),
    ] = None,
    theme: Annotated[
        Path | None,
        typer.Option("--theme", help="Dossier de thème dont `meta.yaml` recevra le crédit TASL."),
    ] = None,
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Recherche ou récupère un texte d'appui libre (`<= 40 Ko`) avec crédit TASL automatique."""
    try:
        resolved_theme = _resolve_theme_dir(repo_root, theme) if theme is not None else None
        sources = _load_sources_policy(repo_root, resolved_theme)

        if (search is None) == (url is None):
            raise OsaraiError(
                "Fournissez exactement l'une des options `--search` ou `--url`.",
                ExitCode.VALIDATION_ERROR,
            )

        if search is not None:
            hits = search_grounding(search, sources, domain=domain)
            payload = {
                "ok": True,
                "query": search,
                "count": len(hits),
                "hits": [h.to_dict() for h in hits],
            }
            human = [f"{len(hits)} résultat(s) MediaWiki pour `{search}` :"] + [
                f"- [{h.domain}] {h.title} ({h.wordcount} mots) -> {h.url}" for h in hits
            ]
            _emit(payload, as_json=as_json, human_lines=human)
            raise typer.Exit(code=int(ExitCode.OK))

        assert url is not None
        doc = fetch_grounding(url, sources, section=section, theme_dir=resolved_theme)
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    payload = {"ok": True, **doc.to_dict()}
    human = [
        f"Source : {doc.credit.title} ({doc.credit.license_spdx})",
        f"URL : {doc.url}",
        f"Taille : {doc.byte_length} octets (tronqué={doc.truncated})",
        "",
        doc.text,
    ]
    _emit(payload, as_json=as_json, human_lines=human)
    raise typer.Exit(code=int(ExitCode.OK))


@app.command("fetch-commons")
def cmd_fetch_commons(
    search: Annotated[
        str | None,
        typer.Option("--search", help="Requête de recherche sur Wikimedia Commons."),
    ] = None,
    file_title: Annotated[
        str | None,
        typer.Option("--file", help="Titre `File:...` de l'illustration Wikimedia Commons."),
    ] = None,
    theme: Annotated[
        Path | None,
        typer.Option("--theme", help="Dossier de thème cible pour l'import de l'illustration."),
    ] = None,
    asset_id: Annotated[
        str | None,
        typer.Option("--asset-id", help="Identifiant court (`slug`) de l'illustration importée."),
    ] = None,
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Recherche ou importe une illustration libre Wikimedia Commons au palier `1280 px`."""
    try:
        resolved_theme = _resolve_theme_dir(repo_root, theme) if theme is not None else None
        sources = _load_sources_policy(repo_root, resolved_theme)

        if (search is None) == (file_title is None):
            raise OsaraiError(
                "Fournissez soit `--search <requête>`, soit `--file <File:...>`.",
                ExitCode.VALIDATION_ERROR,
            )

        if search is not None:
            candidates = search_commons(search, sources)
            payload = {
                "ok": True,
                "query": search,
                "count": len(candidates),
                "candidates": [c.to_dict() for c in candidates],
            }
            human = [f"{len(candidates)} illustration(s) libre(s) trouvée(s) :"] + [
                f"- {c.commons_title} [{c.license_spdx}, {c.mime}, {c.width}x{c.height}]"
                for c in candidates
            ]
            _emit(payload, as_json=as_json, human_lines=human)
            raise typer.Exit(code=int(ExitCode.OK))

        if resolved_theme is None or not asset_id:
            raise OsaraiError(
                "L'import `--file` requiert `--theme <chemin>` et `--asset-id <id>`.",
                ExitCode.VALIDATION_ERROR,
            )
        assert file_title is not None
        entry = fetch_commons_image(file_title, resolved_theme, asset_id, sources)
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    payload = {"ok": True, "asset": entry.model_dump(mode="json")}
    human = [
        (
            f"Illustration importée : {entry.filename} "
            f"({entry.width}x{entry.height}, {entry.license_spdx})"
        ),
        "Grille graduée `0..100 %` générée dans `.osarai_tmp/previews/`.",
    ]
    _emit(payload, as_json=as_json, human_lines=human)
    raise typer.Exit(code=int(ExitCode.OK))


@app.command("preview-occlusions")
def cmd_preview_occlusions(
    theme: Annotated[
        Path,
        typer.Option("--theme", help="Dossier de thème contenant les éléments occultés."),
    ],
    item_id: Annotated[
        str | None,
        typer.Option("--item-id", help="Filtrer sur un identifiant précis (`cNNNN` ou `qNNNN`)."),
    ] = None,
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Génère hors Git les aperçus pleine taille et mobile (`320 px`) des masques CSS."""
    try:
        resolved_theme = _resolve_theme_dir(repo_root, theme)
        if repo_root != Path("."):
            out_dir = repo_root / ".osarai_tmp" / "previews"
        elif (
            len(resolved_theme.resolve().parts) >= 4
            and resolved_theme.resolve().parts[-4] == "content"
        ):
            out_dir = resolved_theme.resolve().parents[3] / ".osarai_tmp" / "previews"
        else:
            out_dir = repo_root / ".osarai_tmp" / "previews"

        files = generate_occlusion_previews(resolved_theme, out_dir, item_id=item_id)
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    str_files = [str(p) for p in files]
    payload = {"ok": True, "count": len(str_files), "previews": str_files}
    human = [f"{len(str_files)} aperçu(s) généré(s) :"] + [f"- {p}" for p in str_files]
    _emit(payload, as_json=as_json, human_lines=human)
    raise typer.Exit(code=int(ExitCode.OK))


@app.command("probe-links")
def cmd_probe_links(
    url: Annotated[
        list[str] | None,
        typer.Option("--url", help="URL candidate à sonder (option répétable)."),
    ] = None,
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Sonde les en-têtes HTTP ou `oEmbed` de liens externes candidats pour tri HITL."""
    try:
        if not url:
            raise OsaraiError(
                "Fournissez au moins une option `--url <https://...>`.",
                ExitCode.VALIDATION_ERROR,
            )
        sources = _load_sources_policy(repo_root)
        results = asyncio.run(probe_urls(url, sources))
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    payload = {
        "ok": True,
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }
    human = [
        f"- [{'OK' if r.ok else r.verdict.upper()}] {r.canonical_url} "
        f"(status={r.status}, titre={r.title!r})"
        for r in results
    ]
    _emit(payload, as_json=as_json, human_lines=human)
    raise typer.Exit(code=int(ExitCode.OK))


@app.command("check-urls")
def cmd_check_urls(
    diff: Annotated[
        str | None,
        typer.Option("--diff", help="Ne vérifier que les liens modifiés contre cette réf. Git."),
    ] = None,
    json_report: Annotated[
        Path | None,
        typer.Option("--json-report", help="Écrire le rapport `link-report.json` à ce chemin."),
    ] = None,
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Contrôle les liens externes publiés dans `resources.yaml` (PR `--diff` ou cron global)."""
    try:
        sources = _load_sources_policy(repo_root)
        summary = asyncio.run(
            check_repository_urls(
                repo_root=repo_root,
                sources=sources,
                diff_ref=diff,
                json_report=json_report,
            )
        )
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    human = [
        f"Liens vérifiés : {summary.checked_count} "
        f"(morts={len(summary.dead_links)}, avertissements={len(summary.warnings)})",
        *[f"[MORT] {d['theme']} — {d['url']} ({d['reason']})" for d in summary.dead_links],
        *[f"[AVERTISSEMENT] {w['theme']} — {w['url']} ({w['reason']})" for w in summary.warnings],
    ]
    _emit(summary.to_dict(), as_json=as_json, human_lines=human)
    raise typer.Exit(code=int(summary.exit_code))


@app.command("assign-ids")
def cmd_assign_ids(
    theme: Annotated[
        Path,
        typer.Option(
            "--theme",
            help="Chemin du dossier de thème (`content/<cycle>/<matiere>/<theme>`).",
        ),
    ],
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Attribue de façon monotone les identifiants `cNNNN` / `qNNNN` manquants d'un thème."""
    try:
        resolved_theme = _resolve_theme_dir(repo_root, theme)
        result = assign_missing_ids(resolved_theme)
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


@app.command("build-site")
def cmd_build_site(
    output: Annotated[
        Path,
        typer.Option("--output", help="Répertoire de sortie du site statique compilé."),
    ] = Path("dist"),
    base_url: Annotated[
        str,
        typer.Option("--base-url", help="Préfixe de sous-chemin GitHub Pages (ex. `/osarai`)."),
    ] = "",
    repo_url: Annotated[
        str | None,
        typer.Option("--repo-url", help="URL du dépôt GitHub pour les liens de signalement."),
    ] = None,
    repo_root: RepoRootOpt = Path("."),
    as_json: JsonOpt = False,
) -> None:
    """Compile le portail web statique `dist/` (HTML pré-rendu, index de recherche et KaTeX)."""
    try:
        resolved_out = output if output.is_absolute() else (repo_root / output)
        summary = build_site(
            repo_root=repo_root,
            output_dir=resolved_out,
            base_url=base_url,
            repo_url=repo_url,
        )
    except ValidationError as exc:
        _handle_error(
            OsaraiError(f"Erreur de schéma lors du build : {exc}", ExitCode.VALIDATION_ERROR),
            as_json=as_json,
        )
        return
    except OsaraiError as exc:
        _handle_error(exc, as_json=as_json)
        return

    payload = {"ok": True, **summary.to_dict()}
    human = [
        f"Portail statique compilé dans `{summary.output_dir}` (base_url={summary.base_url!r}) :",
        f"- {summary.subjects_count} matière(s), {summary.themes_count} thème(s), "
        f"build_sha={summary.build_sha}",
    ]
    _emit(payload, as_json=as_json, human_lines=human)
    raise typer.Exit(code=int(ExitCode.OK))
