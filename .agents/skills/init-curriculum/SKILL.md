---
name: init-curriculum
description: Initialiser et découper en thèmes officiels le programme d'une matière du collège (Cycle 3 ou Cycle 4) depuis les PDF ministériels Éduscol sous Licence Ouverte Etalab 2.0, avec validation humaine (HITL).
---

# Compétence `init-curriculum` — Découpage Officiel d'une Matière depuis Éduscol

Utilisez cette procédure séquentielle avec validation humaine (*Human-in-the-Loop*, HITL) une seule fois par couple `(<cycle>, <matiere>)` afin de créer ou mettre à jour `curriculum/sources/bo_manifest.yaml` et `curriculum/<cycle>/<matiere>.yaml`.

Lisez au préalable `AGENTS.md` et `sources.yaml`.

---

## Étape 1 — Découverte des PDF officiels ministériels (*Etalab 2.0*)

1. Exécutez la découverte automatique sur la page sommaire ministérielle du cycle visé (ex. Cycle 4 : `https://eduscol.education.gouv.fr/4362/enseigner-au-cycle-4`, ou une page matière sur `eduscol.education.gouv.fr` / `education.gouv.fr`) :
   ```bash
   uv run osarai sync-bo --discover-url https://eduscol.education.gouv.fr/4362/enseigner-au-cycle-4 --json
   ```
2. **Gestion du filtrage anti-robots (`ExitCode 3` / `HTTP 403` ou `429`)** :
   - Si l'environnement cloud reçoit un code `3` sur `eduscol.education.gouv.fr`, vérifiez les URL directes des *Bulletins Officiels* publiées sur `education.gouv.fr` / `media.eduscol.education.fr` / `eduscol.education.fr` (domaines autorisés par l'adaptateur `eduscol_bo` dans `sources.yaml`), ou demandez à l'humain d'exécuter `sync-bo` depuis son poste local ou de confirmer les URL PDF officielles de la discipline (*Programme consolidé du cycle*, *Attendus de fin d'année* et *Repères annuels de progression*).
3. **Point de contrôle HITL n°1** :
   - Présentez à l'utilisateur la liste courte des documents PDF officiels retenus pour `(<cycle>, <matiere>)` (`title`, `url`, `doc_type`, `publication_date`).
   - Après validation, inscrivez ces entrées dans `curriculum/sources/bo_manifest.yaml` avec `sha256: null` avant le premier téléchargement.

---

## Étape 2 — Téléchargement vérifié et extraction tabulaire hors Git (`pdfplumber`)

1. Lancez la synchronisation et l'extraction tabulaire :
   ```bash
   uv run osarai sync-bo --cycle <cycle> --subject <matiere> --json
   ```
   - Cette commande télécharge chaque PDF hors Git dans `.osarai_tmp/bo_pdfs/`, calcule et inscrit automatiquement son `sha256` dans `curriculum/sources/bo_manifest.yaml`, et produit un fichier Markdown structuré par document (`<idx:02d>-<doc_slug>.md`) dans `.osarai_tmp/bo_texts/<cycle>-<matiere>/` en préservant les tableaux multi-colonnes `5e | 4e | 3e`.
2. Lisez les fichiers `.md` pertinents générés dans `.osarai_tmp/bo_texts/<cycle>-<matiere>/` (en ciblant les pages de la discipline sans charger de documents étrangers).

---

## Étape 3 — Découpage thématique et point de contrôle HITL sur les colonnes `5e / 4e / 3e`

1. Concevez le découpage en unités thématiques autonomes (`themes`) pour `curriculum/<cycle>/<matiere>.yaml` en respectant ces règles :
   - **Granularité d'un contrôle en classe** : chaque thème correspond à une séquence révisable de façon autonome (~1 000 à 2 000 jetons d'attendus et d'exclusions).
   - **Privilégier des thèmes mono-niveau** (`reperes_levels: ["5eme"]`, `["4eme"]` ou `["3eme"]`) chaque fois que les *Repères annuels de progression* ou le programme annuel (ex. *Histoire-Géographie*) affectent clairement le thème à une année précise ; n'utilisez plusieurs niveaux sur un même `theme_slug` que pour une notion véritablement spiralaire.
   - **Exclusions explicites (`scope_exclusions`) obligatoires** : pour chaque thème, listez explicitement les mécanismes, formules ou concepts des niveaux supérieurs (ex. programme de *4ème*/*3ème* ou de *Lycée*) à ne **surtout pas** introduire lors de la rédaction.
   - **Références `bo_sources`** : reportez les URL officielles, dates, `license_spdx: "Etalab-2.0"`, `license_url` et les empreintes `sha256` exactes calculées à l'Étape 2.
2. **Point de contrôle HITL n°2** :
   - Demandez à l'humain de confirmer le découpage thématique (en particulier la bonne répartition des colonnes `5e` / `4e` / `3e` par rapport au PDF officiel et la pertinence des `scope_exclusions`).
3. Écrivez `curriculum/<cycle>/<matiere>.yaml` et validez hors-ligne jusqu'au code `0` :
   ```bash
   uv run osarai validate --json
   ```
