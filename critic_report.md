# Rapport de Revue Critique — Phase 7, Round 2 (`critic_report.md`)

**Cible auditée** : [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L1-L490) (`FeatureRange` : lignes `1..490`, Round `2` — ré-audit après application des 22 correctifs du Round 1)
**Standards appliqués** :
* `egm-design` : `feature-spec-standard.md`
* `egm-structural` : `feature-spec-standard.md`
* `egm-style` : vecteurs d'audit éditorial et calibration des affirmations (`DROP | CALIBRATE | RELOCATE`)
**Contexte Goldfish fourni** : [LICENSE](file:///Users/seburan/Development/osarai/LICENSE) (`Apache-2.0`)

## Statut des Auditeurs (Round 2)

| Auditeur | Statut | Bilan brut (Round 2) | Évolution depuis Round 1 |
| :--- | :--- | :--- | :--- |
| `egm-structural` | `completed` | `0` Blocker, `0` Major, `5` Nits | Tous les Majors structurels du Round 1 sont résolus |
| `egm-style` | `completed` | `0` Blocker, `4` Majors, `3` Nits | Baisse de `7` à `4` Majors éditoriaux |
| `egm-design` | `completed` | `3` Blockers, `6` Majors, `1` Nit | Nouveaux cas limites détectés sur le pipeline `texmath`/KaTeX, les crédits `TASL` textuels et l'`oEmbed` YouTube en CI |

**Synthèse consolidée et dédupliquée (Round 2)** : **`3` Blockers**, **`10` Majors**, **`8` Nits** (`21` points consolidés ; `0` churn nécessitant d'annuler un correctif du Round 1).

---

## Observations Priorisées (Blockers -> Majors -> Nits)

### 🔴 Blockers

#### R2-01 — Collision du pipeline de rendu Markdown / LaTeX / Cloze (`texmath` vs `KaTeX auto-render` vs CommonMark) et incompatibilité Cloze multi-trous + `occlusions` — Severity: `Blocker`
* **Identifiants sources** : `design-2-1`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : `### 1. Vue d'ensemble des flux` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L104-L106)), `#### 3.3 Contrats des 6 fichiers` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L279-L284)), `### 6. Portail Web Statique` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L340-L344)).
* **Discrepancy Description** :
  1. En `§6` (`L340`), `summary.md` utilise le plugin `texmath` de `markdown-it-py`, qui supprime par défaut les délimiteurs `\(...\)` / `\[...\]` et émet des balises `<eq>...</eq>` et `<section><eqn>...</eqn></section>`. Or `contrib/auto-render.min.js` (`L342`) n'inspecte que les nœuds DOM `Text` (`nodeType === 3`) et ignore ces éléments HTML : aucune formule de la *Fiche de Synthèse* ne sera rendue par KaTeX.
  2. Sur les champs en ligne des cartes et QCM (`L344`), exécuter `markdown-it-py` sans jetoniseur mathématique applique l'échappement CommonMark aux antislashs (`\(` devient `(`) et convertit deux `_` dans une formule en `<em>...</em>` avant KaTeX.
  3. En `§3.3` (`L280`), autoriser simultanément `type: "cloze"` à trous multiples (`{{c1}}`, `{{c2}}`) et `asset_role: "front_occluded"` échoue lors du dépliage en `<card_id>#c1`, `<card_id>#c2` car `occlusions` est rattaché à la note entière et non par trou `#cK`.
* **Rationale & Recommendation** : Activer le jetoniseur `texmath` (`delimiters="brackets"`) à la fois sur `summary.md` et sur le rendu en ligne des cartes/QCM en **surchargeant ses règles de rendu pour ré-émettre littéralement `\(...\)` et `\[...\]` échappés en HTML** (`html.escape`) ; déplier les balises `{{cN::...}}` *avant* la conversion Markdown en ligne ; et interdire dans `schemas.py` la combinaison `type == "cloze"` avec `asset_role == "front_occluded"` (ou la restreindre à un unique trou `c1`).

---

#### R2-02 — Lacunes juridiques dans les crédits `TASL` des sources textuelles (`CC BY-SA 3.0/4.0`, `Etalab 2.0`) et omission de la licence `MIT` de `KaTeX` — Severity: `Blocker`
* **Identifiants sources** : `design-2-2`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : `## Approche Retenue` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L42-L43)), `### 2. Arborescence du dépôt, double licence` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L158-L162)), `#### 3.2 & 3.3` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L245-L249), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L271)), `### 6. Portail Web Statique` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L340-L342)).
* **Discrepancy Description** :
  1. Le critère pilote n° 1 (`L43`) exige 100 % des crédits *TASL* vérifiés automatiquement, mais `meta.yaml -> sources_used` (`L271` : `{title, url, source_domain, license_spdx, revision_or_date}`) omet l'auteur/lien d'historique (`authors_or_history_url`), l'URI du texte de licence (`license_url`) et la mention d'adaptation exigés par `CC BY-SA 3.0 §4(c)` (*Vikidia*) et `CC BY-SA 4.0 §3(a)(1)` (*Wikipédia FR*). De même, `bo_sources` (`L245–L249`) omet le producteur et la date de publication requis par la *Licence Ouverte Etalab 2.0*.
  2. La redistribution des binaires et polices `KaTeX` dans le dépôt et dans `dist/assets/vendor/katex/` (`L342`) omet l'inclusion obligatoire du fichier de licence `MIT` et de sa notice de copyright, et `§2` (`L160`) ne mentionne pas `sources.yaml` ni les ressources tierces vendues.
* **Rationale & Recommendation** : Ajouter `authors_or_history_url` et `license_url` dans `meta.yaml -> sources_used` ainsi que `producer` et `publication_date` dans `bo_sources` (affichés en pied de page avec mention explicite d'adaptation), et embarquer/copier le fichier `LICENSE` (`MIT`) de `KaTeX` dans `dist/assets/vendor/katex/LICENSE` tout en précisant le statut de `sources.yaml` et `vendor/` en `§2`.

---

#### R2-03 — Contournement de la liste blanche YouTube sur `HTTP 403/429` en PR CI, entrée non fiable dans `fix-flagged-cards` et absence de politique `Content-Security-Policy` — Severity: `Blocker`
* **Identifiants sources** : `design-2-3`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : `#### 3.1 & 3.3` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L228), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L287-L288)), `### 4, 5, 6 & 7` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L306-L309), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L329-L331), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L341-L362)), `### Sécurité, vie privée...` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L450-L452)).
* **Discrepancy Description** :
  1. En `§7` (`L362`), traiter `HTTP 403` / `429` en simple avertissement sur `check-urls --diff origin/main` permet à une PR externe d'introduire une vidéo YouTube arbitraire avec un faux `channel_url: "https://www.youtube.com/@Lumni"` dès que `youtube.com/oembed` bloque l'IP GitHub Actions.
  2. La ligne `451` attribue le confinement d'impact d'une injection de prompt aux restrictions de la CLI `osarai`, alors que c'est **l'agent hôte** (doté d'outils shell et d'écriture sur tout le dépôt) qui ingère le texte de `fetch-grounding` ou d'une Issue GitHub publique dans `fix-flagged-cards` (`L330–L331`, où `note`, `cycle`, `subject`, `theme_slug` ne sont ni bornés ni validés avant lecture par l'agent).
  3. Le portail (`L341`, `L350`) n'inclut pas de balise `<meta http-equiv="Content-Security-Policy">` garantissant côté navigateur le blocage de toute requête externe et l'absence de script en ligne exécutable, ni d'exigence explicite de validation de schéma sur `osarai-backup-v1.json` et d'usage de `textContent` pour les données issues de `localStorage`.
* **Rationale & Recommendation** : Rendre **bloquant** tout échec `oEmbed` YouTube sur les liens *nouvellement ajoutés ou modifiés* dans `check-urls --diff` (tout en conservant la tolérance `403`/`429` dans le cron hebdomadaire `link-rot.yml` sur les liens déjà vérifiés, et en contrôlant tous les codes `3xx` `301/302/303/307/308`) ; plafonner `note` (`<= 300` car.), valider les identifiants du bloc `osarai-feedback-v1` via `validate` / filtre déterministe avant édition et calibrer `L451` sur les permissions de l'agent hôte et la relecture du `git diff` ; ajouter une `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; ...">` stricte et la validation de schéma à l'import JSON.

---

### 🟡 Majors

#### R2-04 — Rejet `HTTP 429` par Wikimedia Commons sur les vignettes `1200 px` hors paliers `$wgThumbnailSteps` et seuil rigide `<= 150 Ko` sur les cartes — Severity: `Major`
* **Identifiants sources** : `design-2-4`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : `## Objectifs` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L53)), `#### 3.3 & ### 4` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L274), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L304)), `### Performance...` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L455)).
* **Discrepancy Description** : Wikimedia Commons rejette désormais en `HTTP 429`/`400` les largeurs de vignettes hors paliers officiels `$wgThumbnailSteps` (ex. `1200 px` au lieu de **`1280 px`**), les SVG monolingues français sans `<switch>` nécessitent un repli automatique sans `langfr`, et un plafond dur `<= 150 Ko` dégrade la lisibilité des toponymes sur les cartes de géographie.
* **Rationale & Recommendation** : Utiliser le palier standard **`1280 px`** de Wikimedia Commons (avec repli automatique si `langfr` échoue sur un SVG monolingue) et distinguer une cible de compression à `150 Ko` (avertissement) d'un plafond bloquant à `300 Ko` (`< 315 Mo` à l'échelle de 1 050 fichiers).

---

#### R2-05 — Modélisation incomplète de la progression spiralaire du Cycle 4 (`reperes_level` scalaire, filtrage strict et `summary.md` indivis) — Severity: `Major`
* **Identifiants sources** : `design-2-5`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : Lignes `33`, `43`, `50`, `254`, `269–286` et `344` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L269-L286), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L344)).
* **Discrepancy Description** : Sur un thème pluri-annuel du *Cycle 4*, filtrer par égalité stricte (`reperes_level == "4eme"`) masque à un élève de `4ème` les rappels essentiels de `5ème`, tandis qu'un `summary.md` sans indication de niveau expose des notions de `4ème`/`3ème` à un élève de `5ème` ; en outre, l'inclusion `item.reperes_level in meta.reperes_levels` n'est pas imposée.
* **Rationale & Recommendation** : Privilégier des thèmes mono-niveau lors du découpage `init-curriculum` chaque fois que possible ; sur les thèmes multi-niveaux, appliquer un filtrage **cumulatif** (`<= osarai:v1:grade`), baliser explicitement tout bloc d'approfondissement `4ème`/`3ème` dans `summary.md`, et valider la cohérence des `reperes_level` dans `schemas.py`.

---

#### R2-06 — Lisibilité des badges d'occultation sur smartphone (`360 px`), verrouillage CSS `aspect-ratio` sans `object-fit` et symétrie `quiz.yaml` — Severity: `Major`
* **Identifiants sources** : `design-2-6`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : Lignes `70–73`, `280`, `286`, `305` et `345` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L280-L286), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L345)).
* **Discrepancy Description** : Une boîte d'étiquette de `2 %` de haut ne fait que `5–6 px` sur un écran mobile de `360 px` (rendant le badge illisible sans zoom plein écran ni contrôle basse résolution dans `preview-occlusions`) ; le conteneur CSS doit interdire `object-fit` et borner sa largeur par rapport à `aspect-ratio` et `max-height` ; enfin, `quiz.yaml` manque de `asset_role` et `flashcards.yaml` devrait autoriser une occultation purement `mask` (titre caché sur question globale).
* **Rationale & Recommendation** : Ajouter un mode d'agrandissement plein écran (`<dialog>`) sur les schémas occultés ainsi qu'une vignette de contrôle mobile (`320 px`) dans `preview-occlusions`, verrouiller le conteneur par `aspect-ratio` sans `object-fit`, ajouter `asset_role` sur `quiz.yaml` (rejetant `occlusions` sans `asset_id`) et autoriser `0` ou `>= 1` boîte `target` tant que `occlusions` est non vide.

---

#### R2-07 — Risque de dépassement des quotas de jetons (`fetch-grounding` non borné, estimation d'occultations sans grille graduée et extraction BO monolithique) — Severity: `Major`
* **Identifiants sources** : `design-2-7`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : Lignes `235–236`, `302–305`, `318–325` et `458` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L302-L305), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L318-L325)).
* **Discrepancy Description** : `fetch-grounding` ne plafonne pas la taille des articles Wikipédia, `fetch-commons` ne fournit pas de grille graduée `0..100 %` pour guider le placement initial `{x, y, w, h}` (provoquant des boucles coûteuses d'essais-erreurs multimodaux), et `sync-bo` concatène des PDF de 100 pages en un seul fichier géant.
* **Rationale & Recommendation** : Plafonner la sortie de `fetch-grounding` (ex. `<= 40 Ko` avec ciblage optionnel de sections), générer automatiquement dans `.osarai_tmp/previews/` une image d'aide munie d'une grille graduée en pourcentages (`5 %` / `10 %`) lors de `fetch-commons` (et ciblage `--item-id` sur `preview-occlusions`), et écrire un fichier Markdown par PDF dans `.osarai_tmp/bo_texts/<cycle>-<matiere>/`.

---

#### R2-08 — Angles morts de `localStorage` : items retirés (`retired_ids`), cloisonnement Safari vs Web App sous iPadOS et propagation de `--base-url` — Severity: `Major`
* **Identifiants sources** : `design-2-8`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : Lignes `73–79`, `272`, `310`, `331`, `348–356`, `364` et `469` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L348-L356), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L469)).
* **Discrepancy Description** : Une carte retirée via `retired_ids` disparaît de `#theme-data` sans jamais être marquée résolue dans `osarai:v1:flags` ; sous iPadOS, l'ajout sur l'écran d'accueil crée une partition `localStorage` isolée de Safari ; et `--base-url` doit être injecté dans `manifest.webmanifest` et `<html data-base-url="...">` pour éviter des `404` sur GitHub Pages.
* **Rationale & Recommendation** : Inclure `retired_ids` dans `#theme-data` (marquant l'entrée du panier résolue/retirée et n'exportant par défaut que les signalements actifs), documenter le transfert par export/import JSON lors du passage Safari -> Web App sur iPadOS, et injecter systématiquement `base_url` dans `manifest.webmanifest` et `<html data-base-url="...">`.

---

#### R2-09 — Échec de `origin/main...HEAD` sans `fetch-depth: 0` en CI et invariants incomplets de `validate` sur `retired_ids` — Severity: `Major`
* **Identifiants sources** : `design-2-9`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : Lignes `272`, `308` et `360–362` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L272), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L360-L362)).
* **Discrepancy Description** : `git diff origin/main...HEAD` requiert l'historique commun (`fetch-depth: 0` dans `actions/checkout`, un simple fetch `depth=1` échouant en `no merge base`), et `validate` doit vérifier explicitement `active_ids ∩ retired_ids == ∅`, `seq <= last_*_seq`, la non-décroissance de `last_*_seq`, la non-suppression d'entrées de `retired_ids` et la non-suppression d'un dossier de thème publié par rapport à `origin/main`.
* **Rationale & Recommendation** : Spécifier `fetch-depth: 0` dans `ci.yml` (`L361`) et inscrire ces invariants dans `§3.3` (`L272`) et `§4` (`L308`).

---

#### R2-10 — Estimations de jetons contradictoires, emploi impropre de « refacture » et tournure « jusqu'à 1 \$ à 7 \$ » (`CALIBRATE`) — Severity: `Major`
* **Identifiants sources** : `style-2-1`
* **Reviewer Lens** : `egm-style`
* **Affected Scope** : Lignes `32`, `375`, `381` et `458` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L32), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L375-L381), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L458)).
* **Discrepancy Description** : Fourchettes de jetons discordantes (`200 000 à 400 000` en `L458` présentée à l'indicatif vs `~250 000 à 500 000` en `L381`), verbe « refacture » impropre sur un forfait, syntaxe « jusqu'à 1 \$ à 7 \$ » incohérente (`L32`, `L375`) et hyperbole « obligerait à tout régénérer » (`L381`).
* **Rationale & Recommendation** : Unifier le budget cible estimatif (ex. `~200 000 à 400 000` jetons cumulés par thème), remplacer « refacture » par « décompte dans le quota », écrire « de l'ordre de 1 \$ à 7 \$ selon le volume de recherche » et formuler factuellement le coût de reprise sur 25 thèmes.

---

#### R2-11 — Cliché « en un clic », critère pilote n° 2 non quantifié et promesse de persistance tablette surcalibrée dans `CUJ 1` (`CALIBRATE` / `RELOCATE`) — Severity: `Major`
* **Identifiants sources** : `style-2-2`
* **Reviewer Lens** : `egm-style`
* **Affected Scope** : Lignes `42–44`, `55` et `71–79` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L42-L44), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L71-L79)).
* **Discrepancy Description** : « en un clic » (`L44`, `L55`, `L73`) contredit le parcours multi-actions réel de signalement ou d'import de fichier ; le critère pilote n° 2 (`L44`) ne fixe pas de seuil chiffré ; et `CUJ 1` (`L73`) présente la protection Web App contre la purge à 7 jours comme automatique sans mentionner l'action préalable d'ajout à l'écran d'accueil ou d'export JSON.
* **Rationale & Recommendation** : Supprimer « en un clic », fixer un seuil vérifiable au critère n° 2 (ex. séances réelles sur les `>= 3` thèmes pilotes et validation d'au moins `1` cycle complet de bout en bout `osarai-feedback-v1` -> `fix-flagged-cards`), et borner `CUJ 1` au comportement de `localStorage` complété sur action de l'utilisateur par l'installation Web App ou la sauvegarde JSON.

---

#### R2-12 — Redondances entre les sections de cadrage et triple description de `sync-bo` / `init-curriculum` — Severity: `Major`
* **Identifiants sources** : `style-2-3`
* **Reviewer Lens** : `egm-style`
* **Affected Scope** : Lignes `13–15`, `40–41`, `51–55`, `165`, `234–236`, `302` et `314–318` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L40-L55), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L234-L236), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L314-L318)).
* **Discrepancy Description** : La séparation `SKILL.md` / CLI `osarai` est exposée trois fois entre `L13` et `L55`, le frontmatter `SKILL.md` trois fois (`L13`, `L165`, `L314`), et la procédure détaillée de `sync-bo` trois fois (`L234–236`, `L302`, `L318`).
* **Rationale & Recommendation** : Condenser `Objectifs` et `init-curriculum` (`§5.1`) pour qu'ils renvoient aux détails techniques déjà définis en `§2` et `§3.2` sans les recopier.

---

#### R2-13 — Phrases-fleuves (98 à 138 mots) dans `§3.3` / `CUJ` et répétition interne sur le sans-cookie CNIL en Phase 2 — Severity: `Major`
* **Identifiants sources** : `style-2-4`, `structural-2-3b`
* **Reviewer Lens** : `egm-style`, `egm-structural`
* **Affected Scope** : Lignes `52–55`, `72–91`, `280`, `286` et `486–487` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L280-L286), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L486-L487)).
* **Discrepancy Description** : La ligne `280` concentre 11 champs et contraintes de `flashcards.yaml` en une phrase unique de 138 mots ; plusieurs clauses `CUJ` dépassent 95–109 mots ; et la ligne `486` répète quatre fois l'idée de sans-cookie / exemption CNIL en 106 mots.
* **Rationale & Recommendation** : Scinder les champs de `flashcards.yaml` et `quiz.yaml` en sous-puces courtes, découper les phrases longues des `CUJ` / `Objectifs` et condenser `L486` en deux phrases sans répétition.

---

### 🟢 Nits

#### R2-14 — Diagnostic CI incomplet lors d'un ajout manuel sans `id` (`CUJ 4`) — Severity: `Nit`
* **Identifiants sources** : `design-2-10`
* **Reviewer Lens** : `egm-design`
* **Affected Scope** : Lignes `89–91` et `307–308` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L89-L91)).
* **Discrepancy Description** : Indiquer uniquement l'`id` manquant sans préciser la nouvelle valeur attendue de `last_card_seq` / `last_quiz_seq` dans `meta.yaml` ferait échouer une seconde fois une PR éditée depuis l'interface web GitHub.
* **Rationale & Recommendation** : Préciser que `osarai validate` indique simultanément l'`id` complet à insérer et la valeur exacte à reporter sur `last_card_seq` / `last_quiz_seq` dans `meta.yaml`.

---

#### R2-15 — Inversion de numérotation `2.` / `3.` entre le texte et le diagramme `mermaid` en `§1` — Severity: `Nit`
* **Identifiants sources** : `structural-2-1`
* **Reviewer Lens** : `egm-structural`
* **Affected Scope** : Lignes `101–129` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L101-L129)).
* **Discrepancy Description** : La liste numérote `2. Couche référentielle Git` et `3. Couche déterministe Python`, tandis que le graphe Mermaid numérote `2. CLI Python` et `3. Dépôt Git`.
* **Rationale & Recommendation** : Aligner l'ordre ou les numéros `2.` et `3.` entre la liste et les sous-graphes Mermaid.

---

#### R2-16 — Style hétérogène des renvois internes (`L350`, `L430`, `L436`) — Severity: `Nit`
* **Identifiants sources** : `structural-2-2`
* **Reviewer Lens** : `egm-structural`
* **Affected Scope** : Lignes `350`, `430` et `436` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L350), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L430-L436)).
* **Discrepancy Description** : Mélange d'italique `(cf. *Risques, Limites et Atténuations*)` et de code `` `Plan Technique §6` `` sans liens d'ancrage Markdown `#...`.
* **Rationale & Recommendation** : Utiliser des hyperliens d'ancrage Markdown homogènes pointant vers les en-têtes exacts.

---

#### R2-17 — Granularité de sous-titres `H4` dans `§6` et étiquette uniforme dans `Risques` — Severity: `Nit`
* **Identifiants sources** : `structural-2-3a`, `structural-2-3c`
* **Reviewer Lens** : `egm-structural`
* **Affected Scope** : Lignes `333–357` et `467–473` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L333-L357), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L467-L473)).
* **Discrepancy Description** : `§6` structure ses 5 volets en puces imbriquées là où `§3` utilise `#### 3.1..3.3` ; `## Risques` alterne `**Atténuation dès le MVP** :` et `**Atténuation** :`.
* **Rationale & Recommendation** : Structurer `§6` en `#### 6.1` à `#### 6.5` et uniformiser l'étiquette `**Atténuation** :` dans `## Risques, Limites et Atténuations`.

---

#### R2-18 — Ordre de clôture entre `Améliorations Futures` et `Ressources Complémentaires` et filets `---` — Severity: `Nit`
* **Identifiants sources** : `structural-2-4`
* **Reviewer Lens** : `egm-structural`
* **Affected Scope** : Lignes `7–93` et `474–489` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L474-L489)).
* **Discrepancy Description** : `## Ressources Complémentaires` précède `## Améliorations Futures` au lieu de clore la spécification fonctionnelle, et les séparateurs `---` ne sont pas placés de façon uniforme.
* **Rationale & Recommendation** : Placer `## Améliorations Futures (Feuille de route Phase 2)` avant `## Ressources Complémentaires` et uniformiser les séparateurs `---`.

---

#### R2-19 — Liste non numérotée après annonce de « cinq blocages concrets » dans `## Le Problème` — Severity: `Nit`
* **Identifiants sources** : `structural-2-5`
* **Reviewer Lens** : `egm-structural`
* **Affected Scope** : Lignes `30–36` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L30-L36)).
* **Discrepancy Description** : `### État de l'art` numérote `1..4` ses quatre limites tandis que `### Limites des quatre ébauches` utilise des puces `*` pour ses cinq blocages.
* **Rationale & Recommendation** : Numéroter `1.` à `5.` la liste des cinq blocages.

---

#### R2-20 — Jargon hérité des ébauches supprimées (`evaluator.py`, « 3 moteurs », « 4 piliers ») — Severity: `Nit`
* **Identifiants sources** : `style-2-5`
* **Reviewer Lens** : `egm-style`
* **Affected Scope** : Lignes `36`, `59`, `62`, `372` et `408` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L59-L62), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L372), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L408)).
* **Discrepancy Description** : Mentions de noms de fichiers ou sous-systèmes internes aux brouillons voués à suppression, opaques une fois ces fichiers retirés.
* **Rationale & Recommendation** : Formuler ces exclusions par leur mécanisme fonctionnel général sans citer `evaluator.py` / `eval.yaml` ni « à 3 moteurs / 4 piliers ».

---

#### R2-21 — Précisions terminologiques ponctuelles (Anki vs AnkiWeb, temps verbal et cibles de latence) — Severity: `Nit`
* **Identifiants sources** : `style-2-6`, `style-2-7`
* **Reviewer Lens** : `egm-style`
* **Affected Scope** : Lignes `13`, `23`, `34`, `55`, `99`, `300`, `310`, `346`, `348`, `441`, `450`, `463`, `469`, `471` et `487` ([osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L346-L348), [osarai-mvp-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/osarai-mvp-architecture.md#L463-L487)).
* **Discrepancy Description** : Confusion entre le logiciel libre **Anki** (*FSRS*/*SM-2*) et le service propriétaire **AnkiWeb** (`L487`), cibles `< 50 ms` / `< 60 s` formulées comme faits acquis (`L348`, `L463`), et micro-pléonasmes (« auto-hébergé localement », « découple quatre responsabilités indépendantes », « dès le jour 1 »).
* **Rationale & Recommendation** : Remplacer `AnkiWeb` par `Anki` en `L487`, formuler les latences comme objectifs de dimensionnement et nettoyer ces pléonasmes.
