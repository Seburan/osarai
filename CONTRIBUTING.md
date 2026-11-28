# Guide de Contribution — Osarai

Merci de contribuer à **Osarai**, plateforme libre et statique de révisions scolaires pour le collège français.

---

## 1. Gouvernance de Double Licence (Dérogation expresse à la Section 5 d'`Apache-2.0`)

Le dépôt Osarai distingue trois périmètres juridiques :

1. **Code source, tests, gabarits, compétences IA et intégration continue (`Apache-2.0`)** :
   Les répertoires et fichiers `src/`, `tests/`, `.agents/`, `.claude/`, `AGENTS.md`, `pyproject.toml`, `uv.lock`, `sources.yaml` et `.github/` sont régis par la licence [Apache License 2.0](LICENSE).
   *(Exception ressources tierces embarquées : les fichiers de la bibliothèque KaTeX sous `src/osarai/web_assets/vendor/katex/` conservent leur licence `MIT` d'origine).*
2. **Contenus pédagogiques et découpages de programmes (`CC BY-SA 4.0`)** :
   **Par dérogation expresse à la section 5 (*« 5. Submission of Contributions »*) de [`LICENSE`](LICENSE) (`Apache-2.0`)**, toute création, correction ou modification portant sur les fichiers situés sous `content/` et `curriculum/` est soumise exclusivement par son auteur sous la licence **[Creative Commons Attribution - Partage dans les Mêmes Conditions 4.0 International (`CC BY-SA 4.0`)](LICENSE-CONTENT)**.
3. **Illustrations tierces importées (`content/**/assets/`)** :
   Les schémas et cartes importés depuis Wikimedia Commons sous `content/**/assets/` conservent leur licence libre d'origine (`CC0-1.0`, `CC-PDM-1.0`, `CC-BY-2.0..4.0` ou `CC-BY-SA-2.0..4.0`), telle que documentée dans `assets.yaml` avec mention systématique des adaptations techniques (`modifications_note`).

Lors de l'ouverture d'une *Pull Request*, veuillez cocher la case de confirmation correspondante dans `.github/PULL_REQUEST_TEMPLATE.md`.

---

## 2. Prérequis Techniques et Installation Locale

L'outillage local repose uniquement sur `Python >= 3.12` et le gestionnaire [`uv`](https://docs.astral.sh/uv/) (aucun environnement `Node.js` ni `Ruby` n'est requis).

### Installation de `uv`
- **Linux / macOS** :
  ```bash
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Windows (PowerShell)** :
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

### Utilisateurs Windows (`git config core.symlinks`)
Le dépôt utilise des liens symboliques relatifs (`CLAUDE.md -> AGENTS.md` et `.claude/skills/* -> ../../.agents/skills/*`) pour éviter toute duplication des consignes entre agents IA. Sous **Windows**, activez le support des liens symboliques avant de cloner le dépôt (Mode Développeur Windows activé) :

```bash
git config --global core.symlinks true
```

### Synchronisation de l'environnement local (`.venv`)
À la racine du dépôt cloné, synchronisez les dépendances verrouillées et installez le paquet `osarai` en mode éditable :

```bash
uv sync --frozen --reinstall-package osarai
```

> **Astuce** : relancez également `uv sync --frozen --reinstall-package osarai` après un `git pull` majeur, un changement de version mineure de Python (`3.12` / `3.13` / `3.14`) ou un déplacement du répertoire de travail afin de rafraîchir le pointeur éditable `.pth` de `.venv`.

### Agents de code compatibles (`AGENTS.md` & `.agents/skills/`)
À l'ouverture du projet dans **Antigravity**, **Claude Code** ou **OpenAI Codex**, les consignes permanentes de [`AGENTS.md`](AGENTS.md) (et son lien `CLAUDE.md`) ainsi que les compétences guidées `.agents/skills/*` sont détectées automatiquement sans fichier `.env` ni configuration supplémentaire.

---

## 3. Contribuer Manuellement sans Agent IA

Aucune clé API ni abonnement d'agent IA n'est nécessaire pour corriger une erreur, enrichir une explication ou ajouter des cartes/questions :

1. **Modifier une carte ou question existante** :
   Éditez directement `summary.md`, `flashcards.yaml`, `quiz.yaml` ou `resources.yaml` dans `content/<cycle>/<matiere>/<slug-theme>/`.
   - **Règle d'immuabilité** : ne modifiez **jamais** l'attribut `id` ni le `type` (`basic` / `cloze`) d'une carte existante afin de préserver l'historique de révision des élèves.
   - Pour retirer définitivement un élément erroné, supprimez-le du fichier YAML et ajoutez son `id` dans la liste `retired_ids` de `meta.yaml` sans décrémenter `last_card_seq` ni `last_quiz_seq`.
2. **Ajouter une nouvelle carte mémoire ou un nouveau QCM** :
   Ajoutez l'entrée dans `flashcards.yaml` ou `quiz.yaml` **sans renseigner le champ `id`**, puis attribuez automatiquement les identifiants monotones :
   ```bash
   uv run osarai assign-ids --theme content/cycle-4/svt/la-respiration
   ```
   *(Si vous éditez directement depuis l'interface web de GitHub sans exécuter Python localement, le workflow CI indiquera dans son rapport la valeur exacte de l'`id` attendu et le nouveau compteur `last_card_seq` / `last_quiz_seq` à reporter dans `meta.yaml`).*
3. **Valider hors-ligne avant d'ouvrir la Pull Request** :
   ```bash
   uv run osarai validate --against-ref origin/main
   uv run osarai build-site --output dist --base-url ""
   ```

---

## 4. Rédaction Assistée par Compétences d'Agents IA (Optionnel, HITL)

Si vous utilisez un agent de code compatible avec le format portable `SKILL.md` (**Antigravity**, **Claude Code** ou **OpenAI Codex**), trois compétences guidées avec validation humaine (*Human-in-the-Loop*, HITL) sont disponibles dans `.agents/skills/` (et liées dans `.claude/skills/`) :

- **`init-curriculum`** : téléchargement vérifié des PDF officiels Éduscol (*Licence Ouverte Etalab 2.0*) via `uv run osarai sync-bo` et découpage thématique dans `curriculum/<cycle>/<matiere>.yaml`.
- **`author-theme`** : rédaction séquentielle en 2 phases d'un thème complet (Phase 1 : textes compatibles `CC BY-SA 4.0` via `fetch-grounding`, illustrations Wikimedia Commons `1280 px` via `fetch-commons`, contrôle visuel des masques d'occultation via `preview-occlusions` et `validate --allow-empty-resources` ; Phase 2 : vérification des liens externes via `probe-links`, écriture de `resources.yaml`, `validate` et `build-site`).
- **`fix-flagged-cards`** : traitement sécurisé d'un signalement élève/parent (`osarai-feedback-v1`) après validation préalable par `uv run osarai validate --feedback <fichier>`.

### Règles impératives sur les sources et formules
- Ne copiez et n'adaptez **jamais** de texte issu d'un manuel scolaire propriétaire ou sous licence non commerciale (`CC BY-NC-SA`, ex. *Lelivrescolaire.fr*, *Lumni*). Seuls les domaines marqués `allow_grounding: true` dans `sources.yaml` peuvent servir de source textuelle.
- Délimitez toutes les formules mathématiques et chimiques avec `\(...\)` (en ligne) et `\[...\]` (bloc), en utilisant `\text{CO}_2` plutôt que la macro non standard `\ce{...}`.

---

## 5. Contribuer au Code Python et au Portail Statique (Tests, Aperçu & Dépannage)

### Contrôles automatisés avant Pull Request
Toute modification sous `src/`, `tests/` ou `.github/workflows/` doit passer l'ensemble des vérifications locales reproduisant la CI :

```bash
# Linter et formatage Ruff
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Suite de tests unitaires et d'intégration (seuil de couverture de branches >= 85 %)
uv run pytest --cov
# (équivalent explicite : uv run pytest --cov=src/osarai --cov-branch --cov-fail-under=85)

# Validation complète des schémas, identifiants et contenus
uv run osarai validate --against-ref origin/main
```

### Aperçu local et checklist navigateur (*DevTools*)
1. **Aperçu racine (`http://localhost:8000`)** :
   ```bash
   uv run osarai build-site --output dist --base-url ""
   uv run python -m http.server -d dist 8000
   ```
2. **Simulation du sous-chemin GitHub Pages (`http://localhost:8000/osarai/`)** :
   ```bash
   mkdir -p .osarai_tmp/gh_pages_sim
   uv run osarai build-site --output .osarai_tmp/gh_pages_sim/osarai --base-url "/osarai"
   uv run python -m http.server -d .osarai_tmp/gh_pages_sim 8000
   ```
3. **Points à vérifier dans les *DevTools* du navigateur (`F12`) et conformité `modern-web-guidance`** :
   - Toute évolution HTML/CSS/JS sous `src/osarai/templates/` ou `src/osarai/web_assets/` doit suivre les référentiels **`modern-web-guidance`** (en amélioration progressive sans polyfill externe, conformément à [`AGENTS.md`](AGENTS.md)).
   - **Onglet *Console*, *Network* & *Lighthouse*** : aucune erreur console ni `Content-Security-Policy`, **zéro requête vers un domaine externe** (icône SVG, polices et CSS KaTeX chargés localement), absence de débordement horizontal à `320 px` de large, et maintien des scores Lighthouse à `100` (*Accessibility*, *Best Practices*, *SEO*).
   - **Modes clair / sombre** : ouvrez le panneau **Outils** dans l'en-tête pour basculer entre le thème clair et le thème sombre et vérifier que le conteneur d'illustration `.asset-container` conserve son fond `#ffffff`, que les masques d'occultation (`target` ambre `#b45309` `?` et `mask` ardoise) sont 100 % opaques et alignés, et que le bouton *Agrandir le schéma* ouvre la boîte `<dialog>` plein écran.
   - **Quarantaine & Sauvegarde** : le signalement d'une carte ou d'un QCM l'écarte immédiatement dans `localStorage`, génère un JSON valide pour `uv run osarai validate --feedback <fichier>`, et l'export/import `osarai-backup-v1.json` (accessible depuis **Outils**) restaure la progression.

### Dépannage fréquent (*Troubleshooting*)
- **`CoverageWarning: No data was collected (no-data-collected)` (`Total coverage: 0.00%`) lors de `pytest --cov`** :
  Survient lorsqu'un environnement `.venv` préexistant contient un pointeur éditable `_editable_impl_osarai.pth` obsolète (après un déplacement de dossier, un changement de version de Python ou une initialisation antérieure) ou en cas d'ambiguïté sur le nom du module. Exécutez :
  ```bash
  uv sync --frozen --reinstall-package osarai
  uv run pytest --cov=src/osarai --cov-branch --cov-fail-under=85
  ```
- **`HTTP 403` / code de sortie `3` sur certaines pages HTML ministérielles ou encyclopédiques (`sync-bo --discover-url`, `probe-links`)** :
  Certains pare-feu distants filtrent ponctuellement les requêtes automatisées ou les plages d'IP infonuagiques sur leurs pages HTML (ce que la CLI signale proprement par le code `3` *limitation distante*). Privilégiez les URL directes des documents `.pdf` officiels dans `curriculum/sources/bo_manifest.yaml` (et l'API MediaWiki utilisée par `fetch-grounding` / `fetch-commons`), ou relancez le sondage depuis un poste local résidentiel.
