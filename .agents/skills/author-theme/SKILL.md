---
name: author-theme
description: Rédiger en mode interactif HITL un thème complet du collège (cours synthétique, illustrations Wikimedia Commons masquées, cartes mémoire, QCM et ressources externes) en 2 phases étanches sous licence CC BY-SA 4.0.
---

# Compétence `author-theme` — Rédaction Séquentielle d'un Thème en 2 Phases (HITL)

Cette compétence guide la création complète d'un dossier `content/<cycle>/<matiere>/<theme_slug>/` en **deux phases strictement séparées** afin d'empêcher toute contamination des textes `CC BY-SA 4.0` par des ressources externes propriétaires ou `CC BY-NC-SA`.

Lisez au préalable `AGENTS.md` et la tranche du thème visé dans `curriculum/<cycle>/<matiere>.yaml`.

---

## Phase 1 — Cadrage officiel, visuels libres, rédaction sous `CC BY-SA 4.0` et verrouillage hors-ligne

> **Règle d'étanchéité de Phase 1** : durant toute la Phase 1, n'interrogez **aucun** site externe hors `fetch-grounding` (*Vikidia FR*, *Wikipédia FR*) et `fetch-commons` (*Wikimedia Commons*). N'exécutez pas `probe-links` avant que la validation de Phase 1 n'ait retourné le code `0`.

### 1.1 Cadrage sur le programme officiel et squelette initial
1. Lisez uniquement l'entrée `theme_slug` correspondante dans `curriculum/<cycle>/<matiere>.yaml` (`title`, `macro_theme_bo`, `reperes_levels`, `attendus_bo`, `scope_exclusions`).
2. Créez le dossier `content/<cycle>/<matiere>/<theme_slug>/` et initialisez :
   - le squelette de `meta.yaml` (`schema_version: 1`, `cycle`, `subject`, `subject_code`, `theme_slug`, `title` identique à `curriculum/`, `reperes_levels`, `scope_exclusions`, `qa_status: "hitl_verified"`, `key_concepts`, `sources_used: []`, `last_card_seq: 0`, `last_quiz_seq: 0`, `retired_ids: []`),
   - `assets.yaml` vide (`schema_version: 1` et `assets: []`),
   - `resources.yaml` temporairement vide (`schema_version: 1` et `resources: []`).

### 1.2 Documentation source compatible `CC BY-SA 4.0` (`fetch-grounding`)
1. Recherchez d'abord sur *Vikidia FR* (calibré 8–13 ans), puis si nécessaire sur une section ciblée de *Wikipédia FR* :
   ```bash
   uv run osarai fetch-grounding --search "<requête>" --domain fr.vikidia.org --json
   uv run osarai fetch-grounding --url "https://fr.vikidia.org/wiki/<Article>" --theme content/<cycle>/<matiere>/<theme_slug> --json
   ```
   *(Sur Wikipédia FR, utilisez `--section "<Titre de section>"` pour éviter de charger des détails de niveau lycée exclus par `scope_exclusions`).*
2. Vérifiez que `meta.yaml -> sources_used` a bien reçu automatiquement les crédits *TASL* complets.

### 1.3 Recherche et import d'illustrations Wikimedia Commons (`fetch-commons`)
1. Recherchez 1 à 3 schémas didactiques ou cartes thématiques (privilégiez les versions francophones ou SVG multilingues) :
   ```bash
   uv run osarai fetch-commons --search "<mots-clés en français ou anglais>" --json
   ```
2. Importez chaque illustration retenue au palier standard `1280 px` :
   ```bash
   uv run osarai fetch-commons --file "File:<Nom_exact>" --theme content/<cycle>/<matiere>/<theme_slug> --asset-id <slug-court> --json
   ```
3. Inspectez visuellement l'image importée (`content/.../assets/<filename>`) ainsi que sa **grille graduée `0..100 %`** générée hors Git dans `.osarai_tmp/previews/<filename>--grid.png` pour relever précisément les coordonnées `{x, y, w, h}` des légendes à masquer.

### 1.4 Rédaction pédagogique (`summary.md`, `flashcards.yaml`, `quiz.yaml`)
1. **`summary.md`** :
   - Démarrez directement au niveau `##` (aucun `# ` de niveau 1) avec les quatre sections obligatoires dans l'ordre :
     1. `## L'essentiel à retenir`
     2. `## Définitions clés`
     3. `## Schémas et repères` (intégrant les illustrations locales `![Texte alternatif descriptif](assets/<filename>)`)
     4. `## Pièges fréquents au contrôle`
   - Si le thème couvre plusieurs années dans `reperes_levels`, isolez les notions des années supérieures sous `### Approfondissement 4ème` / `### Approfondissement 3ème`.
   - Respectez strictement `scope_exclusions` et utilisez `\(...\)` / `\[...\]` avec `\text{...}` (jamais `\ce{...}` ni HTML brut).
2. **`flashcards.yaml`** (`20` à `50` cartes, couvrant 100 % des `concept_id` de `meta.yaml`) :
   - **N'écrivez aucun champ `id` à la main** (ils seront attribués par `assign-ids`).
   - Variez cartes `type: "basic"` (définitions actives, relations cause-conséquence, lecture de schémas/cartes avec `asset_role: "front_occluded"` et boîtes `occlusions` distinguant `role: "target"` avec `badge: "?"` et `role: "mask"` pour les autres légendes dévoilant le contexte) et cartes `type: "cloze"` (`back: ""`, indices `{{c1::réponse::indice court}}` contigus `1..K`, **jamais** couplées à `front_occluded`).
   - Gardez des réponses concises (`<= 250` caractères recommandés, plafond `500`).
3. **`quiz.yaml`** (`10` à `20` QCM à 4 choix distincts) :
   - **N'écrivez aucun champ `id` à la main**.
   - Rédigez des distracteurs plausibles inspirés des confusions fréquentes d'élèves en contrôle, et fournissez une `explanation` claire pour chaque question.

### 1.5 Attribution des ID, aperçus d'occultation HITL et verrouillage de Phase 1
1. Numérotez automatiquement les cartes et QCM :
   ```bash
   uv run osarai assign-ids --theme content/<cycle>/<matiere>/<theme_slug> --json
   ```
2. Si le thème comporte des éléments `front_occluded`, générez et inspectez les aperçus pleine taille (`--full.png`) et mobile (`--mobile-320w.png`) :
   ```bash
   uv run osarai preview-occlusions --theme content/<cycle>/<matiere>/<theme_slug> --json
   ```
   - Vérifiez que chaque boîte `target` / `mask` couvre intégralement le texte de la légende sans masquer la pointe des flèches anatomiques ou géographiques, et que le `badge` reste lisible à `320 px` de large. Ajustez `{x, y, w, h}` et relancez `--item-id <id>` si nécessaire.
3. **Point de contrôle HITL de fin de Phase 1** :
   - Présentez les aperçus d'illustrations et le résumé des notions couvertes à l'humain.
   - Après validation visuelle, passez `hitl_verified: true` sur chaque entrée de `assets.yaml`.
4. Exécutez la validation hors-ligne de Phase 1 jusqu'à obtenir `0` erreur :
   ```bash
   uv run osarai validate --theme content/<cycle>/<matiere>/<theme_slug> --allow-empty-resources --json
   ```

---

## Phase 2 — Sélection des ressources externes (`resources.yaml`) sans retouche du cours

> **Règle d'immuabilité de Phase 2** : une fois la Phase 1 validée, **ne modifiez plus `summary.md`, `flashcards.yaml` ni `quiz.yaml`**.

1. Sélectionnez `3` à `6` liens externes complémentaires adaptés aux collégiens parmi les domaines autorisés dans `sources.yaml` (*Vikidia FR*, *Lumni*, *Lelivrescolaire.fr*, *CoopMaths*, *Sésamath*, ou vidéos des chaînes YouTube figurant dans `allowed_youtube_channel_urls` au format canonique `https://www.youtube.com/watch?v=<11-car>`).
2. Sondez les URL candidates via `probe-links` (qui ne lit que les en-têtes/`<title>` ou `oEmbed` sans exposer le corps des articles) :
   ```bash
   uv run osarai probe-links --url "https://..." --url "https://..." --json
   ```
   - Ne retenez que les liens vérifiés (`ok: true` et `status: 200`, ou confirmés par le mainteneur humain en cas de filtrage anti-robots `403`/`429` hors YouTube). Sur YouTube, reportez le `channel_url` exact retourné par `oEmbed`.
3. Renseignez uniquement `content/<cycle>/<matiere>/<theme_slug>/resources.yaml` (`3` à `6` ressources, avec `last_verified_at` à la date du jour `YYYY-MM-DD`).
4. Exécutez la validation complète finale et la compilation statique du portail :
   ```bash
   uv run osarai validate --theme content/<cycle>/<matiere>/<theme_slug> --json
   uv run osarai build-site --output dist --base-url ""
   ```
