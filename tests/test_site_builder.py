"""Tests unitaires et d'intégration du générateur de portail statique (`site_builder.py`)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from osarai.schemas import normalize_search_text
from osarai.site_builder import build_site, create_markdown_renderer, normalize_base_url
from osarai.yaml_io import dump_yaml_roundtrip

EXPECTED_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; img-src 'self'; connect-src 'self'; manifest-src 'self'; "
    "base-uri 'self'; form-action 'none'"
)

SUBRESOURCE_URL_RE = re.compile(r'<(?:script|link|img)\b[^>]*\b(?:src|href)="([^"]+)"')


def test_normalize_base_url_variants() -> None:
    assert normalize_base_url("") == ""
    assert normalize_base_url("/") == ""
    assert normalize_base_url("/osarai") == "/osarai"
    assert normalize_base_url("osarai/") == "/osarai"
    assert normalize_base_url("/college/osarai/") == "/college/osarai"


def test_markdown_renderer_preserves_latex_without_eq_tags_and_escapes_html() -> None:
    md = create_markdown_renderer()
    rendered = md.render(
        "Formule en ligne \\(\\text{CO}_2 < 5\\) et <script>x</script>\n\n"
        "\\[\n\\frac{a}{b}\n\\]\n\n"
        "\\[\nx = 1\n\\] (1)\n"
    )
    assert "<eq>" not in rendered
    assert "<eqn>" not in rendered
    assert r"\(\text{CO}_2 &lt; 5\)" in rendered
    assert r"\[" in rendered and r"\]" in rendered
    assert "<script>" not in rendered
    assert "(1)" in rendered


def test_build_site_empty_repo_and_root_slash_base_url(sample_repo: Path, tmp_path: Path) -> None:
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    shutil.copy2(sample_repo / "sources.yaml", empty_repo / "sources.yaml")

    dist_dir = tmp_path / "dist_empty"
    summary = build_site(empty_repo, dist_dir, base_url="/")

    assert summary.base_url == ""
    assert summary.themes_count == 0
    assert (dist_dir / "index.html").is_file()
    assert (dist_dir / "assets" / "vendor" / "katex" / "LICENSE").is_file()
    assert len(list((dist_dir / "assets" / "vendor" / "katex" / "fonts").glob("*.woff2"))) == 20

    index_html = (dist_dir / "index.html").read_text(encoding="utf-8")
    assert "//manifest.webmanifest" not in index_html
    assert 'href="/manifest.webmanifest"' in index_html
    assert json.loads((dist_dir / "search-index.json").read_text(encoding="utf-8")) == []


def test_build_site_full_theme_csp_cloze_tasl_and_search(sample_repo: Path, tmp_path: Path) -> None:
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"

    # Enrichir summary.md avec `cœur` et `œsophage` et meta.yaml avec un retired_id pour tout tester
    summary_path = theme_dir / "summary.md"
    summary_path.write_text(
        summary_path.read_text(encoding="utf-8")
        + "\nLe **cœur** propulse le sang tandis que l'**œsophage** appartient au tube digestif.\n",
        encoding="utf-8",
    )
    dump_yaml_roundtrip(
        theme_dir / "meta.yaml",
        lambda d: (
            d.__setitem__("last_card_seq", 21),
            d.__setitem__("retired_ids", ["c4-svt-la-respiration-c0021"]),
        ),
    )

    dist_dir = tmp_path / "dist_osarai"
    summary = build_site(
        sample_repo,
        dist_dir,
        base_url="/osarai",
        repo_url="https://github.com/Seburan/osarai",
    )
    assert summary.themes_count == 1
    assert summary.subjects_count == 1
    assert summary.base_url == "/osarai"

    # 1) Manifeste Web App préfixé par `/osarai/`
    manifest = json.loads((dist_dir / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["start_url"] == "/osarai/"
    assert manifest["scope"] == "/osarai/"
    assert manifest["lang"] == "fr"
    assert manifest["display"] == "standalone"

    # 2) Index de recherche sans double préfixe `/osarai` et recherche ligatures/accents
    search_index = json.loads((dist_dir / "search-index.json").read_text(encoding="utf-8"))
    assert len(search_index) == 1
    hit = search_index[0]
    assert hit["url"] == "/cycle-4/svt/la-respiration/"
    assert not hit["url"].startswith("/osarai")
    for query in ("coeur", "oesophage", "alveole"):
        q_norm = normalize_search_text(query)
        assert q_norm in hit["concepts_text_normalized"], f"{q_norm!r} absent de l'index"

    # 3) Page thème : CSP exacte, KaTeX local, zéro ressource externe, LaTeX, Cloze, TASL
    theme_html_path = dist_dir / "cycle-4" / "svt" / "la-respiration" / "index.html"
    assert theme_html_path.is_file()
    assert (
        dist_dir
        / "cycle-4"
        / "svt"
        / "la-respiration"
        / "assets"
        / "c4-svt-la-respiration--alveoles.webp"
    ).is_file()

    html_text = theme_html_path.read_text(encoding="utf-8")
    assert 'data-base-url="/osarai"' in html_text
    assert EXPECTED_CSP in html_text
    assert "/osarai/assets/vendor/katex/katex.min.js" in html_text
    assert "/osarai/assets/vendor/katex/contrib/auto-render.min.js" in html_text
    assert html_text.index("auto-render.min.js") < html_text.index("/osarai/assets/js/app.js")

    # Aucune sous-ressource (<script>, <link>, <img>) ne charge une URL http(s):// externe
    for sub_url in SUBRESOURCE_URL_RE.findall(html_text):
        assert not sub_url.startswith(("http://", "https://", "//")), sub_url

    # Préservation de \(...\) et \[...\] sans <eq>/<eqn> dans la Fiche de Synthèse
    assert "<eq>" not in html_text
    assert "<eqn>" not in html_text
    assert r"\(\text{O}_2\)" in html_text
    assert r"\frac{1}{2}" in html_text

    # 4ème onglet Ressources externes pré-rendu + pied de page TASL complet
    assert "https://www.lumni.fr/video/la-respiration-humaine" in html_text
    assert 'target="_blank" rel="noopener noreferrer"' in html_text
    assert "Respiration — Vikidia" in html_text
    assert "CC-BY-SA-3.0" in html_text
    assert "Wikimedia Contributor" in html_text

    # 4) Inspection de `#theme-data` : assets, retired_ids et dépliage Cloze 2 indices (#c1, #c2)
    match = re.search(
        r'<script type="application/json" id="theme-data">([\s\S]*?)</script>',
        html_text,
    )
    assert match is not None
    theme_data = json.loads(match.group(1))
    assert theme_data["retired_ids"] == ["c4-svt-la-respiration-c0021"]
    assert "alveoles" in theme_data["assets"]
    assert theme_data["assets"]["alveoles"]["width"] == 640

    cloze_items = [
        c for c in theme_data["flashcards"] if c["parent_id"] == "c4-svt-la-respiration-c0002"
    ]
    assert [c["item_id"] for c in cloze_items] == [
        "c4-svt-la-respiration-c0002#c1",
        "c4-svt-la-respiration-c0002#c2",
    ]
    assert cloze_items[0]["content_hash"] != cloze_items[1]["content_hash"]

    # Non-échappement de <span class="cloze-blank"> et <strong class="cloze-answer">
    c1_front = cloze_items[0]["front_html"]
    c1_back = cloze_items[0]["back_html"]
    assert '<span class="cloze-blank">[gaz]</span>' in c1_front
    assert "&lt;span" not in c1_front
    assert r"\(\text{CO}_2\)" in c1_front  # Le trou c2 non actif affiche sa réponse au recto de c1
    assert '<strong class="cloze-answer">du dioxygène</strong>' in c1_back

    c2_front = cloze_items[1]["front_html"]
    c2_back = cloze_items[1]["back_html"]
    assert "du dioxygène" in c2_front
    assert '<span class="cloze-blank">[formule]</span>' in c2_front
    assert r'<strong class="cloze-answer">\(\text{CO}_2\)</strong>' in c2_back

    # 5) Bascule de thème clair/sombre accessible sans script en ligne (conformité CSP)
    assert '<meta name="color-scheme" content="light dark">' in html_text
    assert "/osarai/assets/js/theme-init.js" in html_text
    assert (dist_dir / "assets" / "js" / "theme-init.js").is_file()
    assert 'id="btn-theme-toggle"' in html_text
    assert "Passer au thème sombre" in html_text
    assert "Passer au thème clair" in html_text


def test_build_site_search_index_does_not_truncate_keywords_on_long_themes(
    sample_repo: Path, tmp_path: Path
) -> None:
    """Vérifie que `œsophage` et `cæcum` restent indexés sur un thème riche en termes."""
    theme_dir = sample_repo / "content" / "cycle-4" / "svt" / "la-respiration"
    summary_path = theme_dir / "summary.md"
    padding = " ".join(
        f"**notion-{idx:02d}-anatomie-physiologie-cellulaire**" for idx in range(1, 25)
    )
    summary_path.write_text(
        summary_path.read_text(encoding="utf-8")
        + f"\n{padding}\n"
        + "Trajet : bouche, **œsophage**, estomac, intestin grêle, **cæcum** et côlon.\n",
        encoding="utf-8",
    )

    dist_dir = tmp_path / "dist_long_search"
    build_site(sample_repo, dist_dir, base_url="")

    search_index = json.loads((dist_dir / "search-index.json").read_text(encoding="utf-8"))
    hay = search_index[0]["concepts_text_normalized"]
    for query in ("œsophage", "oesophage", "cæcum", "caecum", "alvéole", "alveole"):
        assert normalize_search_text(query) in hay
