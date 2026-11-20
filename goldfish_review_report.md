# Goldfish Annotated Review Report — Phase 9, Passe 2 (Test de Prêt-à-Implémenter)

**Status:** resolved
**Target:** [docs/designs/osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L516-L723) (`516..723`, avec synchronisation de cohérence sur `§3.3`, `§4`, `§5.2` et `§6.3`)

## Prioritized Findings & AI Suggestions

### [IR2-01] Enveloppes YAML racines non figées (`FlashcardsFile`, `QuizFile`, `AssetsFile`, `ResourcesFile`) et littéraux/types incomplets sur `FeedbackItem` et `BackupPayload` [`egm-implementation-readiness`, `egm-codebase-details`] - Severity: Blocker
*   **Affected Scope:** [Lines 574-578](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L574-L578) (Item 11 `schemas.py`), Items 12–13 (`L579-L588`), Item 26 (`L653-L662`), Item 34 (`L706-L710`) et alignement `§3.3` (`L285-L302`)
*   **Discrepancy Description:** Contrairement à `sources.yaml`, `bo_manifest.yaml`, `curriculum/*.yaml` et `meta.yaml`, l'Item 11 ne fige ni `schema_version: Literal[1]` ni le nom exact de la clé liste racine dans `assets.yaml`, `flashcards.yaml`, `quiz.yaml` et `resources.yaml`. De même, les littéraux `Literal[...]` de `FeedbackItem` (`item_type`, `reason`, `status`) et la structure typée de `BackupPayload` (`progress` indexé par `"<cycle>:<subject>:<theme_slug>"`, `flags: list[FeedbackItem]`) ne sont pas arrêtés.
*   **Rationale:** Sans nom de clé racine explicite (`cards` vs `flashcards`, `questions` vs `quiz`), `schemas.py`, `id_manager.py`, `site_builder.py` et les compétences `SKILL.md` peuvent diverger dès l'écriture du code.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat valide relevant directement de la règle *Zero-Decision*. Figer `{schema_version: 1, assets: [...]}`, `{schema_version: 1, cards: [...]}`, `{schema_version: 1, questions: [...]}` et `{schema_version: 1, resources: [...]}` ainsi que tous les `Literal[...]` élimine toute ambiguïté de sérialisation.
*   ***Proposed Edit:***
    *   Location: Item 11 (`L574-L578`) et alignement `§3.3` (`L285, L290, L298, L301`).
    *   Change: Figer `AssetsFile` (`{schema_version: Literal[1], assets: list[AssetEntry]}`), `FlashcardsFile` (`{schema_version: Literal[1], cards: list[Flashcard]}`), `QuizFile` (`{schema_version: Literal[1], questions: list[QuizQuestion]}`), `ResourcesFile` (`{schema_version: Literal[1], resources: list[ResourceEntry]}`), `FeedbackItem` (`item_type: Literal["flashcard", "quiz"]`, `reason: Literal["erreur_factuelle", "hors_programme", "formulation_ambigue", "masque_decale", "coquille", "autre"]`, `status: Literal["open", "resolved", "retired"]`) et `BackupPayload` (`{schema: Literal["osarai-backup-v1"], exported_at: datetime, grade: GradeLevel, progress: dict[str, ThemeProgress], flags: list[FeedbackItem]}`).

---

### [IR2-02] Échappement des balises Cloze par `markdown-it-py(html=False)`, omission du dictionnaire `assets` dans `#theme-data` et absence du 4ème onglet `resources.yaml` au build HTML [`egm-implementation-readiness`, `egm-codebase-details`] - Severity: Blocker
*   **Affected Scope:** [Lines 638-662](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L638-L662) (Items 23 à 26) et alignement `L363`
*   **Discrepancy Description:** (1) Injecter `<span class="cloze-blank">` et `<strong class="cloze-answer">` sur la chaîne brute *avant* `markdown-it-py(html=False)` fait échapper ces balises en `&lt;span ...&gt;` ; en outre, la 3ème règle `math_block_eqno` de `texmath` émet `<eqn>` si elle n'est pas surchargée. (2) `#theme-data` omet le dictionnaire `assets` (`filename`, `width`, `height` et crédits `TASL`) ainsi que les champs `*_html` pré-rendus et les chemins exacts dans `dist/`. (3) Ni `site_builder.py` ni `theme.html` ne décrivent le pré-rendu du 4ème onglet `resources.yaml`.
*   **Rationale:** Ces trois écarts cassent l'affichage des trous Cloze, le ratio `aspect-ratio: var(--asset-w) / var(--asset-h)` des masques d'occultation, le `<details>` de crédit *TASL* et l'onglet *Ressources externes*.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat technique vérifié sur le comportement de `markdown-it-py` (`html=False`) et `mdit-py-plugins.texmath`.
*   ***Proposed Edit:***
    *   Location: Items 23, 24, 26 (`L638-L662`) et `L363`.
    *   Change: Préciser dans `site_builder.py` le découpage autour des jetons `{{cN::réponse::indice}}`, le passage séparé de chaque segment dans `renderInline` (`html=False`) avant encapsulation `<span class="cloze-blank">` / `<strong class="cloze-answer">`, la surcharge conjointe de `math_inline`, `math_block` et `math_block_eqno`, l'inclusion de `assets: dict[str, AssetEntry]` et des champs pré-rendus (`item_id`, `parent_id`, `content_hash`, `front_html`, `back_html`, `explanation_html`, `question_html`, `choices_html`) dans `#theme-data`, les chemins de sortie `dist/assets/{css,js,vendor}/` et `dist/<cycle>/<matiere>/<theme_slug>/assets/`, ainsi que le pré-rendu statique de `resources.yaml` dans le 4ème onglet de `theme.html` (`target="_blank" rel="noopener noreferrer"`).

---

### [IR2-03] Contrat d'API MediaWiki invalide dans `grounding_fetcher.py` (`prop=info` sans licence et `prop=extracts` sans paramètre `section`) [`egm-codebase-details`] - Severity: Blocker
*   **Affected Scope:** [Lines 606-609](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L606-L609) (Item 17 `grounding_fetcher.py`)
*   **Discrepancy Description:** Dans MediaWiki Action API, `prop=info` ne renvoie pas la licence du wiki (il faut `meta=siteinfo&siprop=rightsinfo` pour distinguer `CC-BY-SA-3.0` sur *Vikidia FR* de `CC-BY-SA-4.0` sur *Wikipédia FR*), et `prop=extracts` ignore tout paramètre `section` en renvoyant l'article entier.
*   **Rationale:** Sans `meta=siteinfo&siprop=rightsinfo` et découpage explicite des sections `== ... ==`, la résolution de licence échoue et l'article complet de Wikipédia FR entre dans le contexte malgré `--section`.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Vérifié contre le contrat de l'API MediaWiki (`TextExtracts` et `siteinfo`).
*   ***Proposed Edit:***
    *   Location: Item 17 (`L606-L609`).
    *   Change: Spécifier l'appel `action=query&prop=extracts|revisions&meta=siteinfo&siprop=rightsinfo&explaintext=1&exsectionformat=wiki&rvprop=ids|timestamp` avec résolution de `license_spdx`/`license_url` depuis `query.rightsinfo` et découpage côté Python de la section `== <section> ==` demandée (`ExitCode.UPSTREAM_NOT_FOUND = 5` si absente).

---

### [IR2-04] Incompatibilité `hatchling>=1.25` avec `license = "Apache-2.0"` (PEP 639) et inclusion involontaire de `LICENSE-CONTENT` dans la wheel Python [`egm-codebase-details`] - Severity: Major
*   **Affected Scope:** [Lines 554-558](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L554-L558) (Item 7 `pyproject.toml`)
*   **Discrepancy Description:** `hatchling 1.25.x` rejette une chaîne SPDX sur `project.license` (le support PEP 639 requiert `hatchling>=1.27`), et le motif par défaut `LICEN[CS]E*` inclut `LICENSE-CONTENT` (`CC BY-SA 4.0`) dans les métadonnées de la wheel Python `Apache-2.0` sans `license-files = ["LICENSE"]`.
*   **Rationale:** Garantir le succès de `uv sync` dès le premier essai et la séparation stricte des licences dans le paquet Python compilé.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat exact sur PEP 639 dans `hatchling`.
*   ***Proposed Edit:***
    *   Location: Item 7 (`L557`).
    *   Change: Remplacer `hatchling>=1.25` par `hatchling>=1.27` et ajouter `license-files = ["LICENSE"]` dans `[project]`.

---

### [IR2-05] Numéros de ligne YAML, typage optionnel d'`id` avant `assign-ids`, `ValidationInfo.context` pour `--allow-empty-resources`, extraction Markdown de `validate --feedback` et contrôles croisés de `validator.py` [`egm-implementation-readiness`, `egm-codebase-details`] - Severity: Major
*   **Affected Scope:** [Lines 569-588](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L569-L588) (Items 10 à 13) et Item 31 (`L688-L692`)
*   **Discrepancy Description:** (1) `YAML(typ="safe")` ne conserve pas `.lc.line` pour les diagnostics par ligne de `validator.py`, `YAML(typ="rt")` doit activer `preserve_quotes=True`, et `compute_content_hash` doit opérer sur `model_dump(mode="json")`. (2) `Flashcard.id` et `QuizQuestion.id` doivent accepter `str | None = None` au parsing initial, et `ResourcesFile` doit consulter `ValidationInfo.context` pour `--allow-empty-resources`. (3) `validate_feedback_file` doit accepter un JSON brut ou un bloc ```` ```osarai-feedback-v1 ... ``` ````. (4) `validator.py` doit rappeler explicitement les contrôles hors-ligne sur `sources.yaml`, le nommage plat, les dimensions `width`/`height` et fichiers orphelins `assets/`, la syntaxe LaTeX/HTML et l'absence de `# ` dans `summary.md`, ainsi que la cohérence `meta.yaml` ↔ `curriculum/` et `reperes_level`.
*   **Rationale:** Assurer la cohérence bout-en-bout entre `yaml_io.py`, `schemas.py`, `id_manager.py`, `validator.py` et `fix-flagged-cards`.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat valide éliminant plusieurs cas d'échec d'intégration au Jalon 1.
*   ***Proposed Edit:***
    *   Location: Items 10, 11, 13 (`L569-L588`).
    *   Change: Ajouter `load_yaml_with_lines` (`YAML(typ="rt")` en lecture) et `preserve_quotes=True` + normalisation `model_dump(mode="json")` dans `yaml_io.py` ; typer `id: str | None = None` et `ValidationInfo.context` dans `schemas.py` ; préciser dans `validator.py` l'extraction des blocs Markdown ```` ```osarai-feedback-v1 ```` et la liste complète des contrôles croisés hors-ligne.

---

### [IR2-06] Comparaison Git sur `merge-base(git_ref, HEAD)`, définition exacte de la non-réattribution d'`id` et exécution à vide aux Jalons 1 à 3 [`egm-implementation-readiness`, `egm-codebase-details`] - Severity: Major
*   **Affected Scope:** [Line 518](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L518), Items 12–13 (`L579-L588`), Item 20 (`L621-L625`) et Item 23 (`L638-L642`)
*   **Discrepancy Description:** Comparer l'arbre courant directement à `origin/main` au lieu de `git merge-base <git_ref> HEAD` produit de faux positifs dès que `main` avance ; `check_immutable_ids_against_git` doit définir la mutation interdite (`Flashcard.type` `basic` ↔ `cloze` ou réutilisation d'un `retired_id`) et tolérer un `git_ref` sans `content/` ; enfin, aux Jalons 1 à 3 où `curriculum/` et `content/` sont absents, `validator.py` et `site_builder.py` doivent s'exécuter sans `FileNotFoundError`.
*   **Rationale:** Permettre aux tests et à `build-site` de passer réellement dès le Jalon 3 et éviter les faux positifs sur les Pull Requests.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat valide.
*   ***Proposed Edit:***
    *   Location: Items 12, 13, 20 et 23.
    *   Change: Prescrire la résolution préalable de `git merge-base <git_ref> HEAD`, définir la mutation interdite sur un `id` conservé (`type` `basic` ↔ `cloze` ou présence dans `retired_ids`), et spécifier qu'en l'absence de `curriculum/` ou `content/` aux Jalons 1 à 3, `validator.py` et `site_builder.py` retournent un résultat/site vide valide.

---

### [IR2-07] Séquence d'initialisation d'un thème neuf dans `author-theme`, cycle de vie de `hitl_verified` / `bo_manifest.sha256`, option `--domain` et `--json` par sous-commande [`egm-implementation-readiness`, `egm-codebase-details`] - Severity: Major
*   **Affected Scope:** [Lines 589-630](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L589-L630) (Items 14, 16, 17, 18, 21), Item 30 (`L680-L686`) et alignement `L317`, `L334-L338`
*   **Discrepancy Description:** Sur un nouveau thème, exécuter `fetch-grounding --theme` et `fetch-commons --theme` échoue si le squelette de `meta.yaml` et `assets.yaml` n'est pas initialisé au préalable ; le cycle `hitl_verified` (`false` à l'import, `true` après contrôle HITL, rejeté si `false` par `validate`) et `BoDocumentEntry.sha256: str | None = None` avant le premier `sync-bo` (`<idx:02d>-<doc_slug>.md`) ne sont pas précisés ; `fetch-grounding` omet `--domain` optionnel, `USER_AGENT` partagé n'est pas fixé, `--json` doit être accepté sur chaque sous-commande, et `probe-links --url` (répétable) doit fixer son code retour.
*   **Rationale:** Aligner les signatures Python, les options CLI et l'ordre opératoire des compétences IA.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat valide.
*   ***Proposed Edit:***
    *   Location: Items 9, 11, 14, 16, 17, 18, 21, 30 et `L317`, `L334-L338`.
    *   Change: Exposer `USER_AGENT = "Osarai/0.1.0 (+https://github.com/Seburan/osarai)"` dans `__init__.py` ; autoriser `BoDocumentEntry.sha256: str | None = None` au parsing initial (`validate` exigeant une valeur non nulle) et nommer `<idx:02d>-<doc_slug>.md` ; créer le squelette `meta.yaml` + `assets.yaml` dès l'étape 1 d'`author-theme` ; écrire `hitl_verified: false` dans `fetch-commons` puis passer à `true` après revue HITL (`validate` exigeant `true`) ; ajouter `--domain` optionnel à `fetch-grounding`, accepter `--json` sur chaque sous-commande et typer `--url: list[str]` sur `probe-links` (code `0` avec statut par URL).

---

### [IR2-08] Règles Soft-404, sondage YouTube exclusivement via `oEmbed` (contre `consent.youtube.com`), périmètre de `sources.yaml` pour `resources.yaml` et exécution de `link-rot.yml` / `deploy.yml` [`egm-implementation-readiness`, `egm-codebase-details`] - Severity: Major
*   **Affected Scope:** [Lines 621-625](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L621-L625) (Item 20 `url_checker.py`) et [Lines 693-700](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L693-L700) (Item 32 workflows)
*   **Discrepancy Description:** (1) Critères Soft-404 non énumérés. (2) Un `GET` sur `youtube.com/watch` redirige vers `consent.youtube.com` hors liste : YouTube doit passer uniquement par `youtube.com/oembed` après purge de `?si=`/`feature=`. (3) `resources.yaml` doit accepter `outbound_only_sources` union `allow_grounding: true` (avec sous-domaines `*.<domain>`). (4) `link-rot.yml` s'arrête avant `gh issue` sans `continue-on-error: true`, omet le schéma de `link-report.json`, la fermeture automatique de l'Issue et `checkout`/`setup-uv` ; `deploy.yml` omet `checkout`, `setup-uv` et `environment: github-pages`.
*   **Rationale:** Éviter les échecs systématiques de `probe-links` sur YouTube et des workflows GitHub Actions `deploy.yml` / `link-rot.yml`.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat opérationnel vérifié sur YouTube EU et GitHub Actions.
*   ***Proposed Edit:***
    *   Location: Items 11, 20 et 32.
    *   Change: Figer les motifs Soft-404 (`<title>` vide ou `"404"`, `"page introuvable"`, `"page non trouvée"`, `"not found"`, `"erreur 404"` dans `<title>`/`<h1>`, ou redirection profonde vers `/`), le contrôle YouTube exclusivement via `oEmbed` après extraction de l'ID 11 car., l'acceptation de `outbound_only_sources ∪ {allow_grounding: true}` (et `*.<domain>`) dans `resources.yaml`, le schéma `link-report.json`, `continue-on-error: true` + clôture automatique dans `link-rot.yml`, et `checkout@v4` + `setup-uv@v5` + `environment: github-pages` dans `deploy.yml`.

---

### [IR2-09] Erreurs `HTTP 404` lors du test local après `--base-url /osarai`, normalisation de `base_url`, fond clair des schémas en mode sombre et contrats `home.html`/`subject.html`/`manifest.webmanifest` [`egm-codebase-details`, `egm-implementation-readiness`] - Severity: Major
*   **Affected Scope:** [Lines 638-667](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L638-L667) (Items 23–27) et [Lines 713-717](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L713-L717) (`Plan de Vérification`)
*   **Discrepancy Description:** Servir `dist/` compilé avec `--base-url /osarai` via `http.server -d dist 8000` provoque des `404` sur `/osarai/...` ; `--base-url /` génère `//manifest.webmanifest` bloqué par CSP sans normalisation ; `search-index.json` doit stocker `url` sans `base_url` ; KaTeX UMD doit être chargé par `<script defer>` avant les ES Modules ; les schémas SVG transparents exigent un fond clair sur leur conteneur en mode sombre ; et `home.html`, `subject.html` et `manifest.webmanifest` doivent préciser leurs clés/attributs.
*   **Rationale:** Empêcher un échec immédiat lors de la vérification locale, en mode sombre ou sous `Content-Security-Policy`.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat valide.
*   ***Proposed Edit:***
    *   Location: Items 23, 24, 25, 26 et `L717`.
    *   Change: Normaliser `base_url` (`""` si `""` ou `"/"`, sinon `"/" + base_url.strip("/")`), stocker `url` sans `base_url` dans `search-index.json`, figer les clés de `manifest.webmanifest` (`display: "standalone"`), préciser `data-reperes-levels` dans `home.html`/`subject.html` et `<script defer>` pour KaTeX UMD avant `<script type="module">`, imposer un fond clair `#ffffff` sur le conteneur d'illustration en mode sombre, et recompiler avec `--base-url ""` avant `http.server -d dist 8000` en `L717`.

---

### [IR2-10] Infrastructure de test dans `tests/conftest.py` (`git config` sur runner CI vierge et exécution des coroutines `async`) [`egm-codebase-details`] - Severity: Major
*   **Affected Scope:** [Lines 594-598](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L594-L598) (Item 15) et [Lines 631-635](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L631-L635) (Item 22)
*   **Discrepancy Description:** `git commit` dans `tmp_path` échoue sur un runner GitHub Actions vierge sans `git config user.name` et `user.email` locaux dans `conftest.py` ; et les fonctions `async def` de `url_checker.py` doivent préciser l'usage d'`asyncio.run(...)` sous `@respx.mock` puisque `pytest-asyncio` n'est pas installé.
*   **Rationale:** Garantir une exécution déterministe des tests sur tout poste local comme sur un runner CI vierge.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat classique et vérifié sur `ubuntu-latest` dans GitHub Actions.
*   ***Proposed Edit:***
    *   Location: Items 15 et 22.
    *   Change: Détailler dans `conftest.py` la configuration locale `git config user.name` / `user.email`, les fixtures de thème valide (20 cartes, 10 QCM, WebP valide, PDF tabulaire minimal) et prescrire `asyncio.run(...)` sous `@respx.mock` dans `test_network_and_media_helpers.py`.

---

### [IR2-11] Calibration éditoriale de la portée d'`osarai validate` en introduction (`L518`) et de la description de `.gitignore` (`L547`) [`egm-style`, `egm-codebase-details`] - Severity: Major
*   **Affected Scope:** [Line 518](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L518) et [Lines 544-547](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L544-L547) (Item 5)
*   **Discrepancy Description:** `L518` laisse entendre qu'`osarai validate` contrôle les chartes juridiques et `SKILL.md` et répète *« livré à ce stade »* ; `L547` énumère 11 règles de `.gitignore` comme une liste exhaustive et omet la mise à jour des commentaires d'en-tête obsolètes (`Clés API Gemini`, `& Cache IA`).
*   **Rationale:** Aligner les affirmations sur le périmètre exact d'`osarai validate` et du fichier `.gitignore` réel.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Constat valide (`CALIBRATE`).
*   ***Proposed Edit:***
    *   Location: Ligne `518` et Item 5 (`L547`).
    *   Change: Restreindre `osarai validate` dans `L518` aux fichiers `sources.yaml`, `bo_manifest.yaml`, `curriculum/` et `content/` (les chartes juridiques et `SKILL.md` relevant de la relecture humaine HITL lors de leur jalon) sans *« livré à ce stade »* ; reformuler `L547` pour inclure le nettoyage des commentaires d'en-tête obsolètes tout en conservant l'ensemble des autres règles existantes de `.gitignore`.

---

### [IR2-12] Sens du test d'anti-divulgation `badge`, indices Cloze contigus `1..K`, paramètres WebP `Pillow` et précisions sur `README.md` [`egm-implementation-readiness`, `egm-codebase-details`] - Severity: Nit
*   **Affected Scope:** Items 6 (`L552`), 11 (`L577`) et 18 (`L614`)
*   **Discrepancy Description:** Préciser `len(answer_norm) > 0 and answer_norm in badge_norm` et les indices Cloze distincts contigus `1..K` dans `schemas.py`, les paramètres `Pillow` WebP (`quality=85, method=6`, paliers `75, 65`) dans `commons_fetcher.py`, ainsi que le retrait des mentions `*(À venir)*` et le cadrage des matières pilotes (*SVT* et *Histoire-Géographie*) dans `README.md`.
*   **Rationale:** Lever les micro-décisions d'implémentation restantes.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Précisions courtes directement utiles au codeur.
*   ***Proposed Edit:***
    *   Location: Items 6, 11 et 18.
    *   Change: Ajouter ces quatre précisions dans les Items 6, 11 et 18.

---

### [IR2-13] Phrases-fleuves à participes présents (`L604`, `L609`, `L619`, `L624`, `L634`, `L641`) et redondances internes dans `author-theme` (`L685`) [`egm-style`] - Severity: Nit
*   **Affected Scope:** Lignes `604`, `609`, `619`, `624`, `634`, `641` et `685`
*   **Discrepancy Description:** Phrases de 110 à 218 mots accumulant les participes présents et répétitions dans `L624` et `L685`.
*   **Rationale:** Améliorer la lisibilité directe des consignes d'implémentation.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Scinder ces blocs en phrases courtes à verbes conjugués ou sous-puces clarifie le plan.
*   ***Proposed Edit:***
    *   Location: Items 16, 17, 19, 20, 22, 23 et 30.
    *   Change: Structurer les descriptions longues en phrases courtes à l'indicatif ou sous-puces et retirer les doublons de `L624` et `L685`.

---

### [IR2-14] Uniformisation de « section 5 » (`LICENSE`), « liste blanche initiale », « commande `osarai` » et « échec définitif » [`egm-style`] - Severity: Nit
*   **Affected Scope:** Lignes `527`, `537`, `542`, `562`, `592`, `699` et `709`
*   **Discrepancy Description:** Hésitations lexicales mineures relevées par `egm-style`.
*   **Rationale:** Homogénéiser le vocabulaire juridique et technique avec `LICENSE` et `1..515`.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Corrections lexicales immédiates.
*   ***Proposed Edit:***
    *   Location: Items 1, 3, 4, 8, 14, 32 et 34.
    *   Change: Employer « dès le premier jour », « section 5 », « est soumise à la licence `CC BY-SA 4.0` », « liste blanche initiale », « commande `osarai` », « échec définitif » et « 18 fichiers sources (6 par thème) ».

---

### [IR2-15] Uniformisation des flèches Unicode `→` hors code et reformulations dans le `Plan de Vérification` [`egm-style`] - Severity: Nit
*   **Affected Scope:** Lignes `552`, `597`, `634`, `661`, `713` et `714`
*   **Discrepancy Description:** Usage de `$\rightarrow$` en prose, doublon « Compilation et Build Statique » (`L713`), et « exécutant `tests/conftest.py` ... les mocks HTTP » (`L714`).
*   **Rationale:** Uniformiser la typographie des flèches et la précision du `Plan de Vérification`.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Corrections typographiques rapides.
*   ***Proposed Edit:***
    *   Location: Items 6, 15, 22, 26 et `Plan de Vérification` (`L713-L714`).
    *   Change: Remplacer `$\rightarrow$` par `→` hors code, intituler `L713` « Validation et compilation statique » et écrire « appuyé sur les fixtures de `tests/conftest.py` ... les simulations HTTP » en `L714`.
