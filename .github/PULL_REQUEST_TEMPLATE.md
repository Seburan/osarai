## Résumé des modifications

<!-- Décrivez brièvement l'objet de cette Pull Request (correction pédagogique, nouveau thème, évolution de l'outillage Python, etc.). -->

## Vérifications effectuées

- [ ] `uv run osarai validate --against-ref origin/main` passe avec le code `0` (ou correction d'identifiant guidée par la CI).
- [ ] Aucun identifiant existant (`id`) n'a été renommé ni réattribué (tout élément supprimé a été déplacé dans `meta.yaml -> retired_ids` sans décrémenter `last_card_seq` / `last_quiz_seq`).
- [ ] Les contenus ajoutés sous `content/` respectent le programme officiel et les `scope_exclusions` de `curriculum/`, et ne proviennent d'aucune source propriétaire ou `CC BY-NC-SA`.

## Déclaration de Double Licence (Obligatoire)

- [ ] **Je confirme les conditions de licence de ma contribution** :
  - Toute contribution portant sur le code, les tests, les gabarits, les compétences IA ou les workflows (`src/`, `tests/`, `.agents/`, `.claude/`, `.github/`, `pyproject.toml`, `sources.yaml`) est soumise sous licence **[Apache-2.0](../LICENSE)**.
  - **Par dérogation expresse à la section 5 de [`LICENSE`](../LICENSE) (`Apache-2.0`)**, toute création ou modification portant sur `content/` et `curriculum/` est soumise sous la licence **[Creative Commons Attribution - Partage dans les Mêmes Conditions 4.0 International (`CC BY-SA 4.0`)](../LICENSE-CONTENT)** (les illustrations tierces sous `content/**/assets/` conservant leur licence libre d'origine documentée dans `assets.yaml`).
