"""Modèles de données `Pydantic v2` et validateurs déterministes (YAML 1.2, LaTeX, Cloze, TASL)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Annotated, Literal
import unicodedata
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

CYCLE_CODE_MAP: dict[str, str] = {
    "cycle-3": "c3",
    "cycle-4": "c4",
}

SUBJECT_CODE_MAP: dict[str, str] = {
    "svt": "svt",
    "histoire-geographie": "hg",
    "mathematiques": "maths",
    "physique-chimie": "pc",
    "francais": "fr",
    "anglais": "en",
    "technologie": "techno",
}

GRADE_ORDER: dict[str, int] = {
    "6eme": 0,
    "5eme": 1,
    "4eme": 2,
    "3eme": 3,
}

CycleName = Literal["cycle-3", "cycle-4"]
SubjectName = Literal[
    "svt",
    "histoire-geographie",
    "mathematiques",
    "physique-chimie",
    "francais",
    "anglais",
    "technologie",
]
SubjectCode = Literal["svt", "hg", "maths", "pc", "fr", "en", "techno"]
GradeLevel = Literal["6eme", "5eme", "4eme", "3eme"]
QaStatus = Literal["hitl_verified", "field_tested"]
CardPriority = Literal["essentiel", "approfondissement"]
CardType = Literal["basic", "cloze"]
CardAssetRole = Literal["front_occluded", "back_reference", "none"]
QuizAssetRole = Literal["front_occluded", "explanation_reference", "none"]
QuizDifficulty = Literal["facile", "moyen", "difficile"]
ResourceType = Literal["video", "cours", "exercice", "article"]
OcclusionRole = Literal["target", "mask"]
SourceAdapter = Literal["eduscol_bo", "mediawiki_text", "wikimedia_commons", "outbound_probe"]
FeedbackItemType = Literal["flashcard", "quiz"]
FeedbackReason = Literal[
    "erreur_factuelle",
    "hors_programme",
    "formulation_ambigue",
    "masque_decale",
    "coquille",
    "autre",
]
FeedbackStatus = Literal["open", "resolved", "retired"]

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{8}$")
CARD_ID_RE = re.compile(r"^c[34]-[a-z]+-[a-z0-9-]+-c(\d{4,})$")
QUIZ_ID_RE = re.compile(r"^c[34]-[a-z]+-[a-z0-9-]+-q(\d{4,})$")
FEEDBACK_ITEM_ID_RE = re.compile(r"^c[34]-[a-z]+-[a-z0-9-]+-(?:c\d{4,}(?:#c[1-9]\d*)?|q\d{4,})$")
ASSET_FILENAME_RE = re.compile(
    r"^(c[34])-([a-z]+)-([a-z0-9-]+)--([a-z0-9]+(?:-[a-z0-9]+)*)\.(webp|png)$"
)
YOUTUBE_WATCH_RE = re.compile(r"^https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})$")
RAW_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?>|<!--")
CE_MACRO_RE = re.compile(r"\\ce\s*\{")
INLINE_CODE_RE = re.compile(r"(`+)([^`]*?)\1")
FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
WHITESPACE_RE = re.compile(r"\s+")

SlugStr = Annotated[str, Field(pattern=SLUG_RE)]


@dataclass(frozen=True)
class ClozeToken:
    """Représentation analysée d'un segment `{{cN::answer[::hint]}}`."""

    index: int
    answer: str
    hint: str | None
    start: int
    end: int


def normalize_search_text(text: str) -> str:
    """Replie la casse, les ligatures `œ`/`æ`, les apostrophes et les diacritiques Unicode."""
    folded = (
        text.lower()
        .replace("œ", "oe")
        .replace("æ", "ae")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
    )
    decomposed = unicodedata.normalize("NFKD", folded)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return WHITESPACE_RE.sub(" ", without_marks).strip()


def normalize_alnum_token(text: str) -> str:
    """Normalisation alphanumérique compacte utilisée pour l'anti-divulgation des badges."""
    folded = normalize_search_text(text)
    return re.sub(r"[^a-z0-9]+", "", folded)


def normalize_hostname(url_or_domain: str) -> str:
    """Extrait ou normalise un nom d'hôte en minuscules sans préfixe `www.`."""
    candidate = url_or_domain.strip().lower()
    if "://" in candidate:
        parsed = urlparse(candidate)
        host = parsed.hostname or ""
    else:
        host = candidate.split("/")[0].split(":")[0]
    if host.startswith("www."):
        return host[4:]
    return host


def normalize_channel_url(url: str) -> str:
    """Normalise une URL canonique de chaîne YouTube pour comparaison insensible à la casse."""
    parsed = urlparse(url.strip())
    host = normalize_hostname(url)
    path = parsed.path.rstrip("/")
    return f"https://{host}{path}".lower()


def _strip_code_spans(text: str, *, allow_fenced: bool = False) -> str:
    cleaned = FENCED_CODE_RE.sub(" ", text) if allow_fenced else text
    return INLINE_CODE_RE.sub(" ", cleaned)


def validate_no_raw_html(text: str, *, allow_fenced: bool = False) -> None:
    """Rejette toute balise HTML brute hors blocs/spans de code Markdown."""
    target = _strip_code_spans(text, allow_fenced=allow_fenced)
    match = RAW_HTML_TAG_RE.search(target)
    if match:
        raise ValueError(
            f"HTML brut interdit ({match.group(0)!r}) ; utilisez uniquement Markdown et LaTeX."
        )


def _check_latex_braces_balanced(expr: str) -> None:
    depth = 0
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                raise ValueError(f"Accolade fermante `}}` surnuméraire dans la formule `{expr}`.")
        i += 1
    if depth != 0:
        raise ValueError(f"Accolades `{{...}}` déséquilibrées dans la formule `{expr}`.")


def validate_latex_fragment(text: str, *, allow_block: bool = True, allow_fenced: bool = False) -> None:
    """Vérifie l'absence de `\\ce{...}` et l'équilibre strict de `\\(...\\)`, `\\[...\\]` et `{...}`."""
    target = _strip_code_spans(text, allow_fenced=allow_fenced)
    if CE_MACRO_RE.search(target):
        raise ValueError(
            "La macro mhchem `\\ce{...}` est interdite ; utilisez `\\text{...}` "
            "(ex. `\\text{CO}_2`)."
        )

    i = 0
    mode: str | None = None
    math_start = 0
    while i < len(target):
        two = target[i : i + 2]
        if two == "\\\\":
            i += 2
            continue
        if two == "\\(":
            if mode is not None:
                raise ValueError("Délimiteur `\\(` imbriqué ou précédent délimiteur non refermé.")
            mode = "inline"
            math_start = i + 2
            i += 2
            continue
        if two == "\\)":
            if mode != "inline":
                raise ValueError("Délimiteur fermant `\\)` sans `\\(` correspondant.")
            _check_latex_braces_balanced(target[math_start:i])
            mode = None
            i += 2
            continue
        if two == "\\[":
            if not allow_block:
                raise ValueError(
                    "Les formules bloc `\\[...\\]` sont interdites dans ce champ ; "
                    "utilisez `\\(...\\)`."
                )
            if mode is not None:
                raise ValueError("Délimiteur `\\[` imbriqué ou précédent délimiteur non refermé.")
            mode = "block"
            math_start = i + 2
            i += 2
            continue
        if two == "\\]":
            if mode != "block":
                raise ValueError("Délimiteur fermant `\\]` sans `\\[` correspondant.")
            _check_latex_braces_balanced(target[math_start:i])
            mode = None
            i += 2
            continue
        i += 1

    if mode == "inline":
        raise ValueError("Délimiteur mathématique `\\(` non refermé par `\\)`.")
    if mode == "block":
        raise ValueError("Délimiteur mathématique `\\[` non refermé par `\\]`.")


def parse_cloze_tokens(text: str) -> list[ClozeToken]:
    """Analyse et valide les jetons `{{cN::réponse[::indice]}}` d'une chaîne."""
    tokens: list[ClozeToken] = []
    i = 0
    header_re = re.compile(r"\{\{c([1-9]\d*)::")
    while i < len(text):
        open_pos = text.find("{{", i)
        if open_pos == -1:
            break
        match = header_re.match(text, open_pos)
        if not match:
            raise ValueError(
                f"Balise `{{{{` mal formée à la position {open_pos} ; "
                "attendu `{{cN::réponse}}` avec N >= 1."
            )
        idx = int(match.group(1))
        cursor = match.end()
        brace_depth = 0
        close_pos: int | None = None
        while cursor < len(text):
            if text[cursor] == "\\" and cursor + 1 < len(text):
                cursor += 2
                continue
            if text[cursor] == "{":
                brace_depth += 1
                cursor += 1
                continue
            if text[cursor] == "}":
                if brace_depth > 0:
                    brace_depth -= 1
                    # Détecter `}}}` sans espace de sécurité lorsque la réponse finit par `}`
                    if brace_depth == 0 and text[cursor + 1 : cursor + 3] == "}}":
                        raise ValueError(
                            "Ajoutez un espace avant `}}` lorsque le segment Cloze "
                            "se termine par `}` (ex. `{{c1::\\frac{1}{2} }}`)."
                        )
                    cursor += 1
                    continue
                if text[cursor : cursor + 2] == "}}":
                    close_pos = cursor
                    break
                raise ValueError("Accolade `}` isolée invalide dans une balise Cloze.")
            cursor += 1

        if close_pos is None:
            raise ValueError(f"Balise Cloze `{{{{c{idx}::` non refermée par `}}}}`.")

        body = text[match.end() : close_pos]
        parts = body.split("::", 1)
        answer = parts[0]
        hint = parts[1] if len(parts) == 2 else None
        if not answer.strip():
            raise ValueError(f"La réponse de la balise `{{{{c{idx}::...}}}}` ne peut pas être vide.")
        if hint is not None and "::" in hint:
            raise ValueError(
                f"Trop de séparateurs `::` dans `{{{{c{idx}::...}}}}` (un seul indice autorisé)."
            )
        tokens.append(
            ClozeToken(
                index=idx,
                answer=answer,
                hint=hint,
                start=open_pos,
                end=close_pos + 2,
            )
        )
        i = close_pos + 2

    return tokens


def validate_https_clean_url(url: str, *, forbid_trackers: bool = True) -> str:
    """Vérifie le schéma `https://`, la présence d'un hôte et l'absence de traceurs `utm_*`/`fbclid`."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"URL HTTPS valide requise (reçu : {url!r}).")
    if forbid_trackers and parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        bad = [k for k in params if k.lower().startswith("utm_") or k.lower() == "fbclid"]
        if bad:
            raise ValueError(
                f"Paramètres de pistage interdits ({', '.join(sorted(bad))}) dans {url!r}."
            )
    return cleaned


class StrictModel(BaseModel):
    """Modèle de base strict interdisant tout champ inconnu."""

    model_config = ConfigDict(extra="forbid")


class DomainRule(StrictModel):
    """Règle d'autorisation par domaine dans `sources.yaml`."""

    domain: str
    allow_grounding: bool
    allow_embed_media: bool
    adapter: SourceAdapter

    @field_validator("domain")
    @classmethod
    def _check_domain(cls, value: str) -> str:
        norm = normalize_hostname(value)
        if not norm or "/" in value or " " in value or value != norm:
            raise ValueError(
                f"Nom de domaine canonique sans `www.` ni chemin requis (reçu : {value!r})."
            )
        return norm


class SourcesPolicy(StrictModel):
    """Contrat de `sources.yaml` (`§3.1`)."""

    schema_version: Literal[1]
    allowed_licenses: list[str] = Field(min_length=1)
    grounding_and_media_sources: list[DomainRule] = Field(min_length=1)
    outbound_only_sources: list[DomainRule] = Field(min_length=1)
    allowed_youtube_channel_urls: list[str] = Field(min_length=1)

    @field_validator("allowed_youtube_channel_urls")
    @classmethod
    def _check_youtube_channels(cls, urls: list[str]) -> list[str]:
        for u in urls:
            validate_https_clean_url(u)
            if normalize_hostname(u) != "youtube.com":
                raise ValueError(f"URL de chaîne YouTube invalide : {u!r}.")
        return urls

    @model_validator(mode="after")
    def _check_outbound_flags(self) -> SourcesPolicy:
        seen: set[str] = set()
        for rule in [*self.grounding_and_media_sources, *self.outbound_only_sources]:
            if rule.domain in seen:
                raise ValueError(f"Domaine dupliqué dans `sources.yaml` : {rule.domain!r}.")
            seen.add(rule.domain)
        for rule in self.outbound_only_sources:
            if rule.allow_grounding or rule.allow_embed_media:
                raise ValueError(
                    f"`outbound_only_sources` ne peut activer grounding/media ({rule.domain!r})."
                )
        return self

    def find_domain_rule(self, url_or_domain: str) -> DomainRule | None:
        """Recherche une règle exacte ou par sous-domaine `*.<domain>`."""
        host = normalize_hostname(url_or_domain)
        all_rules = [*self.grounding_and_media_sources, *self.outbound_only_sources]
        for rule in all_rules:
            if host == rule.domain:
                return rule
        for rule in all_rules:
            if host.endswith(f".{rule.domain}"):
                return rule
        return None

    def is_allowed_resource_domain(self, url_or_domain: str) -> bool:
        """Indique si un domaine est autorisé dans `resources.yaml`."""
        host = normalize_hostname(url_or_domain)
        for rule in self.outbound_only_sources:
            if host == rule.domain or host.endswith(f".{rule.domain}"):
                return True
        for rule in self.grounding_and_media_sources:
            if rule.allow_grounding and (host == rule.domain or host.endswith(f".{rule.domain}")):
                return True
        return False

    def is_allowed_youtube_channel(self, channel_url: str) -> bool:
        """Vérifie sans sensibilité à la casse l'appartenance d'une chaîne YouTube à la liste blanche."""
        target = normalize_channel_url(channel_url)
        allowed = {normalize_channel_url(u) for u in self.allowed_youtube_channel_urls}
        return target in allowed


class BoDocumentEntry(StrictModel):
    """Entrée d'un document PDF ministériel dans `bo_manifest.yaml`."""

    title: str = Field(min_length=1)
    url: str
    doc_type: Literal["programme", "attendus", "reperes", "ressource"] = "programme"
    publication_date: date
    sha256: str | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return validate_https_clean_url(value)

    @field_validator("sha256")
    @classmethod
    def _check_sha(cls, value: str | None) -> str | None:
        if value is not None and not SHA256_RE.match(value):
            raise ValueError("`sha256` doit comporter 64 caractères hexadécimaux minuscules.")
        return value


class BoSubjectEntry(StrictModel):
    """Groupe de documents BO par `(cycle, subject)` dans `bo_manifest.yaml`."""

    cycle: CycleName
    subject: SubjectName
    documents: list[BoDocumentEntry] = Field(min_length=1)


class BoManifest(StrictModel):
    """Contrat de `curriculum/sources/bo_manifest.yaml`."""

    schema_version: Literal[1]
    subjects: list[BoSubjectEntry] = Field(min_length=1)


class BoSourceRef(StrictModel):
    """Référence de source officielle BO dans `curriculum/<cycle>/<matiere>.yaml`."""

    title: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    publication_date: date
    url: str
    license_spdx: Literal["Etalab-2.0"]
    license_url: str
    sha256: str = Field(pattern=SHA256_RE)

    @field_validator("url", "license_url")
    @classmethod
    def _check_urls(cls, value: str) -> str:
        return validate_https_clean_url(value)


class CurriculumTheme(StrictModel):
    """Tranche thématique officielle d'une matière dans `curriculum/`."""

    theme_slug: SlugStr
    title: str = Field(min_length=1)
    macro_theme_bo: str = Field(min_length=1)
    reperes_levels: list[GradeLevel] = Field(min_length=1)
    attendus_bo: list[str] = Field(min_length=1)
    scope_exclusions: list[str] = Field(min_length=1)


class CurriculumFile(StrictModel):
    """Contrat de `curriculum/<cycle>/<matiere>.yaml` (`§3.2`)."""

    schema_version: Literal[1]
    cycle: CycleName
    subject: SubjectName
    subject_code: SubjectCode
    subject_label: str = Field(min_length=1)
    bo_sources: list[BoSourceRef] = Field(min_length=1)
    themes: list[CurriculumTheme] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_subject_and_unique_themes(self) -> CurriculumFile:
        expected_code = SUBJECT_CODE_MAP[self.subject]
        if self.subject_code != expected_code:
            raise ValueError(
                f"`subject_code` invalide pour {self.subject!r} : attendu {expected_code!r}."
            )
        seen: set[str] = set()
        for theme in self.themes:
            if theme.theme_slug in seen:
                raise ValueError(f"`theme_slug` dupliqué dans le programme : {theme.theme_slug!r}.")
            seen.add(theme.theme_slug)
            if self.cycle == "cycle-3" and any(lvl != "6eme" for lvl in theme.reperes_levels):
                raise ValueError("Un thème de `cycle-3` ne peut cibler que `6eme`.")
            if self.cycle == "cycle-4" and "6eme" in theme.reperes_levels:
                raise ValueError("Un thème de `cycle-4` ne peut pas cibler `6eme`.")
        return self


class ConceptEntry(StrictModel):
    """Concept clé d'un thème dans `meta.yaml`."""

    concept_id: SlugStr
    label: str = Field(min_length=1)
    reperes_level: GradeLevel


class TextSourceCredit(StrictModel):
    """Crédit TASL complet d'une source textuelle d'appui dans `meta.yaml -> sources_used`."""

    title: str = Field(min_length=1)
    url: str
    source_domain: str
    authors_or_history_url: str = Field(min_length=1)
    license_spdx: str = Field(min_length=1)
    license_url: str
    revision_or_date: str = Field(min_length=1)

    @field_validator("url", "license_url")
    @classmethod
    def _check_urls(cls, value: str) -> str:
        return validate_https_clean_url(value)

    @field_validator("source_domain")
    @classmethod
    def _check_source_domain(cls, value: str) -> str:
        return normalize_hostname(value)


class ThemeMeta(StrictModel):
    """Contrat de `content/<cycle>/<matiere>/<theme_slug>/meta.yaml` (`§3.3.1`)."""

    schema_version: Literal[1]
    cycle: CycleName
    subject: SubjectName
    subject_code: SubjectCode
    theme_slug: SlugStr
    title: str = Field(min_length=1)
    reperes_levels: list[GradeLevel] = Field(min_length=1)
    scope_exclusions: list[str] = Field(min_length=1)
    qa_status: QaStatus
    key_concepts: list[ConceptEntry] = Field(min_length=1)
    sources_used: list[TextSourceCredit] = Field(default_factory=list)
    last_card_seq: int = Field(ge=0)
    last_quiz_seq: int = Field(ge=0)
    retired_ids: list[str] = Field(default_factory=list)

    @property
    def id_prefix(self) -> str:
        """Préfixe canonique `<code-cycle>-<subject_code>-<theme_slug>`."""
        return f"{CYCLE_CODE_MAP[self.cycle]}-{self.subject_code}-{self.theme_slug}"

    @model_validator(mode="after")
    def _validate_meta_invariants(self) -> ThemeMeta:
        expected_code = SUBJECT_CODE_MAP[self.subject]
        if self.subject_code != expected_code:
            raise ValueError(
                f"`subject_code` invalide pour {self.subject!r} : attendu {expected_code!r}."
            )
        seen_concepts: set[str] = set()
        for concept in self.key_concepts:
            if concept.concept_id in seen_concepts:
                raise ValueError(f"`concept_id` dupliqué dans `meta.yaml` : {concept.concept_id!r}.")
            seen_concepts.add(concept.concept_id)
            if concept.reperes_level not in self.reperes_levels:
                raise ValueError(
                    f"Le concept {concept.concept_id!r} ({concept.reperes_level}) "
                    f"n'appartient pas à `meta.reperes_levels` ({self.reperes_levels})."
                )

        prefix = self.id_prefix
        seen_retired: set[str] = set()
        for rid in self.retired_ids:
            if rid in seen_retired:
                raise ValueError(f"Identifiant dupliqué dans `retired_ids` : {rid!r}.")
            seen_retired.add(rid)
            card_match = CARD_ID_RE.match(rid)
            quiz_match = QUIZ_ID_RE.match(rid)
            if card_match and rid.startswith(f"{prefix}-c"):
                seq = int(card_match.group(1))
                if seq < 1 or seq > self.last_card_seq:
                    raise ValueError(
                        f"`retired_ids` contient {rid!r} (> last_card_seq={self.last_card_seq})."
                    )
            elif quiz_match and rid.startswith(f"{prefix}-q"):
                seq = int(quiz_match.group(1))
                if seq < 1 or seq > self.last_quiz_seq:
                    raise ValueError(
                        f"`retired_ids` contient {rid!r} (> last_quiz_seq={self.last_quiz_seq})."
                    )
            else:
                raise ValueError(
                    f"Identifiant retiré {rid!r} invalide pour le préfixe du thème `{prefix}`."
                )
        return self


class AssetEntry(StrictModel):
    """Entrée d'illustration locale dans `assets.yaml` (`§3.3.2`)."""

    asset_id: SlugStr
    filename: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    sha256: str = Field(pattern=SHA256_RE)
    commons_title: str = Field(min_length=6)
    source_url: str
    license_spdx: str = Field(min_length=1)
    license_url: str
    author: str = Field(min_length=1)
    title: str = Field(min_length=1)
    modifications_note: str = Field(min_length=1)
    hitl_verified: bool = False

    @field_validator("commons_title")
    @classmethod
    def _check_commons_title(cls, value: str) -> str:
        if not value.startswith("File:"):
            raise ValueError("`commons_title` doit commencer par `File:`.")
        validate_no_raw_html(value)
        return value

    @field_validator("source_url", "license_url")
    @classmethod
    def _check_urls(cls, value: str) -> str:
        return validate_https_clean_url(value)

    @field_validator("author", "title", "modifications_note")
    @classmethod
    def _check_clean_metadata(cls, value: str) -> str:
        validate_no_raw_html(value)
        return value

    @model_validator(mode="after")
    def _check_flat_filename(self) -> AssetEntry:
        match = ASSET_FILENAME_RE.match(self.filename)
        if not match:
            raise ValueError(
                f"Nom de fichier plat invalide {self.filename!r} ; attendu "
                "`<code-cycle>-<subject_code>-<theme_slug>--<asset_id>.<webp|png>`."
            )
        if match.group(4) != self.asset_id:
            raise ValueError(
                f"Le suffixe de {self.filename!r} ne correspond pas à `asset_id={self.asset_id!r}`."
            )
        return self


class AssetsFile(StrictModel):
    """Contrat de `assets.yaml`."""

    schema_version: Literal[1]
    assets: list[AssetEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_assets(self) -> AssetsFile:
        seen_ids: set[str] = set()
        seen_files: set[str] = set()
        for entry in self.assets:
            if entry.asset_id in seen_ids:
                raise ValueError(f"`asset_id` dupliqué dans `assets.yaml` : {entry.asset_id!r}.")
            if entry.filename in seen_files:
                raise ValueError(f"`filename` dupliqué dans `assets.yaml` : {entry.filename!r}.")
            seen_ids.add(entry.asset_id)
            seen_files.add(entry.filename)
        return self


class OcclusionBox(StrictModel):
    """Boîte de masquage CSS en pourcentage (`0..100`)."""

    id: SlugStr
    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)
    w: float = Field(gt=0.0, le=100.0)
    h: float = Field(gt=0.0, le=100.0)
    role: OcclusionRole
    badge: str | None = None

    @field_validator("badge")
    @classmethod
    def _check_badge(cls, value: str | None) -> str | None:
        if value is not None:
            stripped = value.strip()
            if not stripped:
                return None
            if len(stripped) > 4:
                raise ValueError(f"`badge` limité à 4 caractères maximum (reçu : {stripped!r}).")
            validate_no_raw_html(stripped)
            return stripped
        return None

    @model_validator(mode="after")
    def _check_bounds(self) -> OcclusionBox:
        if self.x + self.w > 100.0 + 1e-6 or self.y + self.h > 100.0 + 1e-6:
            raise ValueError(
                f"La boîte d'occultation {self.id!r} dépasse 100 % "
                f"(x+w={self.x + self.w:.2f}, y+h={self.y + self.h:.2f})."
            )
        return self


def _check_badge_anti_disclosure(occlusions: list[OcclusionBox], answers: list[str]) -> None:
    norm_answers = [normalize_alnum_token(ans) for ans in answers if normalize_alnum_token(ans)]
    for box in occlusions:
        if not box.badge:
            continue
        badge_norm = normalize_alnum_token(box.badge)
        if not badge_norm:
            continue
        for ans_norm in norm_answers:
            if len(ans_norm) > 0 and ans_norm in badge_norm:
                raise ValueError(
                    f"Anti-divulgation : le badge {box.badge!r} de la boîte {box.id!r} "
                    "contient la réponse attendue."
                )


class Flashcard(StrictModel):
    """Carte mémoire (`basic` ou `cloze`) dans `flashcards.yaml` (`§3.3.4`)."""

    id: str | None = None
    concept_id: SlugStr
    reperes_level: GradeLevel
    priority: CardPriority
    type: CardType
    front: str = Field(min_length=1)
    back: str = ""
    explanation: str | None = None
    asset_id: SlugStr | None = None
    asset_role: CardAssetRole = "none"
    occlusions: list[OcclusionBox] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id_format(cls, value: str | None) -> str | None:
        if value is not None and not CARD_ID_RE.match(value):
            raise ValueError(f"Format d'identifiant de carte invalide : {value!r}.")
        return value

    @model_validator(mode="after")
    def _validate_flashcard(self) -> Flashcard:
        validate_no_raw_html(self.front)
        validate_no_raw_html(self.back)
        if self.explanation is not None:
            validate_no_raw_html(self.explanation)
            validate_latex_fragment(self.explanation, allow_block=True)

        if self.asset_id is None:
            if self.asset_role != "none":
                raise ValueError("`asset_role` doit valoir `'none'` lorsque `asset_id` est absent.")
            if self.occlusions:
                raise ValueError("`occlusions` doit être vide lorsque `asset_id` est absent.")
        elif self.asset_role == "front_occluded":
            if not self.occlusions:
                raise ValueError(
                    "`occlusions` doit contenir au moins une boîte lorsque "
                    "`asset_role == 'front_occluded'`."
                )
        elif self.occlusions:
            raise ValueError(
                "`occlusions` n'est autorisé que lorsque `asset_role == 'front_occluded'`."
            )

        seen_box_ids: set[str] = set()
        for box in self.occlusions:
            if box.id in seen_box_ids:
                raise ValueError(f"`occlusions[].id` dupliqué : {box.id!r}.")
            seen_box_ids.add(box.id)

        if self.type == "cloze":
            if self.asset_role == "front_occluded":
                raise ValueError(
                    "Combinaison interdite : `type: 'cloze'` ne peut pas utiliser "
                    "`asset_role: 'front_occluded'` (compatibilité Phase 2 Anki)."
                )
            if self.back != "":
                raise ValueError("Sur une carte `type: 'cloze'`, `back` doit être vide (`\"\"`).")

            tokens = parse_cloze_tokens(self.front)
            if not tokens:
                raise ValueError(
                    "Une carte `type: 'cloze'` doit contenir au moins une balise `{{c1::...}}`."
                )
            distinct_indices = sorted({tok.index for tok in tokens})
            expected_indices = list(range(1, len(distinct_indices) + 1))
            if distinct_indices != expected_indices:
                raise ValueError(
                    f"Les indices Cloze doivent être contigus de 1 à K (reçu : {distinct_indices})."
                )

            # Vérifier qu'aucune balise Cloze ne coupe un délimiteur mathématique
            outside_parts: list[str] = []
            visible_parts: list[str] = []
            cursor = 0
            answers: list[str] = []
            for tok in tokens:
                outside_Segment = self.front[cursor : tok.start]
                outside_parts.append(outside_Segment)
                visible_parts.append(outside_Segment)
                visible_parts.append(tok.answer)
                answers.append(tok.answer)
                if len(tok.answer) > 500:
                    raise ValueError(
                        f"Segment Cloze `c{tok.index}` trop long ({len(tok.answer)} > 500 car.)."
                    )
                validate_latex_fragment(tok.answer, allow_block=False)
                if tok.hint is not None:
                    validate_latex_fragment(tok.hint, allow_block=False)
                cursor = tok.end
            outside_parts.append(self.front[cursor:])
            visible_parts.append(self.front[cursor:])

            try:
                validate_latex_fragment(" ".join(outside_parts), allow_block=True)
            except ValueError as exc:
                raise ValueError(
                    f"Délimiteur mathématique coupé par une balise Cloze ou invalide : {exc}"
                ) from exc

            plain_front = "".join(visible_parts)
            if len(plain_front) > 500:
                raise ValueError(
                    f"Texte `front` hors balises Cloze trop long ({len(plain_front)} > 500 car.)."
                )
            _check_badge_anti_disclosure(self.occlusions, answers)
        else:
            if "{{c" in self.front or "{{c" in self.back:
                raise ValueError(
                    "Balise `{{cN::...}}` détectée sur une carte `type: 'basic'` ; "
                    "utilisez `type: 'cloze'`."
                )
            if not self.back.strip():
                raise ValueError("Sur une carte `type: 'basic'`, `back` ne peut pas être vide.")
            if len(self.back) > 500:
                raise ValueError(f"Champ `back` trop long ({len(self.back)} > 500 caractères).")
            validate_latex_fragment(self.front, allow_block=True)
            validate_latex_fragment(self.back, allow_block=True)
            _check_badge_anti_disclosure(self.occlusions, [self.back])

        return self


class FlashcardsFile(StrictModel):
    """Contrat de `flashcards.yaml` (`20..50` cartes)."""

    schema_version: Literal[1]
    cards: list[Flashcard] = Field(min_length=20, max_length=50)


class QuizQuestion(StrictModel):
    """Question à choix multiples dans `quiz.yaml` (`§3.3.5`)."""

    id: str | None = None
    concept_id: SlugStr
    reperes_level: GradeLevel
    difficulty: QuizDifficulty
    question: str = Field(min_length=1)
    choices: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1)
    asset_id: SlugStr | None = None
    asset_role: QuizAssetRole = "none"
    occlusions: list[OcclusionBox] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id_format(cls, value: str | None) -> str | None:
        if value is not None and not QUIZ_ID_RE.match(value):
            raise ValueError(f"Format d'identifiant de QCM invalide : {value!r}.")
        return value

    @model_validator(mode="after")
    def _validate_quiz(self) -> QuizQuestion:
        validate_no_raw_html(self.question)
        validate_latex_fragment(self.question, allow_block=True)
        validate_no_raw_html(self.explanation)
        validate_latex_fragment(self.explanation, allow_block=True)

        normalized_choices: set[str] = set()
        for choice in self.choices:
            stripped = WHITESPACE_RE.sub(" ", choice).strip()
            if not stripped:
                raise ValueError("Chaque choix d'un QCM doit être non vide.")
            validate_no_raw_html(choice)
            validate_latex_fragment(choice, allow_block=False)
            if stripped.lower() in normalized_choices:
                raise ValueError(f"Choix de QCM en doublon : {choice!r}.")
            normalized_choices.add(stripped.lower())

        if self.asset_id is None:
            if self.asset_role != "none":
                raise ValueError("`asset_role` doit valoir `'none'` lorsque `asset_id` est absent.")
            if self.occlusions:
                raise ValueError("`occlusions` doit être vide lorsque `asset_id` est absent.")
        elif self.asset_role == "front_occluded":
            if not self.occlusions:
                raise ValueError(
                    "`occlusions` doit contenir au moins une boîte lorsque "
                    "`asset_role == 'front_occluded'`."
                )
        elif self.occlusions:
            raise ValueError(
                "`occlusions` n'est autorisé que lorsque `asset_role == 'front_occluded'`."
            )

        seen_box_ids: set[str] = set()
        for box in self.occlusions:
            if box.id in seen_box_ids:
                raise ValueError(f"`occlusions[].id` dupliqué : {box.id!r}.")
            seen_box_ids.add(box.id)

        _check_badge_anti_disclosure(self.occlusions, [self.choices[self.answer_index]])
        return self


class QuizFile(StrictModel):
    """Contrat de `quiz.yaml` (`10..20` QCM)."""

    schema_version: Literal[1]
    questions: list[QuizQuestion] = Field(min_length=10, max_length=20)


class ResourceEntry(StrictModel):
    """Lien externe vérifié dans `resources.yaml` (`§3.3.6`)."""

    title: str = Field(min_length=1)
    url: str
    source_domain: str
    type: ResourceType
    channel_url: str | None = None
    last_verified_at: date

    @field_validator("title")
    @classmethod
    def _check_title(cls, value: str) -> str:
        validate_no_raw_html(value)
        return value

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return validate_https_clean_url(value, forbid_trackers=True)

    @field_validator("source_domain")
    @classmethod
    def _check_domain(cls, value: str) -> str:
        return normalize_hostname(value)

    @model_validator(mode="after")
    def _check_youtube_and_domain_consistency(self) -> ResourceEntry:
        url_host = normalize_hostname(self.url)
        if not (url_host == self.source_domain or url_host.endswith(f".{self.source_domain}")):
            raise ValueError(
                f"L'hôte de `url` ({url_host!r}) ne correspond pas à "
                f"`source_domain` ({self.source_domain!r})."
            )
        if url_host in {"youtube.com", "youtu.be"} or self.source_domain in {
            "youtube.com",
            "youtu.be",
        }:
            if not YOUTUBE_WATCH_RE.match(self.url):
                raise ValueError(
                    f"URL YouTube non canonique ({self.url!r}) ; "
                    "format requis : `https://www.youtube.com/watch?v=<11-car>`."
                )
            if not self.channel_url:
                raise ValueError("`channel_url` est obligatoire pour toute ressource YouTube.")
            validate_https_clean_url(self.channel_url)
        elif self.channel_url is not None:
            validate_https_clean_url(self.channel_url)
        return self


class ResourcesFile(StrictModel):
    """Contrat de `resources.yaml` (`3..6` entrées, ou `0..6` sous `--allow-empty-resources`)."""

    schema_version: Literal[1]
    resources: list[ResourceEntry] = Field(max_length=6)

    @model_validator(mode="after")
    def _check_count_and_uniqueness(self, info: ValidationInfo) -> ResourcesFile:
        allow_empty = bool(info.context and info.context.get("allow_empty_resources"))
        if not allow_empty and len(self.resources) < 3:
            raise ValueError(
                f"`resources.yaml` doit contenir entre 3 et 6 liens (reçu : {len(self.resources)})."
            )
        seen_urls: set[str] = set()
        for res in self.resources:
            if res.url in seen_urls:
                raise ValueError(f"URL dupliquée dans `resources.yaml` : {res.url!r}.")
            seen_urls.add(res.url)
        return self


class FeedbackItem(StrictModel):
    """Entrée de signalement d'erreur élève/parent (`osarai:v1:flags` / `osarai-feedback-v1`)."""

    cycle: CycleName
    subject: SubjectName
    theme_slug: SlugStr
    item_id: str = Field(pattern=FEEDBACK_ITEM_ID_RE)
    item_type: FeedbackItemType
    content_hash: str = Field(pattern=CONTENT_HASH_RE)
    build_sha: str = Field(min_length=4, max_length=40, pattern=r"^[0-9a-fA-F]+|dev$")
    reason: FeedbackReason
    note: str = Field(default="", max_length=300)
    status: FeedbackStatus = "open"
    flagged_at: datetime

    @model_validator(mode="after")
    def _check_item_type_matches_id(self) -> FeedbackItem:
        expected_prefix = f"{CYCLE_CODE_MAP[self.cycle]}-{SUBJECT_CODE_MAP[self.subject]}-{self.theme_slug}-"
        if not self.item_id.startswith(expected_prefix):
            raise ValueError(
                f"`item_id` ({self.item_id!r}) ne correspond pas au thème `{expected_prefix}*`."
            )
        tail = self.item_id[len(expected_prefix) :]
        if self.item_type == "flashcard" and not tail.startswith("c"):
            raise ValueError(f"`item_type='flashcard'` incompatible avec {self.item_id!r}.")
        if self.item_type == "quiz" and (not tail.startswith("q") or "#" in tail):
            raise ValueError(f"`item_type='quiz'` incompatible avec {self.item_id!r}.")
        return self


class FeedbackPayload(StrictModel):
    """Bloc d'export/partage `osarai-feedback-v1`."""

    schema_name: Literal["osarai-feedback-v1"] = Field(alias="schema")
    exported_at: datetime
    items: list[FeedbackItem] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CardProgress(StrictModel):
    """État de révision local d'une carte mémoire."""

    state: Literal["connu", "a_revoir"]
    updated_at: datetime


class QuizProgress(StrictModel):
    """Meilleur score et erreurs QCM enregistrés localement."""

    best_score: int = Field(ge=0)
    total: int = Field(gt=0)
    missed_ids: list[str] = Field(default_factory=list)
    updated_at: datetime


class ThemeProgress(StrictModel):
    """Objet stocké sous `osarai:v1:progress:<cycle>:<subject>:<theme_slug>`."""

    cards: dict[str, CardProgress] = Field(default_factory=dict)
    quiz: QuizProgress | None = None


class BackupPayload(StrictModel):
    """Sauvegarde locale complète `osarai-backup-v1.json`."""

    schema_name: Literal["osarai-backup-v1"] = Field(alias="schema")
    exported_at: datetime
    grade: GradeLevel
    progress: dict[str, ThemeProgress] = Field(default_factory=dict)
    flags: list[FeedbackItem] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("progress")
    @classmethod
    def _check_progress_keys(cls, value: dict[str, ThemeProgress]) -> dict[str, ThemeProgress]:
        key_re = re.compile(
            r"^(cycle-3|cycle-4):([a-z-]+):([a-z0-9]+(?:-[a-z0-9]+)*)$"
        )
        for key in value:
            if not key_re.match(key):
                raise ValueError(
                    f"Clé `progress` invalide ({key!r}) ; attendu `<cycle>:<subject>:<theme_slug>`."
                )
        return value
