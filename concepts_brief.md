# Osarai MVP: Antigravity-Native French Collège Revision Platform

* **Author:** Severin Ferrand
* **Date:** 2026-11-11

## Overview

Osarai is an open-source, static revision platform for French middle-school (*Collège*) students, starting with real-world test preparation for a 5ème student (Cycle 4) in subjects such as SVT (*La Respiration*, *La Digestion*) and Histoire-Géographie. All study material lives in Git as plain YAML and Markdown files under `CC BY-SA 4.0` (with source code under `Apache-2.0`) and compiles to pre-rendered static HTML pages on GitHub Pages offering course summaries, 4-choice interactive quizzes with explanations, browser flashcards (including masked diagram questions), verified external study links, and client-side error reporting.

Superseding and replacing all four initial repository drafts ([00-global-architecture.md](file:///Users/seburan/Development/osarai/docs/designs/00-global-architecture.md) through [03-static-web-portal.md](file:///Users/seburan/Development/osarai/docs/designs/03-static-web-portal.md)), all AI authoring and multimodal screening of open-licensed Wikimedia Commons diagrams run interactively (Human-in-the-Loop for the MVP) inside Antigravity via versioned workspace skills (`.agents/skills/`) under the author's existing Gemini subscription quota. A single-toolchain, zero-LLM Python CLI (`osarai` managed with `uv`) handles schema validation, license provenance against `sources.yaml`, deterministic ID assignment, link verification, and `Jinja2` + `markdown-it-py` static HTML compilation so GitHub Actions CI and external contributors can validate edits and build the entire website without Antigravity, Node.js, Ruby, or API keys.

## Analysis

### Goldfish Reviewer Status

| Reviewer Lens | Persona | Status |
| :--- | :--- | :--- |
| `egm-design` | Hostile Design Critic | `completed` |
| `egm-codebase-details` | Technical Quality Auditor | `completed` |
| `egm-zoom-out` | Skeptical Architect (YAGNI) | `completed` |
| `egm-comprehension` | Naive Reader & UX Auditor | `completed` |
| `egm-implementation-readiness` | Pragmatic Tech Lead | `completed` |
| `egm-structural` | Structural & Migration Validator | `completed` |
| `egm-inventive-catalyst` | Inventive Catalyst (TRIZ) | `completed` |

### 1. Cycle 4 Multi-Year Themes vs. 5ème Depth and Permanent IDs
* **Contradiction & Migration Risk**: French Cycle 4 (`5ème`–`4ème`–`3ème`) defines multi-year spiral programmes for SVT, Physique-Chimie, Technologie, and Mathématiques (while Histoire-Géographie and Français have strict annual programmes). Existing draft paths (`content/5eme/...`) and IDs (`5e-hg-h1-c001` in [01-ai-pipeline-and-evaluation.md](file:///Users/seburan/Development/osarai/docs/designs/01-ai-pipeline-and-evaluation.md#L120-L124)) hardcode a single grade and chapter number: reclassifying or sharing a theme across Cycle 4 breaks static URLs, browser `localStorage` keys, and Phase 2 Anki `guid` hashes. Conversely, putting uncalibrated themes under `cycle-4/` mixes 3ème *Brevet* biochemistry or algebra into 5ème study sessions. Furthermore, without a persisted sequence counter, deleting the highest-numbered card (`c030`) causes `osarai assign-ids` to reuse `c030` on the next added card, and `quiz.yaml` lacks item IDs needed for error flagging.
* **Suggested Catalog Patterns (*Segmentation* + *Dynamics* + *Preliminary Action*)**:
  * Store themes under cycle-scoped paths (`content/cycle-3/` for 6ème; `content/cycle-4/<subject>/<theme-slug>/` for 5ème–4ème–3ème) with grade- and order-independent IDs for both flashcards (`c4-svt-la-respiration-c0001`) and quiz items (`c4-svt-la-respiration-q0001`), backed by monotonic `last_card_seq` and `last_quiz_seq` high-water marks in `meta.yaml`.
  * Tag themes and items with `reperes_level` (`5eme` | `4eme` | `3eme`, aligned with Éduscol *Repères annuels de progression*) plus explicit `scope_exclusions` in `meta.yaml`. Default the web portal to the student's active grade ceiling (`<= 5ème`) while providing one-keystroke Cycle-wide search and a toggle to reveal higher-grade cards if a teacher goes deeper.
* **Secondary Trade-offs**: Adds a `reperes_level` metadata field alongside `priority` (`essentiel` / `approfondissement`) in `schemas.py` and requires the portal header to announce when higher-grade cards are hidden by default.

### 2. Official Syllabus Reality (`data.education.gouv.fr`) and Human-in-the-Loop Single-Theme Authoring First
* **Infrastructure & YAGNI Risk**:
  * **Upstream data reality**: `data.education.gouv.fr` (`fr-en-programmes-enseignement-2nd-degre`) is only a flat metadata catalog linking to 30-to-100-page Bulletin Officiel / Éduscol PDFs—not a structured JSON API of school themes. Writing a live per-theme syllabus fetcher is wasted code, and reading full BO PDFs on every authoring run burns 50k–100k extra input tokens per theme.
  * **Quota math & premature batching**: Inside Antigravity, every tool call re-bills cumulative prompt context (~250k–500k cumulative quota-counted tokens per 12–15-turn theme). Unattended full-subject batch runs before validating 3–5 themes on real 5ème school tests risk draining interactive quota and regenerating decks once real usage reveals card-format issues.
* **Suggested Catalog Patterns (*Preliminary Action*)**:
  * Download pinned Etalab 2.0 BO and *Repères annuels* PDFs once, extract text locally (`pymupdf` / `pypdf`), and commit static human-verified `curriculum/<cycle>/<subject>.yaml` slices (~1–2k tokens per theme with verbatim expectations and out-of-scope exclusions) instead of runtime syllabus scraping.
  * Defer unattended multi-theme batch orchestration to Phase 2; focus Phase 1 MVP strictly on an interactive, Human-in-the-Loop (HITL) single-theme authoring skill (`.agents/skills/author-theme/SKILL.md`) compressed with coarse Python helper commands so 3–5 real themes can be validated with the target 5ème student first.
* **Secondary Trade-offs**: Committed `curriculum/` YAML requires manual updates when Ministerial decrees change (every few years), and scaling across full subjects waits until Phase 2 batching.

### 3. Grounding Scope Safety and Zero-LLM Pedagogical Validation
* **Contradiction**: Excluding `CC BY-NC-SA` textbooks (*Lelivrescolaire.fr*) leaves Wikipedia FR alongside Vikidia FR and BO slices as grounding sources; Wikipedia science articles introduce Lycée/university concepts that can leak into cards without explicit BO guardrails. Meanwhile, deferring `evaluator.py` ([01-ai-pipeline-and-evaluation.md](file:///Users/seburan/Development/osarai/docs/designs/01-ai-pipeline-and-evaluation.md#L134-L163)) risks discarding its zero-LLM Python checks (Pillar 3 and Pillar 4a).
* **Suggested Catalog Patterns (*Extraction*)**:
  * Move zero-LLM deterministic checks into `osarai validate` on Day 1: 4 unique QCM choices, valid answer index, answer-length ceiling (`<= 250` chars), Cloze non-spoiler check (ensuring hidden Cloze text is not repeated verbatim on the card), and concept coverage—parsed with YAML 1.2 (`ruamel.yaml`) so scientific tokens like `NO` or ratios like `1:20` are not coerced into booleans or base-60 integers by YAML 1.1.
  * Prioritize Vikidia FR + official BO slices (`scope_exclusions`) over Wikipedia FR during HITL single-theme authoring.
* **Secondary Trade-offs**: Strict length lints must separate authoring warnings from hard PR failures so external contributors fixing prose are not blocked.

### 4. Visual Flashcards with CSS Occlusion Masks, SVG Rasterization, and Phase 2 Anki Distribution
* **Contradiction & Compatibility Risk**:
  * **French labels vs. non-spoiler active recall**: Standard French Wikimedia Commons SVT/Geography diagrams print organ or territory names directly on the figure; naturally unlabeled ("mute") variants are rare, and even visible file titles/credits on question fronts give away answers.
  * **SVG screening trap**: Most French Commons diagrams are `.svg` files; Antigravity's file reader loads `.svg` as XML text rather than rendered pixels unless a localized PNG/WebP rasterization (`iiurlwidth=1200&iiurlparam=langfr-1200px` with a Wikimedia-compliant `User-Agent`) is fetched.
  * **Anki flat media & Phase 2 `.apkg` hosting**: Anki's internal `collection.media/` database folder has zero subdirectories regardless of whether `.apkg` files are downloaded from GitHub Pages, GitHub Releases, or AnkiWeb—generic per-theme names like `schema.png` overwrite each other inside the student's local Anki app. Additionally, while AnkiWeb Shared Decks is useful for manual milestone discovery in Phase 2, AnkiWeb provides no public automated upload API for CI/CD and auto-deletes shared decks with low 3-month download counts, whereas GitHub Releases hosts automated CI `.apkg` builds (up to 2 GB per file) without touching GitHub Pages' 1 GB limit.
* **Suggested Catalog Patterns (*Extraction* / *Preliminary Action*)**:
  * Implement **non-destructive percentage CSS occlusion masks** (`occlusions: [{x, y, w, h, label: "?"}]`) in `flashcards.yaml` and `quiz.yaml` so a single French-labeled Wikimedia Commons diagram serves unmasked in `summary.md` and on answer reveals while masking target labels on question fronts (with CC image credits collapsed behind a toggle on question fronts). Include a deterministic raster preview with drawn bounding boxes during HITL authoring (or lightweight dev-mode box coordinate helper) so vision bounding-box drift (2–5%) is caught immediately before commit.
  * Store localized WebP/PNG renderings (`<= 150 KB`) using globally unique flat filenames (`c4-svt-la-respiration--alveole.webp`) referenced via structured `asset_id` fields so Phase 2 `genanki` builds require zero YAML/filename migration (pre-baking masked images or mapping to Anki Image Occlusion notes, publishing automated `.apkg` builds to GitHub Releases and optional manual mega-decks to AnkiWeb).
* **Secondary Trade-offs**: Vision-generated bounding boxes require an aspect-ratio-locked CSS container (`aspect-ratio`) and quick HITL verification so arrows or partial letters are not left exposed.

### 5. Clean-Room CC BY-SA 4.0 Provenance, Commons License Filtering, and Root `LICENSE` Carve-Out
* **Contradiction & Legal Gaps**:
  * **Apache-2.0 §5 override**: Root [LICENSE](file:///Users/seburan/Development/osarai/LICENSE#L130-L136) states all external contributions default to Apache-2.0 unless explicitly carved out; without a `LICENSE-CONTENT` file and `CONTRIBUTING.md` dual-license clause, community PRs to `content/` will not be licensed under `CC BY-SA 4.0`.
  * **Per-asset Commons traps & per-work TASL attribution**: Wikimedia Commons hosts legacy `GFDL-only` and `CC BY-SA 1.0` files incompatible with `CC BY-SA 4.0`, and unmodified embedded media retain their upstream license (`CC0`, `CC BY`, `CC BY-SA 3.0/4.0`). Furthermore, adapting Vikidia (`CC BY-SA 3.0`) or Wikipedia (`CC BY-SA 4.0`) text legally requires per-article attribution on the theme page—not just a repo-root `sources.yaml`.
  * **Context contamination & prompt injection**: If an authoring subagent reads full web pages from `external_link_only` sites (*Lelivrescolaire.fr* `CC BY-NC-SA`, *Lumni*) before writing `summary.md`, non-compatible prose enters its context window. Also, unsanitized wiki `extmetadata` HTML or open-URL fetch flags expose indirect prompt-injection vectors inside pre-approved CLI commands.
* **Suggested Catalog Patterns (*Intermediary* + *Segmentation*)**:
  * Add `LICENSE-CONTENT` (`CC BY-SA 4.0`) and explicit contributor carve-outs in [README.md](file:///Users/seburan/Development/osarai/README.md) and `CONTRIBUTING.md`.
  * Enforce `sources.yaml` mechanically inside Python CLI subcommands: `osarai fetch-grounding` allows only `allow_grounding: true` hosts; `osarai fetch-commons` filters `extmetadata` against an explicit SPDX allowlist (`CC0-1.0`, `Public-domain`, `CC-BY-2.0..4.0`, `CC-BY-SA-2.0..4.0`), strips HTML tags, and writes TASL attribution into `assets.yaml`; and `osarai probe-links` (executed in a separate post-authoring step for `resources.yaml`) returns **only** HTTP status, canonical URL, `<title>`, `<h1>`, and YouTube `oEmbed` author/title—stripping `<body>` prose in Python before stdout enters the agent context. Render `sources_used` and `assets.yaml` TASL credits automatically in every theme page footer.
* **Secondary Trade-offs**: Rejecting `GFDL-only` Commons files narrows available diagrams on niche topics, and header-only link probing gives weaker topical signal when external page titles are generic.

### 6. Child/Family Error-Reporting UX, Python `Jinja2` Pre-Rendered Portal, and Two-Tier CI
* **Contradiction & Usability Gaps**:
  * **12-year-old GitHub login wall & `HTTP 414`**: A 5ème student (~12 years old—below GitHub's 13+ minimum age and France's 15+ GDPR consent age) revising on a tablet or phone has no GitHub session, so `/issues/new` hits a `/login` wall. Additionally, percent-encoded French notes across 10–15 flagged items exceed GitHub's ~6–8 KB GET query limit (`HTTP 414`), and auto-clearing `localStorage` on click loses unsent reports.
  * **Web-only MVP study & build requirements**: With `genanki` deferred, 100% of MVP studying happens in the browser—requiring clean shareable URLs with per-lesson chat preview titles (`og:title`), search-engine indexing, self-hosted local KaTeX (for zero third-party CDN requests under RGPD for minors), `--base-url` support for GitHub Pages project paths, build-time validation forbidding Cloze tags from straddling KaTeX delimiters (`\({{c1::...}}\)`), expansion of multi-cloze notes (`c1`, `c2`) into distinct review cards, and `"À revoir uniquement"` multi-day persistence.
* **Suggested Catalog Patterns (*Inversion* + *Blessing in Disguise* + *Beforehand Cushioning* + *Preliminary Action*)**:
  * **Immediate Local Quarantine + Portable Share Sheet**: Flagging a defective `card_id` or `question_id` immediately hides it from the student's active drill session in versioned `localStorage` (`osarai:v1:...`, keyed by `(item_id, content_hash)` so upstream fixes un-quarantine it automatically). Export via one-tap **"Copier / Partager le signalement"** (`navigator.share` / clipboard Markdown/JSON payload ingested directly by a `fix-flagged-cards` Antigravity skill on the parent's machine) alongside a byte-budgeted (`<= 5,500` bytes) `/issues/new` link for logged-in GitHub users, with manual cart-clear confirmation.
  * **Single-Toolchain Python `Jinja2` Pre-Rendered HTML + Plain Modern CSS/JS Islands (`Option B`)**: `uv run osarai build-site` compiles each theme into a real static `dist/<cycle>/<subject>/<theme>/index.html` page via `Jinja2` + `markdown-it-py` (protecting LaTeX spans) alongside a `< 150 KB` accent-folded `search-index.json`, self-hosted KaTeX assets, and ~350 lines of plain modern browser CSS/JS islands (built using `modern-web-guidance` standards for native `<dialog>`, CSS `aspect-ratio`, dark mode, and accessibility), deployed via `actions/deploy-pages` with zero Node.js or Ruby dependencies.
  * **Two-Tier CI & Full Doc Replacement**: Gate all PRs on fast offline `osarai validate` + `osarai build-site`; run live link checks only when `resources.yaml` or `sources.yaml` changes in a PR plus a weekly scheduled link-rot Issue job; and replace the superseded `docs/designs/00..03` drafts cleanly.
* **Secondary Trade-offs**: Adds ~150–200 lines of `Jinja2` HTML templates and ~80 lines of client-side quarantine/share JS, without a Node framework HMR server (relying on sub-second `osarai build-site` rebuilds instead).

### Ideal Final Result (IFR)
An author creates curriculum-bounded, visually illustrated Collège themes interactively inside Antigravity at zero marginal API cost without non-permissive license leakage; a single Python `uv` command compiles clean, SEO-indexed static HTML pages with zero `node_modules` overhead; a 12-year-old student revises text and occluded diagrams on any mobile or desktop browser with zero accounts and zero third-party tracking, immediately quarantining any bad question and sharing a structured fix payload to a parent in one tap; and every Phase 1 YAML and media file compiles into Phase 2 Anki `.apkg` packages later with zero ID or filename migration.

## Goals vs. Non-Goals

* **In-Scope Goals:**
  * Completely replace the superseded draft design documents (`docs/designs/00..03`) and align [README.md](file:///Users/seburan/Development/osarai/README.md) with the Antigravity-native MVP architecture.
  * Structure content around standalone Cycle-scoped thematic units (piloting with HITL on 3–5 real 5ème themes starting with SVT's *La Respiration* and *La Digestion*) calibrated with `reperes_level` metadata and Cycle-wide accent-folded search.
  * Build an interactive HITL single-theme Antigravity skill (`.agents/skills/author-theme/SKILL.md`) backed by pinned Etalab 2.0 `curriculum/` YAML slices.
  * Enforce clean-room `CC BY-SA 4.0` licensing via `LICENSE-CONTENT`, `sources.yaml` domain/SPDX rules, per-theme/per-asset TASL attribution, and header-only probing for external-link-only resources.
  * Reuse localized Wikimedia Commons diagrams downloaded with flat theme-prefixed filenames and percentage CSS occlusion masks (`occlusions: [{x, y, w, h}]`) for non-spoiler visual questions, verified via HITL preview.
  * Ship a single-toolchain zero-LLM Python CLI (`osarai`) using `uv`, `pydantic`, `ruamel.yaml`, `jinja2`, and `markdown-it-py` for media/link helpers, monotonic ID assignment (`card_id` and `question_id`), deterministic pedagogical/MathJax/Cloze validation, and pre-rendered static HTML compilation.
  * Provide a mobile-first static web portal on GitHub Pages (`actions/deploy-pages`, built following `modern-web-guidance` HTML/CSS/JS standards with self-hosted KaTeX) featuring summaries, 4-choice QCMs, Cloze/Basic/Occluded flashcards (`"À revoir"` persistence), local quarantine of flagged items, and Web Share / clipboard + byte-capped GitHub Issue reporting.

* **Out-of-Scope Non-Goals:**
  * Paid `google-genai` API integration, API key management, or runtime `deep-research` benchmarks in Python.
  * Node.js (`npm` / Astro) or Ruby (Jekyll) build toolchains in the repository.
  * Unattended multi-theme / full-subject batch orchestration (deferred to Phase 2 after HITL pilot validation).
  * Automated 4-pillar LLM-as-a-Judge `/100` scoring (`eval.yaml`) and `--auto-fix` rewrite loops in Phase 1 MVP.
  * `genanki` `.apkg` binary compilation and GitHub Releases / AnkiWeb deck distribution in Phase 1 MVP (deferred to Phase 2, keeping schemas and flat media filenames forward-compatible).
  * Programmatic SVG geometry plotting and generative AI image synthesis in Phase 1 MVP (deferred to Phase 2).
  * Custom backend servers, user accounts, cloud databases, or third-party analytics/CDN scripts.

## Alternatives Weighed

* **Paid Python CLI calling `google-genai` API + 3-engine Deep Research runtime benchmark**: Rejected by author: incurs recurring per-theme API costs and autonomous `deep-research` web browsing cannot be hard-fenced to `CC BY-SA`-compatible domains; replaced by Antigravity skills under existing Gemini subscription quota plus deterministic Python CLI helpers.
* **Unattended full-subject batch orchestration in MVP**: Rejected by author: postponed to next iteration in favor of building and validating a few themes first with Human-in-the-Loop (HITL) single-theme authoring.
* **Scraping proprietary or `CC BY-NC-SA` educational sites with attribution and an opt-out takedown form**: Rejected by author: notice-and-takedown does not shield a publisher adapting protected third-party content under French copyright law, and `CC BY-NC-SA` (*Lelivrescolaire.fr*) cannot legally be remixed into `CC BY-SA 4.0`; replaced by strict `sources.yaml` separation between `CC BY-SA`-compatible grounding/media sources and outbound-link-only sites.
* **Raw LLM SVG generation or generative image models for maps and anatomy in MVP**: Rejected by author: high risk of geometric coordinate errors and hallucinated historical borders or anatomical labels; deferred in favor of open-licensed Wikimedia Commons assets with declarative CSS occlusion masks.
* **Restricting visual question fronts strictly to naturally unlabeled Wikimedia Commons images**: Rejected by author: unlabeled French Collège diagrams are scarce on Wikimedia Commons; replaced by percentage CSS occlusion masks over French-labeled diagrams.
* **Sequential `Chapitre 1, 2, 3` grade-locked curriculum tree**: Rejected by author: French Cycle 4 programmes span 3 years (`5ème`–`4ème`–`3ème`) and leave chapter sequencing to teachers; replaced by standalone thematic units searchable across Cycle 4.
* **Automated 4-pillar LLM-as-a-Judge evaluator (`/100`) and `--auto-fix` loop in MVP**: Rejected by author: premature before testing real cards with a 5ème student; replaced in MVP by zero-LLM Python structural/pedagogical validation plus live parent-daughter testing and in-app card flagging.
* **Day-1 `genanki` `.apkg` compilation in MVP**: Rejected by author: initial study sessions with the target 5ème student use the web portal first; `.apkg` builds (distributed via GitHub Releases for automated updates + manual milestone uploads to AnkiWeb) are deferred to Phase 2 while preserving monotonic IDs, flat media naming, and Cloze/MathJax rules from Day 1.
* **Jekyll (Ruby + Liquid static site generator)**: Rejected by author: requires a Ruby toolchain alongside Python and Anki's `{{c1::...}}` Cloze syntax collides directly with Liquid's `{{ ... }}` template delimiters.
* **Single-page blank HTML shell rendering JSON client-side (`Option A`)**: Rejected by author: loses clean per-lesson URLs without `404.html` workarounds, chat link preview titles (`og:title`), and per-lesson Google search indexing; replaced by Python `Jinja2` pre-rendered HTML (`Option B`).
* **Dual-toolchain Python CLI + Astro / Node.js (`Option C`)**: Rejected by author: introduces a second language runtime (`Node.js` / `npm` / `node_modules`) and duplicate TypeScript schema maintenance alongside Python `uv` and `schemas.py`; replaced by Python-only `Jinja2` pre-rendered HTML + plain modern CSS/JS islands (`Option B`).
* **Patching existing `docs/designs/00..03` incrementally in place**: Rejected by author: existing drafts are pervasive paid-SDK artifacts; replaced completely by the new specification.

## Key Decisions & Staging for Next Steps

### Decisions Locked During Brainstorming
1. **Complete Design Replacement**: Replace `docs/designs/00..03` cleanly rather than patching legacy paid-API docs in place.
2. **HITL Single-Theme MVP Scope**: Postpone unattended batch orchestration to Phase 2; build and field-test 3–5 themes interactively with HITL first.
3. **Visual Occlusion Masks + Flat Media Invariants**: Use declarative percentage CSS occlusion masks (`occlusions: [{x, y, w, h}]`) with HITL bounding-box preview on localized Wikimedia Commons images stored under globally unique flat filenames (`<cycle>-<subject>-<theme>--<asset>`) so Phase 2 Anki imports never collide in `collection.media/` (with Phase 2 `.apkg` hosting split between automated GitHub Releases and manual milestone AnkiWeb uploads).
4. **Dual Licensing Carve-Out**: Code under `Apache-2.0` ([LICENSE](file:///Users/seburan/Development/osarai/LICENSE)); pedagogical content under `CC BY-SA 4.0` (`LICENSE-CONTENT`), with unmodified embedded Commons media retaining upstream SPDX licenses and per-page TASL attribution.
5. **Zero-LLM Python CLI + Antigravity Authoring Split**: Fixed `uv run osarai <subcommand>` grammar for sandbox prefix pre-approval, offline PR CI validation, and non-Antigravity contributor ergonomics.
6. **Python-Only Pre-Rendered Static Portal (`Option B`)**: `uv run osarai build-site` compiles pre-rendered static HTML pages per theme via `Jinja2` + `markdown-it-py` plus a `< 150 KB` accent-folded `search-index.json`, self-hosted KaTeX, and plain modern CSS/JS islands following `modern-web-guidance`, deployed via `actions/deploy-pages`.

### Staging for `/egm-draft`
All open architectural questions are resolved. `/egm-draft` should formalize:
1. Repository layout, `LICENSE-CONTENT` / `CONTRIBUTING.md` dual-license carve-outs, and removal/replacement of legacy `docs/designs/00..03`.
2. Exact Pydantic (`schemas.py`) data contracts for `curriculum/<cycle>/<subject>.yaml`, `sources.yaml`, `meta.yaml`, `assets.yaml`, `flashcards.yaml` (including `occlusions` and Cloze/KaTeX rules), `quiz.yaml`, and `resources.yaml`.
3. `osarai` CLI subcommands (`fetch-grounding`, `fetch-commons`, `probe-links`, `assign-ids`, `validate`, `build-site`) with typed exit codes and `--json` output.
4. Workspace Antigravity skills (`.agents/skills/author-theme/SKILL.md` and `.agents/skills/fix-flagged-cards/SKILL.md`).
5. `Jinja2` page templates, vanilla CSS/JS islands (Quiz, 3D/Cloze/Occluded Flashcards, Cycle-wide Search, Local Quarantine + Share/GitHub Issue Drawer), and two-tier GitHub Actions (`ci.yml`, `deploy.yml`, weekly link-rot check).
