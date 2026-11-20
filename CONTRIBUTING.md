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

## 2. Prérequis Techniques et Liens Symboliques (`core.symlinks`)

L'outillage local repose uniquement sur `Python >= 3.12` et le gestionnaire [`uv`](https://docs.astral.sh/uv/) (aucun environnement `Node.js` ni `Ruby` n'est requis).

### Utilisateurs Windows (`git config core.symlinks`)
Le dépôt utilise des liens symboliques relatifs (`CLAUDE.md -> AGENTS.md` et `.claude/skills/* -> ../../.agents/skills/*`) pour éviter toute duplication des consignes entre agents IA. Sous **Windows**, activez le support des liens symboliques avant de cloner le dépôt (Mode Développeur Windows activé) :

```bash
git config --global core.symlinks true
```

### Installation de l'environnement local

```bash
uv sync --frozen
```

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
