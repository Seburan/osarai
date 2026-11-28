"""Compilateur du portail web statique Osarai (`Jinja2` + `markdown-it-py` + KaTeX local)."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from mdit_py_plugins.texmath import texmath_plugin

from osarai import ExitCode, OsaraiError
from osarai.schemas import (
    GRADE_ORDER,
    AssetsFile,
    CurriculumFile,
    Flashcard,
    FlashcardsFile,
    QuizFile,
    ResourcesFile,
    SourcesPolicy,
    ThemeMeta,
    normalize_search_text,
    parse_cloze_tokens,
)
from osarai.yaml_io import (
    card_canonical_fields,
    compute_content_hash,
    load_yaml,
    quiz_canonical_fields,
)

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
WEB_ASSETS_DIR = PACKAGE_DIR / "web_assets"
DEFAULT_REPO_URL = "https://github.com/Seburan/osarai"

GRADE_LABELS: dict[str, str] = {
    "6eme": "6ème",
    "5eme": "5ème",
    "4eme": "4ème",
    "3eme": "3ème",
}

CYCLE_LABELS: dict[str, str] = {
    "cycle-3": "Cycle 3 (6ème)",
    "cycle-4": "Cycle 4 (5ème, 4ème, 3ème)",
}

SUMMARY_BOLD_TERM_RE = re.compile(r"\*\*([^*]{2,80})\*\*")
SUMMARY_SUBHEADING_RE = re.compile(r"^#{3,4}\s+(.+)$", re.MULTILINE)
SUMMARY_IMAGE_ALT_RE = re.compile(r"!\[([^\]]+)\]\(assets/")
MARKDOWN_ASSET_URL_RE = re.compile(r"\(assets/[^)]+\)")
LATEX_COMMAND_RE = re.compile(r"\\[a-zA-Z]+")
SEARCH_WORD_RE = re.compile(r"[a-z0-9]{2,}")
SEARCH_MAX_CHARS = 2400

FRENCH_SEARCH_STOPWORDS: frozenset[str] = frozenset(
    {
        "au",
        "aussi",
        "autre",
        "autres",
        "aux",
        "avec",
        "avoir",
        "bien",
        "car",
        "ce",
        "ces",
        "cet",
        "cette",
        "chez",
        "comme",
        "dans",
        "de",
        "des",
        "donc",
        "dont",
        "du",
        "elle",
        "elles",
        "en",
        "entre",
        "est",
        "et",
        "ete",
        "etre",
        "fait",
        "font",
        "il",
        "ils",
        "la",
        "le",
        "les",
        "leur",
        "leurs",
        "lors",
        "mais",
        "meme",
        "memes",
        "moins",
        "ne",
        "ni",
        "non",
        "nous",
        "on",
        "ont",
        "ou",
        "oui",
        "par",
        "pas",
        "peut",
        "peuvent",
        "plus",
        "pour",
        "puis",
        "que",
        "qui",
        "quoi",
        "sa",
        "sans",
        "se",
        "ses",
        "son",
        "sont",
        "sous",
        "sur",
        "tous",
        "tout",
        "toute",
        "toutes",
        "tres",
        "un",
        "une",
        "vers",
        "vous",
    }
)


@dataclass(frozen=True)
class BuildSummary:
    """Bilan d'exécution de `build_site`."""

    output_dir: str
    base_url: str
    repo_url: str
    build_sha: str
    subjects_count: int
    themes_count: int
    search_entries_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "base_url": self.base_url,
            "repo_url": self.repo_url,
            "build_sha": self.build_sha,
            "subjects_count": self.subjects_count,
            "themes_count": self.themes_count,
            "search_entries_count": self.search_entries_count,
        }


def normalize_base_url(base_url: str) -> str:
    """Normalise `--base-url` (`""` pour `""` ou `"/"`, sinon `"/<chemin>"` sans `/` final)."""
    stripped = base_url.strip()
    if not stripped or stripped == "/":
        return ""
    return "/" + stripped.strip("/")


def resolve_repo_url(repo_root: Path, explicit_repo_url: str | None) -> str:
    """Résout l'URL du dépôt GitHub depuis `--repo-url` ou `pyproject.toml`."""
    if explicit_repo_url and explicit_repo_url.strip():
        return explicit_repo_url.strip().rstrip("/")

    pyproject_path = repo_root / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            with pyproject_path.open("rb") as handle:
                data = tomllib.load(handle)
            repo = data.get("project", {}).get("urls", {}).get("Repository")
            if isinstance(repo, str) and repo.strip():
                return repo.strip().rstrip("/")
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return DEFAULT_REPO_URL


def resolve_build_sha(repo_root: Path) -> str:
    """Retourne le SHA court Git (`8` hex) de `HEAD` ou `'dev'` hors dépôt Git."""
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--short=8", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    sha = proc.stdout.strip()
    if proc.returncode == 0 and sha:
        return sha
    return "dev"


def create_markdown_renderer() -> MarkdownIt:
    """Configure `markdown-it-py` (`html=False`) et `texmath` pour `\\(...\\)` / `\\[...\\]`."""
    md = (
        MarkdownIt("commonmark", {"html": False, "typographer": False})
        .enable("table")
        .use(texmath_plugin, delimiters="brackets")
    )

    def _render_math_inline(
        _self: Any, tokens: list[Any], idx: int, _options: Any, _env: Any
    ) -> str:
        escaped = html.escape(tokens[idx].content, quote=True)
        return f"\\({escaped}\\)"

    def _render_math_block(
        _self: Any, tokens: list[Any], idx: int, _options: Any, _env: Any
    ) -> str:
        escaped = html.escape(tokens[idx].content, quote=True)
        return f'<div class="math-block">\\[{escaped}\\]</div>\n'

    def _render_math_block_eqno(
        _self: Any, tokens: list[Any], idx: int, _options: Any, _env: Any
    ) -> str:
        escaped = html.escape(tokens[idx].content, quote=True)
        info = html.escape(tokens[idx].info or "", quote=True)
        return (
            f'<div class="math-block">\\[{escaped}\\] '
            f'<span class="math-eqno">({info})</span></div>\n'
        )

    md.add_render_rule("math_inline", _render_math_inline)
    md.add_render_rule("math_block", _render_math_block)
    md.add_render_rule("math_block_eqno", _render_math_block_eqno)
    return md


def expand_flashcard_for_web(
    card: Flashcard,
    md: MarkdownIt,
) -> list[dict[str, Any]]:
    """Déplie une carte (`basic` -> 1 item, `cloze` à `K` indices -> `#c1..#cK`)."""
    if not card.id:
        raise OsaraiError(
            "Toutes les cartes mémoire doivent posséder un `id` avant `build-site` "
            "(exécutez `uv run osarai assign-ids`).",
            ExitCode.VALIDATION_ERROR,
        )

    card_json = card.model_dump(mode="json")
    explanation_html = md.renderInline(card.explanation) if card.explanation else None

    if card.type == "basic":
        c_hash = compute_content_hash(card_canonical_fields(card_json, active_cloze_index=None))
        return [
            {
                "item_id": card.id,
                "parent_id": card.id,
                "concept_id": card.concept_id,
                "reperes_level": card.reperes_level,
                "priority": card.priority,
                "type": "basic",
                "content_hash": c_hash,
                "front_html": md.renderInline(card.front),
                "back_html": md.renderInline(card.back),
                "explanation_html": explanation_html,
                "asset_id": card.asset_id,
                "asset_role": card.asset_role,
                "occlusions": card_json["occlusions"],
            }
        ]

    tokens = parse_cloze_tokens(card.front)
    distinct_indices = sorted({tok.index for tok in tokens})
    expanded: list[dict[str, Any]] = []

    for active_k in distinct_indices:
        front_parts: list[str] = []
        back_parts: list[str] = []
        cursor = 0

        for tok in tokens:
            outside_raw = card.front[cursor : tok.start]
            if outside_raw:
                outside_rendered = md.renderInline(outside_raw)
                front_parts.append(outside_rendered)
                back_parts.append(outside_rendered)

            answer_rendered = md.renderInline(tok.answer.strip())
            if tok.index == active_k:
                if tok.hint is not None and tok.hint.strip():
                    hint_rendered = md.renderInline(tok.hint.strip())
                    front_parts.append(f'<span class="cloze-blank">[{hint_rendered}]</span>')
                else:
                    front_parts.append('<span class="cloze-blank">[...]</span>')
                back_parts.append(f'<strong class="cloze-answer">{answer_rendered}</strong>')
            else:
                front_parts.append(answer_rendered)
                back_parts.append(answer_rendered)

            cursor = tok.end

        tail_raw = card.front[cursor:]
        if tail_raw:
            tail_rendered = md.renderInline(tail_raw)
            front_parts.append(tail_rendered)
            back_parts.append(tail_rendered)

        c_hash = compute_content_hash(card_canonical_fields(card_json, active_cloze_index=active_k))
        expanded.append(
            {
                "item_id": f"{card.id}#c{active_k}",
                "parent_id": card.id,
                "concept_id": card.concept_id,
                "reperes_level": card.reperes_level,
                "priority": card.priority,
                "type": "cloze",
                "active_cloze_index": active_k,
                "content_hash": c_hash,
                "front_html": "".join(front_parts),
                "back_html": "".join(back_parts),
                "explanation_html": explanation_html,
                "asset_id": card.asset_id,
                "asset_role": card.asset_role,
                "occlusions": card_json["occlusions"],
            }
        )

    return expanded


def _enhance_summary_images(
    summary_html: str, assets_by_filename: dict[str, dict[str, Any]]
) -> str:
    """Encapsule les images locales de `summary.md` dans `.asset-container` avec crédit TASL."""
    img_tag_re = re.compile(r'<img\s+src="assets/([^"]+)"\s+alt="([^"]*)"\s*/?>')

    def _replace(match: re.Match[str]) -> str:
        fname = html.unescape(match.group(1))
        alt_escaped = match.group(2)
        asset = assets_by_filename.get(fname)
        if asset is None:
            return match.group(0)
        w = int(asset["width"])
        h = int(asset["height"])
        title_esc = html.escape(str(asset["title"]))
        author_esc = html.escape(str(asset["author"]))
        src_url_esc = html.escape(str(asset["source_url"]))
        lic_spdx_esc = html.escape(str(asset["license_spdx"]))
        lic_url_esc = html.escape(str(asset["license_url"]))
        mod_esc = html.escape(str(asset["modifications_note"]))
        fname_esc = html.escape(fname)
        return (
            f'<figure class="summary-figure">'
            f'<div class="asset-stage">'
            f'<div class="asset-container" style="--asset-w: {w}; --asset-h: {h};">'
            f'<img src="assets/{fname_esc}" alt="{alt_escaped}" '
            f'width="{w}" height="{h}" loading="lazy">'
            f"</div>"
            f'<button type="button" class="btn-zoom-asset" '
            f'aria-label="Agrandir le schéma : {title_esc}">Agrandir le schéma</button>'
            f"</div>"
            f'<figcaption class="asset-caption">'
            f"<strong>{title_esc}</strong> — Auteur : {author_esc} · "
            f'<a href="{src_url_esc}" target="_blank" rel="noopener noreferrer">'
            f"Source Wikimedia</a> · "
            f'Licence <a href="{lic_url_esc}" target="_blank" rel="noopener noreferrer">'
            f"{lic_spdx_esc}</a> ({mod_esc})"
            f"</figcaption>"
            f"</figure>"
        )

    return img_tag_re.sub(_replace, summary_html)


def _enhance_summary_tables(summary_html: str) -> str:
    """Ajoute `scope="col"` aux en-têtes et encapsule les tableaux pour le scroll mobile."""
    thead_re = re.compile(r"<thead>[\s\S]*?</thead>")
    th_re = re.compile(r"<th(?![^>]*\bscope=)(\s+[^>]*?)?>")
    table_re = re.compile(r"<table>[\s\S]*?</table>")

    def _scope_thead(match: re.Match[str]) -> str:
        return th_re.sub(lambda m: f'<th scope="col"{m.group(1) or ""}>', match.group(0))

    with_scopes = thead_re.sub(_scope_thead, summary_html)
    return table_re.sub(
        lambda m: (
            '<div class="table-wrapper" tabindex="0" role="region" '
            f'aria-label="Tableau récapitulatif du cours">{m.group(0)}</div>'
        ),
        with_scopes,
    )


def _extract_summary_description(summary_md: str, fallback_title: str) -> str:
    lines: list[str] = []
    for raw_line in summary_md.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("#", "![", "\\[", "|", "-")):
            continue
        cleaned = re.sub(r"\*\*|\*|`|\\\(|\\\)", "", stripped)
        lines.append(cleaned)
        if len(" ".join(lines)) >= 150:
            break
    joined = " ".join(lines).strip()
    if not joined:
        return f"Fiche de synthèse, cartes mémoire et QCM corrigés : {fallback_title}."
    return joined[:180].rstrip() + ("…" if len(joined) > 180 else "")


def _extract_markdown_section(summary_md: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        summary_md,
        re.MULTILINE,
    )
    return match.group(1) if match else ""


def _build_search_terms(
    meta: ThemeMeta,
    subject_label: str,
    summary_md: str,
    cards_file: FlashcardsFile | None = None,
) -> str:
    cloze_answers = (
        [
            tok.answer
            for card in cards_file.cards
            if card.type == "cloze"
            for tok in parse_cloze_tokens(card.front)
        ]
        if cards_file is not None
        else []
    )
    defs_section = _extract_markdown_section(summary_md, "Définitions clés")
    essentiel_section = _extract_markdown_section(summary_md, "L'essentiel à retenir")
    cleaned_summary = MARKDOWN_ASSET_URL_RE.sub(" ", summary_md)

    parts: list[str] = [
        meta.title,
        meta.theme_slug.replace("-", " "),
        subject_label,
        meta.subject_code,
        *meta.reperes_levels,
        *(c.label for c in meta.key_concepts),
        *(c.concept_id.replace("-", " ") for c in meta.key_concepts),
        *(m.group(1) for m in SUMMARY_SUBHEADING_RE.finditer(summary_md)),
        *(m.group(1) for m in SUMMARY_BOLD_TERM_RE.finditer(summary_md)),
        *cloze_answers,
        defs_section,
        essentiel_section,
        *(m.group(1) for m in SUMMARY_IMAGE_ALT_RE.finditer(summary_md)),
        cleaned_summary,
    ]
    raw_joined = LATEX_COMMAND_RE.sub(" ", " ".join(parts))
    normalized = normalize_search_text(raw_joined)

    unique_tokens: list[str] = []
    seen: set[str] = set()
    total_len = 0
    for tok in SEARCH_WORD_RE.findall(normalized):
        if tok in FRENCH_SEARCH_STOPWORDS or tok in seen:
            continue
        added_len = len(tok) if not unique_tokens else len(tok) + 1
        if total_len + added_len > SEARCH_MAX_CHARS:
            break
        seen.add(tok)
        unique_tokens.append(tok)
        total_len += added_len

    return " ".join(unique_tokens)


def _create_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["GRADE_LABELS"] = GRADE_LABELS
    env.globals["CYCLE_LABELS"] = CYCLE_LABELS
    return env


def _copy_static_web_assets(output_dir: Path) -> None:
    if not WEB_ASSETS_DIR.is_dir():
        raise OsaraiError(
            f"Dossier `web_assets` introuvable : {WEB_ASSETS_DIR}",
            ExitCode.VALIDATION_ERROR,
        )
    dest_assets = output_dir / "assets"
    if dest_assets.exists():
        shutil.rmtree(dest_assets)
    shutil.copytree(WEB_ASSETS_DIR, dest_assets)


def _write_manifest(output_dir: Path, norm_base_url: str) -> None:
    scoped_root = f"{norm_base_url}/"
    manifest = {
        "name": "Osarai — Révisions libres du Collège",
        "short_name": "Osarai",
        "lang": "fr",
        "display": "standalone",
        "start_url": scoped_root,
        "scope": scoped_root,
        "background_color": "#f8fafc",
        "theme_color": "#1d4ed8",
        "icons": [
            {
                "src": f"{norm_base_url}/assets/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any",
            }
        ],
    }
    (output_dir / "manifest.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_site(
    repo_root: Path,
    output_dir: Path,
    base_url: str = "",
    repo_url: str | None = None,
) -> BuildSummary:
    """Compile l'intégralité du portail statique HTML/CSS/JS dans `output_dir` sans réseau."""
    sources_path = repo_root / "sources.yaml"
    if sources_path.is_file():
        SourcesPolicy.model_validate(load_yaml(sources_path))

    norm_base = normalize_base_url(base_url)
    resolved_repo_url = resolve_repo_url(repo_root, repo_url)
    build_sha = resolve_build_sha(repo_root)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _copy_static_web_assets(output_dir)
    _write_manifest(output_dir, norm_base)

    md = create_markdown_renderer()
    jinja_env = _create_jinja_env()

    subjects_view: list[dict[str, Any]] = []
    search_entries: list[dict[str, Any]] = []
    published_grades: set[str] = set()
    total_themes = 0

    curriculum_root = repo_root / "curriculum"
    content_root = repo_root / "content"

    if curriculum_root.is_dir():
        for curr_path in sorted(curriculum_root.glob("cycle-*/*.yaml")):
            curr = CurriculumFile.model_validate(load_yaml(curr_path))
            subject_themes: list[dict[str, Any]] = []
            subject_grades: set[str] = set()

            for curr_theme in curr.themes:
                theme_dir = content_root / curr.cycle / curr.subject / curr_theme.theme_slug
                if not theme_dir.is_dir() or not (theme_dir / "meta.yaml").is_file():
                    continue

                meta = ThemeMeta.model_validate(load_yaml(theme_dir / "meta.yaml"))
                assets_file = AssetsFile.model_validate(load_yaml(theme_dir / "assets.yaml"))
                cards_file = FlashcardsFile.model_validate(load_yaml(theme_dir / "flashcards.yaml"))
                quiz_file = QuizFile.model_validate(load_yaml(theme_dir / "quiz.yaml"))
                resources_file = ResourcesFile.model_validate(
                    load_yaml(theme_dir / "resources.yaml"),
                    context={"allow_empty_resources": True},
                )
                summary_md = (theme_dir / "summary.md").read_text(encoding="utf-8")

                assets_by_id: dict[str, dict[str, Any]] = {}
                assets_by_filename: dict[str, dict[str, Any]] = {}
                dest_theme_dir = output_dir / curr.cycle / curr.subject / meta.theme_slug
                dest_theme_assets = dest_theme_dir / "assets"

                for asset in assets_file.assets:
                    asset_dump = asset.model_dump(mode="json")
                    assets_by_id[asset.asset_id] = asset_dump
                    assets_by_filename[asset.filename] = asset_dump
                    src_img = theme_dir / "assets" / asset.filename
                    if not src_img.is_file():
                        raise OsaraiError(
                            f"Illustration manquante lors du build : {src_img}",
                            ExitCode.VALIDATION_ERROR,
                        )
                    dest_theme_assets.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_img, dest_theme_assets / asset.filename)

                raw_summary_html = md.render(summary_md)
                summary_html = _enhance_summary_tables(
                    _enhance_summary_images(raw_summary_html, assets_by_filename)
                )

                expanded_cards: list[dict[str, Any]] = []
                for card in cards_file.cards:
                    expanded_cards.extend(expand_flashcard_for_web(card, md))

                serialized_quiz: list[dict[str, Any]] = []
                for question in quiz_file.questions:
                    if not question.id:
                        raise OsaraiError(
                            "Toutes les questions QCM doivent posséder un `id` avant `build-site`.",
                            ExitCode.VALIDATION_ERROR,
                        )
                    q_json = question.model_dump(mode="json")
                    q_hash = compute_content_hash(quiz_canonical_fields(q_json))
                    serialized_quiz.append(
                        {
                            "item_id": question.id,
                            "parent_id": question.id,
                            "concept_id": question.concept_id,
                            "reperes_level": question.reperes_level,
                            "difficulty": question.difficulty,
                            "content_hash": q_hash,
                            "question_html": md.renderInline(question.question),
                            "choices_html": [md.renderInline(ch) for ch in question.choices],
                            "answer_index": question.answer_index,
                            "explanation_html": md.renderInline(question.explanation),
                            "asset_id": question.asset_id,
                            "asset_role": question.asset_role,
                            "occlusions": q_json["occlusions"],
                        }
                    )

                theme_data_payload = {
                    "cycle": meta.cycle,
                    "subject": meta.subject,
                    "subject_code": meta.subject_code,
                    "theme_slug": meta.theme_slug,
                    "build_sha": build_sha,
                    "repo_url": resolved_repo_url,
                    "retired_ids": list(meta.retired_ids),
                    "assets": assets_by_id,
                    "flashcards": expanded_cards,
                    "quiz": serialized_quiz,
                }

                theme_rel_url = f"/{curr.cycle}/{curr.subject}/{meta.theme_slug}/"
                description = _extract_summary_description(summary_md, meta.title)

                dest_theme_dir.mkdir(parents=True, exist_ok=True)
                theme_html = jinja_env.get_template("theme.html").render(
                    base_url=norm_base,
                    repo_url=resolved_repo_url,
                    build_sha=build_sha,
                    available_grades=sorted(
                        published_grades | set(meta.reperes_levels) | {"5eme"},
                        key=lambda g: GRADE_ORDER.get(g, 99),
                    ),
                    curriculum=curr,
                    curriculum_theme=curr_theme,
                    meta=meta,
                    description=description,
                    summary_html=summary_html,
                    resources=[r.model_dump(mode="json") for r in resources_file.resources],
                    assets_list=list(assets_by_id.values()),
                    cards_count=len(expanded_cards),
                    quiz_count=len(serialized_quiz),
                    theme_data=theme_data_payload,
                    theme_url=theme_rel_url,
                )
                (dest_theme_dir / "index.html").write_text(theme_html, encoding="utf-8")

                for lvl in meta.reperes_levels:
                    published_grades.add(lvl)
                    subject_grades.add(lvl)

                subject_themes.append(
                    {
                        "theme_slug": meta.theme_slug,
                        "title": meta.title,
                        "macro_theme_bo": curr_theme.macro_theme_bo,
                        "reperes_levels": list(meta.reperes_levels),
                        "description": description,
                        "url": theme_rel_url,
                        "cards_count": len(expanded_cards),
                        "quiz_count": len(serialized_quiz),
                        "concepts_count": len(meta.key_concepts),
                    }
                )
                search_entries.append(
                    {
                        "url": theme_rel_url,
                        "cycle": meta.cycle,
                        "subject": meta.subject,
                        "subject_label": curr.subject_label,
                        "title": meta.title,
                        "reperes_levels": list(meta.reperes_levels),
                        "concepts_text_normalized": _build_search_terms(
                            meta, curr.subject_label, summary_md, cards_file
                        ),
                    }
                )
                total_themes += 1

            # Générer la page matière si elle est déclarée dans curriculum/
            subj_url = f"/{curr.cycle}/{curr.subject}/"
            sorted_subj_grades = sorted(
                subject_grades or {lvl for th in curr.themes for lvl in th.reperes_levels},
                key=lambda g: GRADE_ORDER.get(g, 99),
            )
            subject_record = {
                "cycle": curr.cycle,
                "subject": curr.subject,
                "subject_code": curr.subject_code,
                "subject_label": curr.subject_label,
                "url": subj_url,
                "reperes_levels": sorted_subj_grades,
                "themes": subject_themes,
                "bo_sources": [b.model_dump(mode="json") for b in curr.bo_sources],
            }
            subjects_view.append(subject_record)

            dest_subj_dir = output_dir / curr.cycle / curr.subject
            dest_subj_dir.mkdir(parents=True, exist_ok=True)
            subj_html = jinja_env.get_template("subject.html").render(
                base_url=norm_base,
                repo_url=resolved_repo_url,
                build_sha=build_sha,
                available_grades=sorted(
                    published_grades | {"5eme"}, key=lambda g: GRADE_ORDER.get(g, 99)
                ),
                subject=subject_record,
            )
            (dest_subj_dir / "index.html").write_text(subj_html, encoding="utf-8")

    home_html = jinja_env.get_template("home.html").render(
        base_url=norm_base,
        repo_url=resolved_repo_url,
        build_sha=build_sha,
        available_grades=sorted(published_grades | {"5eme"}, key=lambda g: GRADE_ORDER.get(g, 99)),
        subjects=subjects_view,
        total_themes=total_themes,
    )
    (output_dir / "index.html").write_text(home_html, encoding="utf-8")

    (output_dir / "search-index.json").write_text(
        json.dumps(search_entries, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    return BuildSummary(
        output_dir=str(output_dir),
        base_url=norm_base,
        repo_url=resolved_repo_url,
        build_sha=build_sha,
        subjects_count=len(subjects_view),
        themes_count=total_themes,
        search_entries_count=len(search_entries),
    )
