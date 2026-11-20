# Rapport de Prêt-à-Implémenter — Phase 9, Passe 2 (`implementation_readiness_report.md`)

**Cible auditée** : [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L516-L723) (`DetailedRange` : lignes `516..723`, vérifié en cohérence avec `FeatureRange` `1..515` et l'état réel du dépôt)
**Standards appliqués** :
* `egm-implementation-readiness` : `implementation-readiness-standard.md` (*Zero-Decision Rule*, jalonnement exécutable/testable, frontières exactes de fichiers)
* `egm-codebase-details` : `implementation-readiness-standard.md` (exactitude vis-à-vis du dépôt existant, API tierces, infrastructure de test)
* `egm-style` : vecteurs d'audit éditorial et calibration des affirmations (`DROP | CALIBRATE | RELOCATE`)
**Contexte Goldfish fourni** : [LICENSE](file:///Users/seburan/Development/osarai/LICENSE) (`Apache-2.0`)

## Statut des Auditeurs (Passe 2 — Ré-audit de vérification)

| Auditeur | Statut | Bilan brut (Passe 1 → Passe 2) |
| :--- | :--- | :--- |
| `egm-implementation-readiness` | `completed` | `4 B / 4 M / 1 N` → **`2` Blockers, `5` Majors, `3` Nits** |
| `egm-codebase-details` | `completed` | `8 B / 3 M / 0 N` → **`2` Blockers, `7` Majors, `3` Nits** |
| `egm-style` | `completed` | `0 B / 4 M / 5 N` → **`0` Blocker, `2` Majors, `6` Nits** |

**Synthèse consolidée et dédupliquée (Passe 2)** : **`3` Blockers**, **`8` Majors**, **`4` Nits** (`15` observations consolidées ; l'ensemble des 17 écarts de la Passe 1 est confirmé résolu).

---

## Observations Priorisées (Blockers → Majors → Nits)

### 🔴 Blockers

#### IR2-01 — Enveloppes YAML racines non figées (`FlashcardsFile`, `QuizFile`, `AssetsFile`, `ResourcesFile`) et littéraux/types incomplets sur `FeedbackItem` et `BackupPayload` — Severity: `Blocker`
* **Identifiants sources** : `ir-2-1`, `cd-2-12c`
* **Reviewer Lens** : `egm-implementation-readiness`, `egm-codebase-details`
* **Affected Scope** : Item 11 (`src/osarai/schemas.py`, [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L574-L578)), Items 12–13 (`L579–L588`), Item 26 (`L653–L662`) et Item 34 (`L706–L710`).
* **Discrepancy Description** : Contrairement à `sources.yaml`, `bo_manifest.yaml`, `curriculum/*.yaml` et `meta.yaml`, l'Item 11 ne fige ni la présence de `schema_version: Literal[1]` ni le nom exact de la clé liste racine dans `assets.yaml` (`assets:`), `flashcards.yaml` (`cards:` vs `flashcards:`), `quiz.yaml` (`questions:` vs `quiz:`) et `resources.yaml` (`resources:`). De même, les `Literal[...]` exacts de `FeedbackItem` (`item_type`, `reason`, `status`) ainsi que les types exacts des champs de `BackupPayload` (`progress` indexé par `"<cycle>:<subject>:<theme_slug>"`, `flags: list[FeedbackItem]`) ne sont pas arrêtés.
* **Rationale & Recommendation** : Figer dans `schemas.py` (et `§3.3`) les enveloppes `{schema_version: 1, assets: [...]}`, `{schema_version: 1, cards: [...]}`, `{schema_version: 1, questions: [...]}` et `{schema_version: 1, resources: [...]}`, ainsi que les `Literal[...]` de `FeedbackItem` et la structure exacte de `BackupPayload`.

---

#### IR2-02 — Échappement des balises Cloze par `markdown-it-py(html=False)`, omission du dictionnaire `assets` dans `#theme-data` et absence du 4ème onglet `resources.yaml` au build HTML — Severity: `Blocker`
* **Identifiants sources** : `ir-2-2`, `cd-2-2`, `cd-2-8d`
* **Reviewer Lens** : `egm-implementation-readiness`, `egm-codebase-details`
* **Affected Scope** : Items 23 à 26 ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L638-L662)).
* **Discrepancy Description** :
  1. **Échappement HTML des balises Cloze et règle `math_block_eqno` (`L641`)** : injecter `<span class="cloze-blank">` et `<strong class="cloze-answer">` sur le texte brut *avant* d'exécuter `markdown-it-py` configuré avec `html=False` fait échapper ces balises en `&lt;span ...&gt;`. En outre, `texmath_plugin(..., delimiters="brackets")` enregistre une troisième règle `math_block_eqno` qui émet `<eqn>` si elle n'est pas également surchargée.
  2. **Omission de `assets` dans `#theme-data` (`L641`, `L659–L660`)** : `#theme-data` ne contient pas les entrées `assets.yaml` (`filename`, `width`, `height` et crédits `TASL`), alors que `Flashcard` et `QuizQuestion` ne portent que `asset_id`, empêchant `quiz.js` et `flashcards.js` de calculer `--asset-w` / `--asset-h` et d'afficher le `<details>` de crédit *TASL*.
  3. **Omission du 4ème onglet `resources.yaml` (`L641`, `L646`)** : ni `site_builder.py` ni `theme.html` ne mentionnent le chargement et le pré-rendu HTML statique de `resources.yaml` dans le 4ème onglet accessible (*Fiche de Synthèse*, *Cartes mémoire*, *Quiz QCM*, *Ressources externes*).
* **Rationale & Recommendation** : Découper d'abord la chaîne Cloze autour des jetons `{{cN::réponse::indice}}`, rendre chaque segment séparément via `renderInline` (`html=False`), puis encapsuler dans `<span class="cloze-blank">` / `<strong class="cloze-answer">` ; surcharger aussi `math_block_eqno` ; inclure `assets: dict[str, AssetEntry]` et les champs `*_html` dans `#theme-data` (ainsi que les chemins de sortie dans `dist/`) ; et pré-rendre `resources.yaml` dans `theme.html` (`target="_blank" rel="noopener noreferrer"`).

---

#### IR2-03 — Contrat d'API MediaWiki invalide dans `grounding_fetcher.py` (`prop=info` sans licence et `prop=extracts` sans paramètre `section`) — Severity: `Blocker`
* **Identifiants sources** : `cd-2-1`
* **Reviewer Lens** : `egm-codebase-details`
* **Affected Scope** : Item 17 (`src/osarai/grounding_fetcher.py`, [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L606-L609)).
* **Discrepancy Description** : Dans l'API MediaWiki réelle, `prop=info` ne renvoie aucune métadonnée de licence (il faut ajouter `meta=siteinfo&siprop=rightsinfo` pour distinguer `CC-BY-SA-3.0` sur *Vikidia FR* de `CC-BY-SA-4.0` sur *Wikipédia FR*), et `prop=extracts` n'accepte aucun paramètre `section` (il émet un avertissement et renvoie tout l'article, neutralisant le filtrage hors-programme sur Wikipédia FR).
* **Rationale & Recommendation** : Spécifier `action=query&prop=extracts|revisions&meta=siteinfo&siprop=rightsinfo&explaintext=1&exsectionformat=wiki&rvprop=ids|timestamp` avec extraction côté Python de la sous-section `== <section> ==` demandée (et code `ExitCode.UPSTREAM_NOT_FOUND = 5` si la section est introuvable).

---

### 🟡 Majors

#### IR2-04 — Incompatibilité `hatchling>=1.25` avec `license = "Apache-2.0"` (PEP 639) et inclusion involontaire de `LICENSE-CONTENT` dans la wheel Python — Severity: `Major`
* **Identifiants sources** : `cd-2-7`
* **Reviewer Lens** : `egm-codebase-details`
* **Affected Scope** : Item 7 (`pyproject.toml`, [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L554-L558)).
* **Discrepancy Description** : `hatchling 1.25.x` rejette une chaîne SPDX sur `project.license` (le support PEP 639 requiert `hatchling>=1.27`), et le motif par défaut `LICEN[CS]E*` embarque `LICENSE-CONTENT` (`CC BY-SA 4.0`) dans les métadonnées de la wheel Python `osarai` (`Apache-2.0`) si `license-files = ["LICENSE"]` n'est pas fixé.
* **Rationale & Recommendation** : Exiger `hatchling>=1.27` et définir `license-files = ["LICENSE"]` dans `[project]`.

---

#### IR2-05 — Numéros de ligne YAML, typage optionnel d'`id` avant `assign-ids`, `ValidationInfo.context` pour `--allow-empty-resources`, extraction Markdown de `validate --feedback` et contrôles croisés de `validator.py` — Severity: `Major`
* **Identifiants sources** : `ir-2-3`, `ir-2-4`, `cd-2-5`, `cd-2-12b`
* **Reviewer Lens** : `egm-implementation-readiness`, `egm-codebase-details`
* **Affected Scope** : Items 10 à 13 ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L569-L588)) et Item 31 (`L688–L692`).
* **Discrepancy Description** : (1) `YAML(typ="safe")` ne conserve pas `.lc.line` requis pour les diagnostics par ligne de `validator.py`, et `YAML(typ="rt")` doit activer `preserve_quotes=True` ; `compute_content_hash` doit opérer sur la sortie `model_dump(mode="json")` du modèle validé (`float` sur `occlusions`, `[]` par défaut). (2) `Flashcard.id` et `QuizQuestion.id` doivent accepter `str | None = None` dans `schemas.py` (rejetés ensuite par `validator.py` avec calcul de l'`id` et du `last_*_seq` attendus), et `ResourcesFile` doit lire `ValidationInfo.context` pour autoriser `0` entrée sous `--allow-empty-resources`. (3) `validate_feedback_file` doit accepter un JSON brut ou extraire un bloc ```` ```osarai-feedback-v1 ... ``` ```` d'un fichier Markdown/texte. (4) `validator.py` omet de rappeler le contrôle hors-ligne `sources.yaml` (`allowed_licenses`, `allow_grounding`, `allowed_youtube_channel_urls`), la vérification du nommage plat, des dimensions réelles `width`/`height` et des fichiers orphelins `assets/`, le contrôle LaTeX/HTML et l'absence de `# ` (`<h1>`) dans `summary.md`, ainsi que la cohérence `meta.yaml` ↔ `curriculum/` et `item.reperes_level == concept.reperes_level`.
* **Rationale & Recommendation** : Compléter les Items 10, 11 et 13 avec ces règles exactes.

---

#### IR2-06 — Comparaison Git sur `merge-base(git_ref, HEAD)`, définition exacte de la non-réattribution d'`id` et exécution à vide aux Jalons 1 à 3 — Severity: `Major`
* **Identifiants sources** : `ir-2-5`, `cd-2-8c,e`
* **Reviewer Lens** : `egm-implementation-readiness`, `egm-codebase-details`
* **Affected Scope** : Ligne `518`, Item 12 (`L579–L583`), Item 13 (`L584–L588`), Item 20 (`L621–L625`) et Item 23 (`L638–L642`).
* **Discrepancy Description** : Comparer directement à `origin/main` au lieu de `git merge-base <git_ref> HEAD` fausse la détection de suppression dès que `main` avance en parallèle ; `check_immutable_ids_against_git` ne précise pas qu'éditer le texte d'un item existant est permis tant que son type (`basic` vs `cloze`) ne change pas (et doit tolérer une référence `git_ref` sans `content/`) ; enfin, aux Jalons 1 à 3 où `curriculum/` et `content/` n'existent pas encore, `validator.py` et `site_builder.py` doivent générer un rapport/site vide valide sans lever `FileNotFoundError`.
* **Rationale & Recommendation** : Prescrire `merge-base(git_ref, HEAD)`, définir la mutation interdite (`type` `basic` ↔ `cloze` ou réutilisation d'un `retired_id`), et gérer l'absence initiale de `curriculum/` et `content/`.

---

#### IR2-07 — Séquence d'initialisation d'un thème neuf dans `author-theme`, cycle de vie de `hitl_verified` / `bo_manifest.sha256`, option `--domain` et `--json` par sous-commande — Severity: `Major`
* **Identifiants sources** : `ir-2-7`, `cd-2-3`, `cd-2-8a`, `cd-2-12a`
* **Reviewer Lens** : `egm-implementation-readiness`, `egm-codebase-details`
* **Affected Scope** : Items 14, 16, 17, 18, 21 et 30 ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L589-L630), `L680–L686`).
* **Discrepancy Description** : Sur un nouveau thème, appeler `fetch-grounding --theme` et `fetch-commons --theme` avant que `meta.yaml` et `assets.yaml` n'existent échoue si l'ordre d'initialisation n'est pas fixé ; le passage de `hitl_verified` (`false` à l'import `fetch-commons`, `true` après contrôle HITL, rejeté si `false` par `validate`) et `BoDocumentEntry.sha256: str | None = None` avant le premier `sync-bo` (avec nommage `<idx:02d>-<slug>.md`) ne sont pas précisés ; `fetch-grounding` omet `--domain` optionnel (par défaut tous les domaines `mediawiki_text`), la constante partagée `USER_AGENT` n'est pas fixée, `--json` doit être accepté sur chaque sous-commande, et `probe-links --url` (répétable) doit préciser son code retour sur lot mixte.
* **Rationale & Recommendation** : Créer le squelette initial `meta.yaml` + `assets.yaml` dès le début de la Phase 1 d'`author-theme`, figer le cycle `hitl_verified` et `sha256`, partager `USER_AGENT`, exposer `--domain` optionnel et accepter `--json` sur chaque sous-commande.

---

#### IR2-08 — Règles Soft-404, sondage YouTube exclusivement via `oEmbed` (contre `consent.youtube.com`), périmètre de `sources.yaml` pour `resources.yaml` et exécution de `link-rot.yml` / `deploy.yml` — Severity: `Major`
* **Identifiants sources** : `ir-2-6`, `cd-2-6`, `cd-2-8b`, `ir-2-10a`
* **Reviewer Lens** : `egm-implementation-readiness`, `egm-codebase-details`
* **Affected Scope** : Item 8 (`L559–L563`), Item 20 (`L621–L625`) et Item 32 (`L693–L700`).
* **Discrepancy Description** : (1) Les motifs exacts de détection Soft-404 ne sont pas listés. (2) Un `GET` direct sur `youtube.com/watch` redirige vers `consent.youtube.com` (`ExitCode.LICENSE_DISALLOWED`) : YouTube doit être vérifié uniquement via `youtube.com/oembed` après purge de `?si=`/`feature=`. (3) `resources.yaml` doit autoriser l'union de `outbound_only_sources` et des domaines `allow_grounding: true` (ex. `fr.vikidia.org`, avec sous-domaines `*.<domain>`). (4) Dans `link-rot.yml`, sans `continue-on-error: true` (ou capture du code retour `5`), le job s'interrompt avant `gh issue`, et le schéma JSON de `link-report.json`, la fermeture automatique de l'Issue quand tout est rétabli, ainsi que `actions/checkout@v4` + `astral-sh/setup-uv@v5` (+ `environment: github-pages` dans `deploy.yml`) manquent.
* **Rationale & Recommendation** : Figer ces quatre contrats dans les Items 20 et 32.

---

#### IR2-09 — Erreurs `HTTP 404` lors du test local après `--base-url /osarai`, normalisation de `base_url`, fond clair des schémas en mode sombre et contrats `home.html`/`subject.html`/`manifest.webmanifest` — Severity: `Major`
* **Identifiants sources** : `cd-2-4`, `cd-2-8e`, `ir-2-8`
* **Reviewer Lens** : `egm-codebase-details`, `egm-implementation-readiness`
* **Affected Scope** : Items 23 à 27 (`L638–L667`) et `Plan de Vérification` (`L713–L717`).
* **Discrepancy Description** : Servir `dist/` compilé avec `--base-url /osarai` via `python -m http.server -d dist 8000` provoque des `HTTP 404` sur toutes les ressources `/osarai/...` ; passer `--base-url /` génère `href="//manifest.webmanifest"` bloqué par `CSP` sans normalisation de `base_url` ; `url` dans `search-index.json` doit exclure `base_url` pour éviter un double préfixe ; `katex.min.js` / `auto-render.min.js` (scripts UMD) doivent être chargés via `<script defer>` avant les ES Modules ; les schémas SVG à fond transparent deviennent illisibles en mode sombre sans fond clair sur leur conteneur ; et la structure `data-reperes-levels` de `home.html` / `subject.html` doit être précisée.
* **Rationale & Recommendation** : Recompiler avec `--base-url ""` à l'étape de vérification locale `L717`, normaliser `base_url` dans `site_builder.py`, fixer un fond clair sur le conteneur d'image dans `main.css`, et préciser le chargement `<script defer>` de KaTeX ainsi que `home.html` / `subject.html`.

---

#### IR2-10 — Infrastructure de test dans `tests/conftest.py` (`git config` sur runner CI vierge et exécution des coroutines `async`) — Severity: `Major`
* **Identifiants sources** : `cd-2-9`
* **Reviewer Lens** : `egm-codebase-details`
* **Affected Scope** : Item 15 (`L594–L598`) et Item 22 (`L631–L635`).
* **Discrepancy Description** : Créer un commit Git dans `tmp_path` échoue sur un runner GitHub Actions vierge (`Author identity unknown`) si `conftest.py` ne configure pas localement `git config user.name` et `user.email` ; de plus, `probe_urls` et `check_repository_urls` étant `async def` sans `pytest-asyncio` dans `pyproject.toml`, la convention d'appel `asyncio.run(...)` sous `@respx.mock` doit être explicitée.
* **Rationale & Recommendation** : Préciser dans `conftest.py` la configuration locale `git config`, les fabriques de fixtures (20 cartes, 10 QCM, WebP valide, PDF tabulaire minimal) et l'usage d'`asyncio.run(...)` dans `test_network_and_media_helpers.py`.

---

#### IR2-11 — Calibration éditoriale de la portée d'`osarai validate` en introduction (`L518`) et de la description de `.gitignore` (`L547`) (`CALIBRATE`) — Severity: `Major`
* **Identifiants sources** : `st-2-1`, `st-2-2`, `cd-2-11`
* **Reviewer Lens** : `egm-style`, `egm-codebase-details`
* **Affected Scope** : Ligne `518` et Item 5 (`L544–L547`).
* **Discrepancy Description** : `L518` associe `osarai validate` aux chartes juridiques et aux fichiers `SKILL.md` (alors qu'`osarai validate` ne contrôle que `sources.yaml`, `bo_manifest.yaml`, `curriculum/` et `content/`) et répète *« à l'issue de chaque jalon ... livré à ce stade »* ; `L547` présente 11 motifs de `.gitignore` comme une liste exhaustive et omet le nettoyage des commentaires d'en-tête obsolètes (`Clés API Gemini`, `& Cache IA`).
* **Rationale & Recommendation** : Calibrer `L518` et `L547` conformément à la portée réelle d'`osarai validate` et au contenu complet de `.gitignore`.

---

### 🟢 Nits

#### IR2-12 — Sens du test d'anti-divulgation `badge`, indices Cloze contigus `1..K`, paramètres WebP `Pillow` et précisions sur `README.md` — Severity: `Nit`
* **Identifiants sources** : `ir-2-9`, `ir-2-10b`, `cd-2-10`
* **Reviewer Lens** : `egm-implementation-readiness`, `egm-codebase-details`
* **Affected Scope** : Items 6 (`L552`), 11 (`L577`) et 18 (`L614`).
* **Discrepancy Description** : Préciser `len(answer_norm) > 0 and answer_norm in badge_norm` (et non l'inverse) ainsi que la continuité des indices Cloze `1..K` dans `schemas.py` ; préciser les paramètres `Pillow` WebP (`quality=85, method=6`, repli `75, 65`) dans `commons_fetcher.py` ; et mentionner dans `README.md` le retrait des mentions `*(À venir)*` et le cadrage du tableau des matières pilotes sur *SVT* et *Histoire-Géographie*.
* **Rationale & Recommendation** : Intégrer ces précisions courtes aux Items 6, 11 et 18.

---

#### IR2-13 — Phrases-fleuves à participes présents (`L604`, `L609`, `L619`, `L624`, `L634`, `L641`) et redondances internes dans `author-theme` (`L685`) — Severity: `Nit`
* **Identifiants sources** : `st-2-3`, `st-2-4`, `st-2-5`
* **Reviewer Lens** : `egm-style`
* **Affected Scope** : Lignes `604`, `609`, `619`, `624`, `634`, `641` et `685`.
* **Discrepancy Description** : Plusieurs items enchaînent de 5 à 9 participes présents en une seule phrase de plus de 150 mots (`site_builder.py` atteignant 218 mots), `L624` cumule *« interrompt le flux et jette le reste ... sans jamais »*, et `L685` répète *« pas-à-pas »*, *« Phase 1 ... dès la Phase 1 »* et le détail interne de `probe-links`.
* **Rationale & Recommendation** : Découper ces items en phrases courtes à verbes conjugués ou en sous-puces et supprimer les répétitions de `L624` et `L685`.

---

#### IR2-14 — Uniformisation de « section 5 » (`LICENSE`), « liste blanche initiale », « commande `osarai` » et « échec définitif » — Severity: `Nit`
* **Identifiants sources** : `st-2-6`, `st-2-7`
* **Reviewer Lens** : `egm-style`
* **Affected Scope** : Lignes `527`, `537`, `542`, `562`, `592`, `699` et `709`.
* **Discrepancy Description** : Alternance entre « section 5 » et « article 5 » pour `LICENSE` (+ double « sous » à `L542`), calque « dès le jour 1 » (`L527`), oxymore « liste initiale figée » (`L562`), « binaire `osarai` » (`L592`), « échec franc ... lors du contrôle » (`L699`) et « fichiers déclaratifs fixes » incluant `summary.md` (`L709`).
* **Rationale & Recommendation** : Appliquer les termes exacts (« section 5 », « dès le premier jour », « liste blanche initiale », « commande `osarai` », « échec définitif », « 18 fichiers sources (6 par thème) »).

---

#### IR2-15 — Uniformisation des flèches Unicode `→` hors code et reformulations dans le `Plan de Vérification` — Severity: `Nit`
* **Identifiants sources** : `st-2-8`
* **Reviewer Lens** : `egm-style`
* **Affected Scope** : Lignes `552`, `597`, `634`, `661`, `713` et `714`.
* **Discrepancy Description** : Usage de `$\rightarrow$` en prose aux lignes `552`, `597`, `634`, `661` (au lieu de `→`), doublon bilingue « Compilation et Build Statique » (`L713`), et formulation « exécutant `tests/conftest.py` ... les mocks HTTP » (`L714`).
* **Rationale & Recommendation** : Remplacer `$\rightarrow$` par `→` hors code, renommer `L713` en « Validation et compilation statique » et préciser « appuyé sur les fixtures de `tests/conftest.py` ... les simulations HTTP » en `L714`.
