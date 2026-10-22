# 02 — Conception et Compilation des Decks Anki Hiérarchiques (`genanki`)

## 1. Cycle de Vie des Notes Anki : En amont vs Site Statique

> [!IMPORTANT]
> **Principe fondamental : Toutes les notes et tous les paquets `.apkg` sont générés et compilés en amont par notre pipeline de développement et d'intégration continue (CI/CD), jamais par l'IA à la volée côté visiteur.**

Voici les **3 étapes exactes** du cycle de vie d'une carte Anki :

1. **Étape A — Génération du contenu source (en développement via notre CLI Python)** :
   - Lorsque nous lançons la commande de génération pour un chapitre, le pipeline IA crée le fichier `content/<niveau>/<matiere>/<chapitre>/flashcards.yaml`.
   - Ce fichier YAML est versionné dans Git. Il constitue la « Source de Vérité » lisible par l'humain : n'importe quel contributeur peut corriger une faute ou ajouter une carte via une simple Pull Request GitHub.

2. **Étape B — Compilation statique des fichiers `.apkg` (en local ou via GitHub Actions)** :
   - À chaque commit sur GitHub (ou via la commande locale `build-anki`), le module Python `anki_builder.py` (basé sur la bibliothèque **`genanki`**) parcourt tous les fichiers `flashcards.yaml` du dépôt et **compile statiquement les fichiers binaires `.apkg`**.
   - Les fichiers `.apkg` compilés sont placés dans le dossier `dist/decks/` du site statique (et dans les *GitHub Releases*).

3. **Étape C — Téléchargement par l'utilisateur final depuis le Site Web** :
   - Sur le site web (GitHub Pages), l'élève ou le parent clique simplement sur un bouton **« Télécharger le deck Anki (.apkg) »** qui télécharge instantanément le fichier pré-compilé à l'Étape B.
   - Il l'ouvre dans Anki (PC/Mac), AnkiDroid (Android) ou AnkiMobile (iOS).

---

## 2. Organisation Hiérarchique des Paquets (`::`)

Anki organise nativement les paquets sous forme d'arbre pliable grâce au séparateur `::`. Notre compilateur `anki_builder.py` nomme chaque deck selon la convention stricte :

```text
Collège
└── 5ème
    ├── Histoire-Géographie
    │   ├── H1 - Chrétienté et Islam (VIe-XIIIe siècle)
    │   ├── H2 - Société, Église et pouvoir politique dans l'Occident féodal
    │   └── G1 - La question démographique et l'inégal développement
    └── SVT
        ├── Thème 1 - La planète Terre, l'environnement et l'action humaine
        └── Thème 2 - Le vivant et son évolution (Nutrition et organisation des êtres vivants)
```

### Les 3 Granularités de Fichiers `.apkg` Distribués

Pour répondre à tous les usages, le pipeline génère automatiquement **3 niveaux de paquets `.apkg`** :
1. **Deck par Chapitre** (`College_5eme_Histoire-Geo_H1-Chretiente-et-Islam.apkg`) : Idéal pour réviser le contrôle de la semaine suivante.
2. **Deck par Matière** (`College_5eme_Histoire-Geographie.apkg`) : Regroupe tous les chapitres de l'année pour une matière donnée.
3. **Méga-Deck par Niveau** (`College_5eme_Complet.apkg`) : Regroupe toutes les matières et tous les chapitres de la classe de 5ème en un seul fichier `.apkg` tout en conservant toute l'arborescence interne `Collège::5ème::<Matière>::<Chapitre>`.

---

## 3. Identifiants Déterministes : Mises à jour sans Perte d'Historique

### Le Problème Classique d'Anki
Si l'on régénère un fichier `.apkg` parce qu'on a corrigé une coquille dans une carte ou ajouté 5 nouvelles cartes au chapitre, Anki risque soit d'écraser la progression de l'élève, soit de créer des cartes en doublon si les identifiants changent d'un build à l'autre.

### Notre Solution Technique dans `anki_builder.py`
1. **ID stable par carte dans le YAML** :
   Chaque carte dans `flashcards.yaml` possède un identifiant unique immuable (ex: `id: "5e-hg-h1-c001"`).
2. **Calcul déterministe du `guid` de la note Anki** :
   Au lieu de laisser `genanki` générer un identifiant aléatoire, nous surchargeons la propriété `guid` de `genanki.Note` via un hachage cryptographique stable :
   ```python
   import hashlib
   import genanki

   def deterministic_guid(card_id: str) -> str:
       return genanki.guid_for("osarai-v1", card_id)

   def deterministic_deck_id(deck_hierarchy_name: str) -> int:
       # Entier positif sur 31 bits dérivé du chemin complet du deck
       digest = hashlib.sha256(deck_hierarchy_name.encode("utf-8")).digest()
       return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
   ```
3. **Bénéfice pour l'élève** :
   Lorsqu'un élève ré-importe une version mise à jour du fichier `.apkg` dans son application Anki :
   - Les cartes existantes voient leur texte mis à jour **sans perdre leurs intervalles de répétition espacée**.
   - Les nouvelles cartes sont ajoutées automatiquement au bon sous-paquet.

---

## 4. Modèles de Notes (`genanki.Model`) & Design Visuel des Cartes

Nous définissons deux modèles de notes Anki (`genanki.Model` avec IDs fixes) dotés d'une feuille de style CSS moderne (compatible mode clair et mode sombre d'Anki) et du support natif **MathJax** (`\(...\)` et `\[...\]`) :

1. **Modèle « Collège - Question / Réponse » (`basic`)** :
   - **Recto** :
     - Bandeau supérieur : `Niveau • Matière • Chapitre` + Badge de priorité (`Essentiel` ou `Approfondissement`).
     - Question claire (avec formules MathJax éventuelles).
   - **Verso** :
     - Réponse concise mise en valeur.
     - Encadré *« Pour bien comprendre / Moyen mnémotechnique »* (`explanation`).
     - Tags Anki : `#5eme`, `#histoire-geographie`, `#essentiel` (permettant à l'élève de filtrer dans Anki s'il veut réviser uniquement les cartes `#essentiel` la veille d'un contrôle).

2. **Modèle « Collège - Texte à trous » (`cloze`)** :
   - Utilise le type natif `genanki.Model.CLOZE`.
   - Idéal pour mémoriser des définitions exactes, des théorèmes ou des dates (ex: `En {{c1::800}}, {{c2::Charlemagne}} est couronné empereur d'Occident à Rome par le pape.`).

