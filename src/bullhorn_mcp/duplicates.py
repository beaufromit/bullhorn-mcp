"""Candidate match check: normalisers, profile shape and scorer (CR44, FR-23).

Pure functions with no I/O apart from reading the packaged ``match_config.json``.
Retrieval (the Bullhorn searches that build the pool and fill ``MatchContext``)
lives in ``duplicate_retrieval.py`` (Sprint 42B); nothing here talks to Bullhorn.

The model: each agreeing signal adds ``log2(m/u)`` points, where m is the chance
the signal agrees when both records are the same person and u the chance it
agrees when they are not. The prior is ``log2(pi/(1-pi))`` with ``pi = 0.3/N``
(N = live candidate count), and ``percentage = 1/(1+2^-(points+prior))``. Every
m, u, cap and threshold is in the versioned config, so calibration is a reviewed
change and the match log can record which version scored each call.

A missing value always scores exactly zero: an empty email on a new CV is not
evidence of a new person (the 90308 false negative that motivated CR44).
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlsplit


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class MatchConfigError(ValueError):
    """The match config is missing a key or holds an invalid value."""


_REQUIRED_KEYS = (
    "version",
    "population.fallback_n",
    "population.pi_numerator",
    "bands.high",
    "bands.low",
    "caps.name_only_percentage",
    "caps.max_employers",
    "caps.education_points",
    "identifiers.email",
    "identifiers.phone",
    "identifiers.linkedin",
    "identifier_guard.m",
    "identifier_guard.generic_min_holders",
    "forename.exact",
    "forename.equivalent",
    "forename.initial",
    "forename.typo",
    "forename.different",
    "surname.exact",
    "surname.fuzzy",
    "surname.different",
    "employer.m",
    "employer.default_u",
    "employer.overlap_bonus",
    "employer.title_bonus",
    "education.school_and_year",
    "education.school",
    "education.qualification",
    "education.year_tolerance",
    "default_country_code",
    "generic_mailbox_prefixes",
    "internal_domains",
    "employer_suffixes",
    "generic_employer_words",
    "generic_degrees",
    "forename_equivalents",
)

# Keys whose value is a probability, beyond the m/u pairs found by walking the file.
_PROBABILITY_KEYS = ("identifier_guard.m", "employer.m", "employer.default_u")


def _lookup(config: dict, path: str):
    node = config
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise MatchConfigError(f"match config is missing '{path}'")
        node = node[part]
    return node


def _check_probability(path: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
        raise MatchConfigError(f"match config '{path}' must be a probability between 0 and 1 (exclusive), got {value!r}")


def _check_m_u(node, path: str) -> None:
    """Every ``m`` and ``u`` anywhere in the file is a probability in (0, 1)."""
    if isinstance(node, dict):
        for key, value in node.items():
            sub = f"{path}.{key}" if path else key
            if key in ("m", "u"):
                _check_probability(sub, value)
            else:
                _check_m_u(value, sub)


def _check_number(path: str, value, minimum=None, maximum=None, integer: bool = False) -> None:
    kind = "an integer" if integer else "a number"
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)):
        raise MatchConfigError(f"match config '{path}' must be {kind}, got {value!r}")
    if minimum is not None and value < minimum:
        raise MatchConfigError(f"match config '{path}' must be {kind} of at least {minimum}, got {value!r}")
    if maximum is not None and value > maximum:
        raise MatchConfigError(f"match config '{path}' must be {kind} of at most {maximum}, got {value!r}")


# Levels scored from m/u, and the "different" levels that hold fixed points.
_M_U_LEVELS = (
    "forename.exact", "forename.equivalent", "forename.initial", "forename.typo",
    "surname.exact", "surname.fuzzy",
    "identifiers.email", "identifiers.phone", "identifiers.linkedin",
)
_PENALTY_LEVELS = ("forename.different", "surname.different")

# (path, integer, minimum) for the plain numbers the scorer reads.
_NUMBER_KEYS = (
    ("caps.max_employers", True, 1),
    ("caps.education_points", False, 0),
    ("identifier_guard.generic_min_holders", True, 1),
    ("employer.overlap_bonus", False, 0),
    ("employer.title_bonus", False, 0),
    ("education.school_and_year", False, 0),
    ("education.school", False, 0),
    ("education.qualification", False, 0),
    ("education.year_tolerance", True, 0),
)


def _check_shapes(config: dict) -> None:
    """Each level and number holds what the scorer reads, with the right sign."""
    for path in _M_U_LEVELS:
        for key in ("m", "u"):
            _lookup(config, f"{path}.{key}")
    for path in _PENALTY_LEVELS:
        _check_number(f"{path}.points", _lookup(config, f"{path}.points"), maximum=0)
    for kind in ("email", "phone", "linkedin"):
        path = f"identifiers.{kind}.differ_points"
        _check_number(path, _lookup(config, path), maximum=0)
    for path, integer, minimum in _NUMBER_KEYS:
        _check_number(path, _lookup(config, path), minimum=minimum, integer=integer)


def validate_match_config(config: dict) -> dict:
    """Raise ``MatchConfigError`` naming the bad key; return the config unchanged."""
    if not isinstance(config, dict):
        raise MatchConfigError("match config must be a JSON object")
    for path in _REQUIRED_KEYS:
        _lookup(config, path)
    _check_m_u(config, "")
    _check_shapes(config)
    for path in _PROBABILITY_KEYS:
        _check_probability(path, _lookup(config, path))
    low, high = _lookup(config, "bands.low"), _lookup(config, "bands.high")
    cap = _lookup(config, "caps.name_only_percentage")
    for path, value in (("bands.low", low), ("bands.high", high), ("caps.name_only_percentage", cap)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 100:
            raise MatchConfigError(f"match config '{path}' must be a percentage between 0 and 100, got {value!r}")
    if not low < high:
        raise MatchConfigError(f"match config 'bands.low' ({low}) must be below 'bands.high' ({high})")
    if not cap < high:
        raise MatchConfigError(
            f"match config 'caps.name_only_percentage' ({cap}) must be below 'bands.high' ({high}), "
            "or a name match alone could reach the high band"
        )
    n = _lookup(config, "population.fallback_n")
    pi = _lookup(config, "population.pi_numerator")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 1:
        raise MatchConfigError(f"match config 'population.fallback_n' must be an integer above 1, got {n!r}")
    if isinstance(pi, bool) or not isinstance(pi, (int, float)) or not 0 < pi < n:
        raise MatchConfigError(f"match config 'population.pi_numerator' must be above 0 and below fallback_n, got {pi!r}")
    if not isinstance(_lookup(config, "version"), str):
        raise MatchConfigError("match config 'version' must be a string")
    return config


def load_match_config(path: str | Path | None = None) -> dict:
    """Load and validate the match config; the packaged file when ``path`` is None.

    A bad file raises ``MatchConfigError`` at load, naming the key, so a broken
    calibration change fails at startup rather than scoring quietly wrong.
    """
    try:
        if path is None:
            text = resources.files("bullhorn_mcp").joinpath("match_config.json").read_text(encoding="utf-8")
        else:
            text = Path(path).read_text(encoding="utf-8")
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MatchConfigError(f"match config is not valid JSON: {exc}") from exc
    return validate_match_config(config)


@lru_cache(maxsize=1)
def default_match_config() -> dict:
    """The packaged config, loaded once per process."""
    return load_match_config()


# ---------------------------------------------------------------------------
# Normalisers
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({"the", "of", "and", "for", "in", "at", "a", "an", "on"})


def _fold(text: str) -> str:
    """Lowercase, accents folded (Pádraig -> padraig), curly apostrophes straightened."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.replace("’", "'").replace("‘", "'").replace("`", "'").lower()


def _words(text: str | None) -> list[str]:
    """Lowercase words with ``&`` as ``and``, apostrophes joined (o'reilly -> oreilly)."""
    if not text:
        return []
    folded = _fold(text).replace("&", " and ").replace("'", "")
    return re.findall(r"[a-z0-9]+", folded)


def normalize_email(value) -> str | None:
    """Trimmed, lowercased email, or None when the value is not an email."""
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        return None
    return email


def is_generic_mailbox(email: str, config: dict) -> bool:
    """True for a role mailbox (info@, cv@, ...) that several people can share."""
    local = (normalize_email(email) or "").split("@")[0]
    return local in set(config["generic_mailbox_prefixes"])


def is_internal(email: str, config: dict) -> bool:
    """True for an internal address (@thepanel.com): a consultant's, not the candidate's."""
    domain = (normalize_email(email) or "").rpartition("@")[2]
    return any(domain == d or domain.endswith("." + d) for d in config["internal_domains"])


def normalize_phone(value, country_code: str = "353") -> str | None:
    """One comparable form of a phone number (CR44 D1).

    Spaces, dashes, dots, brackets and ``(0)`` go; ``00353`` and a leading
    national ``0`` become ``+353``; unquoted ``353...`` digits get their ``+``.
    Fewer than 7 digits gives None, because extensions and fragments are not
    identifiers.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip().replace("(0)", "")
    plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if len(digits) < 7:
        return None
    if not plus:
        if digits.startswith("00"):
            digits, plus = digits[2:], True
        elif digits.startswith("0"):
            digits, plus = country_code + digits[1:], True
        elif digits.startswith(country_code) and len(digits) >= len(country_code) + 7:
            plus = True
    if plus and digits.startswith(country_code + "0"):
        # "+353 0 85 ..." written with the national trunk 0 kept
        digits = country_code + digits[len(country_code) + 1:]
    return f"+{digits}" if plus else digits


def phone_search_variants(phone, country_code: str = "353") -> list[str]:
    """Stored-style forms to search, because Bullhorn phone search is format-exact.

    ``+353857260864`` gives ``["+353857260864", "0857260864", "353857260864"]``.
    """
    normalized = normalize_phone(phone, country_code)
    if normalized is None:
        return []
    variants = [normalized]
    if normalized.startswith("+"):
        digits = normalized[1:]
        if digits.startswith(country_code):
            variants.append("0" + digits[len(country_code):])
        variants.append(digits)
    return list(dict.fromkeys(variants))


def linkedin_key(url) -> str | None:
    """Comparable key for a LinkedIn profile URL, or None for anything else.

    Handles ``/in/<slug>`` and the old ``/pub/<name>/<x>/<y>/<z>`` form, country
    subdomains (``ie.linkedin.com``), any case, with or without scheme, query or
    trailing slash, and URL-encoded characters (critique 7).
    """
    if not isinstance(url, str) or not url.strip():
        return None
    text = unquote(url.strip())
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    segments = [s for s in parts.path.lower().split("/") if s]
    if len(segments) >= 2 and segments[0] == "in":
        return f"in/{segments[1]}"
    if len(segments) >= 5 and segments[0] == "pub":
        return "pub/" + "/".join(segments[1:5])
    return None


def normalize_employer(name, config: dict) -> str | None:
    """Comparable employer key: lowercase words, ``&`` as ``and``, punctuation off.

    A leading "The" and trailing legal or jurisdiction suffixes (Ltd, plc, DAC,
    Group, Ireland, ...) are removed, but a suffix that follows a stopword is part
    of the name, so "Bank of Ireland" stays "bank of ireland" (critique 6), and the
    key is never stripped to nothing.
    """
    if not isinstance(name, str):
        return None
    words = _words(name)
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    suffixes = set(config["employer_suffixes"])
    while len(words) > 1 and words[-1] in suffixes and words[-2] not in _STOPWORDS:
        words = words[:-1]
    return " ".join(words) or None


def _distinctive(word: str, config: dict) -> bool:
    return (
        word not in _STOPWORDS
        and word not in config["generic_employer_words"]
        and word not in config["employer_suffixes"]
    )


def employer_words(name, config: dict) -> list[str]:
    """Distinct words of the normalised employer for the nested word-AND search."""
    key = normalize_employer(name, config)
    if not key:
        return []
    return list(dict.fromkeys(w for w in key.split() if w not in _STOPWORDS))


def normalize_person_name(name) -> str | None:
    """Lowercase, accents folded, whitespace collapsed; apostrophes and hyphens kept."""
    if not isinstance(name, str):
        return None
    text = " ".join(_fold(name).split())
    return text or None


def name_forms(name) -> list[str]:
    """The apostrophe and no-apostrophe forms, both needed for search.

    Bullhorn search does not fold apostrophes: ``o'brien`` and ``obrien`` find
    different candidates.
    """
    normalized = normalize_person_name(name)
    if not normalized:
        return []
    return list(dict.fromkeys([normalized, normalized.replace("'", "")]))


def name_key(name) -> str | None:
    """Comparison key for a name: folded, no apostrophes, hyphens, dots or spaces.

    ``MatchContext`` name counts are keyed by this.
    """
    normalized = normalize_person_name(name)
    if not normalized:
        return None
    return re.sub(r"[\s'.\-]", "", normalized) or None


def _first_token_key(name: str) -> str | None:
    normalized = normalize_person_name(name)
    if not normalized:
        return None
    tokens = [t for t in re.split(r"[\s\-]+", normalized) if t]
    return name_key(tokens[0]) if tokens else None


def _within_one_edit(a: str, b: str) -> bool:
    """True when a and b differ by at most one insert, delete, substitute or adjacent swap."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = [i for i in range(la) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]
    short, long_ = (a, b) if la < lb else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1:] == short:
            return True
    return False


def _equivalent_forenames(a: str, b: str, config: dict) -> bool:
    for group in config["forename_equivalents"]:
        keys = {name_key(n) for n in group}
        if a in keys and b in keys:
            return True
    return False


def forename_relation(a, b, config: dict) -> str:
    """exact / equivalent / initial / typo / different / missing.

    Compound forenames compare on the first name too ("Mary Kate" and "Mary" are
    exact). Equivalents are nicknames and Irish-English pairs from the config
    (Seán/John, Liam/William). An initial matches its own letter only.
    """
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return "missing"
    if ka == kb:
        return "exact"
    ta, tb = _first_token_key(a), _first_token_key(b)
    if ta == tb:
        return "exact"
    if _equivalent_forenames(ta, tb, config) or _equivalent_forenames(ka, kb, config):
        return "equivalent"
    if len(ta) == 1 or len(tb) == 1:
        return "initial" if ta[0] == tb[0] else "different"
    if min(len(ta), len(tb)) >= 4 and _within_one_edit(ta, tb):
        return "typo"
    return "different"


def surname_relation(a, b) -> str:
    """exact / fuzzy / different / missing.

    Exact compares the name key, so O'Brien = OBrien = O Brien and fadas fold.
    Fuzzy covers one edit (on names of 4+ letters), Mc/Mac, a dropped O prefix
    and a shared part of a double-barrelled name (a common married-name form).
    """
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return "missing"
    if ka == kb:
        return "exact"

    def mac(k: str) -> str:
        return "mc" + k[3:] if k.startswith("mac") else k

    if mac(ka) == mac(kb) or ka == "o" + kb or kb == "o" + ka:
        return "fuzzy"
    if min(len(ka), len(kb)) >= 4 and _within_one_edit(ka, kb):
        return "fuzzy"
    parts_a = {name_key(p) for p in re.split(r"[\s\-]+", normalize_person_name(a)) if name_key(p)}
    parts_b = {name_key(p) for p in re.split(r"[\s\-]+", normalize_person_name(b)) if name_key(p)}
    if max(len(parts_a), len(parts_b)) > 1 and parts_a & parts_b:
        return "fuzzy"
    return "different"


def _year(value) -> int | None:
    """UTC year of an epoch-ms date (CR44 D3, P8), or of a "YYYY..." string."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() and len(text) > 4:
            value = int(text)
        else:
            match = re.match(r"(\d{4})", text)
            return int(match.group(1)) if match else None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).year
        except (OverflowError, OSError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# Profile (CR44 D7: one input shape for every caller)
# ---------------------------------------------------------------------------

_EMAIL_FIELDS = ("email", "email2", "email3")
_PHONE_FIELDS = ("mobile", "phone", "workPhone", "phone2", "phone3")


@dataclass
class WorkEntry:
    company: str | None = None
    title: str | None = None
    start_year: int | None = None
    end_year: int | None = None


@dataclass
class EducationEntry:
    school: str | None = None
    degree: str | None = None
    year: int | None = None


@dataclass
class CandidateProfile:
    """A candidate as the match check sees it, from a parse, plain fields or a record."""

    first_name: str | None = None
    last_name: str | None = None
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    linkedin_url: str | None = None
    current_company: str | None = None
    work_history: list[WorkEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    candidate_id: int | None = None

    @property
    def display_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    def to_echo(self, config: dict | None = None) -> dict:
        """The normalised profile that was compared, for the response (D7)."""
        config = config or default_match_config()
        cc = config["default_country_code"]
        return {
            "first_name": normalize_person_name(self.first_name),
            "last_name": normalize_person_name(self.last_name),
            "emails": list(dict.fromkeys(e for e in map(normalize_email, self.emails) if e)),
            "phones": list(dict.fromkeys(p for p in (normalize_phone(x, cc) for x in self.phones) if p)),
            "linkedin": linkedin_key(self.linkedin_url),
            "employers": list(_employers(self, config)),
            "education": [
                {
                    "school": normalize_employer(e.school, config),
                    "degree": " ".join(_words(e.degree)) or None,
                    "year": e.year,
                }
                for e in self.education
            ],
        }


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _live_row(row) -> bool:
    # D2: soft-deleted work history and education rows are not evidence.
    return isinstance(row, dict) and not row.get("isDeleted")


def _work_entry(row: dict) -> WorkEntry | None:
    entry = WorkEntry(
        company=_text(row.get("companyName")),
        title=_text(row.get("title")),
        start_year=_year(row.get("startDate")),
        end_year=_year(row.get("endDate")),
    )
    return entry if entry.company or entry.title else None


def _education_entry(row: dict) -> EducationEntry | None:
    # D4: a professional qualification held in degree (or certification) is kept.
    entry = EducationEntry(
        school=_text(row.get("school")),
        degree=_text(row.get("degree")) or _text(row.get("certification")),
        year=_year(row.get("graduationDate")) or _year(row.get("endDate")),
    )
    return entry if entry.school or entry.degree else None


def profile_from_fields(fields: dict | None, work_history: list | None = None, education: list | None = None) -> CandidateProfile:
    """Profile from Candidate-shaped fields plus work history and education rows."""
    fields = fields or {}
    candidate_id = fields.get("id")
    return CandidateProfile(
        first_name=_text(fields.get("firstName")),
        last_name=_text(fields.get("lastName")),
        emails=[e for f in _EMAIL_FIELDS if (e := _text(fields.get(f)))],
        phones=[p for f in _PHONE_FIELDS if (p := _text(fields.get(f)))],
        linkedin_url=_text(fields.get("companyURL")),
        current_company=_text(fields.get("companyName")),
        work_history=[w for r in (work_history or []) if _live_row(r) and (w := _work_entry(r))],
        education=[e for r in (education or []) if _live_row(r) and (e := _education_entry(r))],
        candidate_id=candidate_id if isinstance(candidate_id, int) and not isinstance(candidate_id, bool) else None,
    )


def profile_from_parse(parsed: dict, corrections: dict | None = None) -> CandidateProfile:
    """Profile from a resume parse with Claude's corrections applied (CR43 P5).

    ``corrections`` uses the create_candidate_from_cv argument names:
    ``fields_override`` is merged over the parsed candidate, and ``work_history``
    or ``education``, when given, replace the parsed lists.
    """
    corrections = corrections or {}
    fields = dict((parsed or {}).get("candidate") or {})
    fields.update(corrections.get("fields_override") or {})
    work_history = corrections.get("work_history")
    if work_history is None:
        work_history = (parsed or {}).get("candidateWorkHistory") or []
    education = corrections.get("education")
    if education is None:
        education = (parsed or {}).get("candidateEducation") or []
    return profile_from_fields(fields, work_history, education)


def profile_from_record(candidate: dict, work_history_rows: list | None, education_rows: list | None) -> CandidateProfile:
    """Profile of an existing Candidate record and its child rows (deleted rows skipped)."""
    return profile_from_fields(candidate, work_history_rows, education_rows)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

@dataclass
class MatchContext:
    """Population facts the scorer needs; retrieval fills them (Sprint 42B).

    ``identifier_holders`` maps kind ("email", "phone", "linkedin") to normalised
    value to the number of live candidates holding it. Name counts are keyed by
    ``name_key``, employer counts by ``normalize_employer``. A missing count falls
    back to the config u.
    """

    n: int | None = None
    identifier_holders: dict[str, dict[str, int]] = field(default_factory=dict)
    surname_counts: dict[str, int] = field(default_factory=dict)
    forename_counts: dict[str, int] = field(default_factory=dict)
    employer_counts: dict[str, int] = field(default_factory=dict)


def prior(n: int, config: dict) -> float:
    """Prior log-odds in points that two records are the same person: log2(pi/(1-pi))."""
    pi = config["population"]["pi_numerator"] / n
    return math.log2(pi / (1 - pi))


def to_percentage(points: float, prior_points: float) -> float:
    """1/(1+2^-(points+prior)) as a percentage (0 to 100)."""
    x = max(-500.0, min(500.0, points + prior_points))
    return 100.0 / (1.0 + 2.0 ** (-x))


def band(percentage: float, config: dict) -> str:
    """high (>= bands.high), low (< bands.low) or uncertain in between."""
    if percentage >= config["bands"]["high"]:
        return "high"
    if percentage < config["bands"]["low"]:
        return "low"
    return "uncertain"


def _agree_points(m: float, u: float) -> float:
    # Agreement is never evidence against: a common value only weakens it.
    return max(0.0, math.log2(m / min(u, 0.999)))


def _level_points(levels: dict, level: str, u_override: float | None = None) -> float:
    spec = levels[level]
    if "points" in spec:
        return float(spec["points"])
    return _agree_points(spec["m"], u_override if u_override is not None else spec["u"])


def _entry(signal: str, points: float, reason: str) -> dict:
    return {"signal": signal, "points": round(points, 2), "reason": reason, "_raw": points}


_IDENTIFIER_LABEL = {"email": "email address", "phone": "phone number", "linkedin": "LinkedIn profile"}


def _identifier_values(profile: CandidateProfile, config: dict) -> dict[str, set[str]]:
    cc = config["default_country_code"]
    key = linkedin_key(profile.linkedin_url)
    return {
        "email": {e for e in map(normalize_email, profile.emails) if e},
        "phone": {p for p in (normalize_phone(x, cc) for x in profile.phones) if p},
        "linkedin": {key} if key else set(),
    }


def _score_identifiers(a, b, context, n, config, forenames_disagree, breakdown, flags) -> None:
    va, vb = _identifier_values(a, config), _identifier_values(b, config)
    guard = config["identifier_guard"]
    for kind in ("email", "phone", "linkedin"):
        label = _IDENTIFIER_LABEL[kind]
        spec = config["identifiers"][kind]
        if not va[kind] or not vb[kind]:
            continue  # missing on either side: exactly zero
        shared = va[kind] & vb[kind]
        if not shared:
            breakdown.append(_entry(kind, float(spec["differ_points"]), f"Different {label}s on file"))
            continue
        holders_by_value = context.identifier_holders.get(kind, {})
        best = None
        for value in sorted(shared):
            holders = max(1, int(holders_by_value.get(value, 1)))
            guards = []
            if holders > 1:
                guards.append(f"held by {holders} candidates")
            generic = kind == "email" and (is_generic_mailbox(value, config) or is_internal(value, config))
            if kind == "email" and is_generic_mailbox(value, config):
                guards.append("a shared role mailbox")
            if kind == "email" and is_internal(value, config):
                guards.append("an internal address")
            if forenames_disagree:
                guards.append("the first names clearly disagree")
            if not guards:
                points = _agree_points(spec["m"], spec["u"])
            else:
                h = max(holders, guard["generic_min_holders"]) if generic else holders
                points = _agree_points(guard["m"], h / n)
            if best is None or points > best[0]:
                best = (points, value, guards)
        points, value, guards = best
        if not guards:
            flags.append(f"guaranteed_match:{kind}")
            breakdown.append(_entry(kind, points, f"Same {label} ({value}): treated as a guaranteed match"))
        else:
            flags.append(f"guard_tripped:{kind}")
            breakdown.append(_entry(
                kind, points,
                f"Same {label} ({value}), but it is {' and '.join(guards)}, so it counts as strong evidence, not a guaranteed match",
            ))


def _count_u(counts: dict, keys, n: int) -> float | None:
    found = [counts[k] for k in keys if k and k in counts and counts[k]]
    return max(found) / n if found else None


def _score_names(a, b, context, n, config, breakdown, flags) -> str:
    """Add the name entries; return the forename relation used."""
    ka_first, ka_last = name_key(a.first_name), name_key(a.last_name)
    kb_first, kb_last = name_key(b.first_name), name_key(b.last_name)
    fore = forename_relation(a.first_name, b.first_name, config)
    sur = surname_relation(a.last_name, b.last_name)
    a_first, a_last, b_first, b_last = a.first_name, a.last_name, b.first_name, b.last_name
    # Swapped first and last names are checked first, on exact keys only, so the
    # check reads the same from either side.
    if (
        ka_first and ka_last and ka_first != ka_last
        and ka_first == kb_last and ka_last == kb_first
        and not (fore == "exact" and sur == "exact")
    ):
        fore, sur = "exact", "exact"
        b_first, b_last = b.last_name, b.first_name
        kb_first, kb_last = kb_last, kb_first
        flags.append("names_swapped")
        breakdown.append(_entry("names_swapped", 0.0, "First and last names appear swapped on one record"))

    if fore != "missing":
        u = _count_u(context.forename_counts, [ka_first, kb_first], n) if fore == "exact" else None
        points = _level_points(config["forename"], fore, u)
        reasons = {
            "exact": f"Same first name ({a_first})",
            "equivalent": f"First names are equivalent ({a_first} / {b_first})",
            "initial": f"First name matches an initial ({a_first} / {b_first})",
            "typo": f"First names differ by one letter ({a_first} / {b_first})",
            "different": f"Different first names ({a_first} / {b_first})",
        }
        breakdown.append(_entry("first_name", points, reasons[fore]))
    if sur != "missing":
        u = _count_u(context.surname_counts, [ka_last, kb_last], n) if sur == "exact" else None
        points = _level_points(config["surname"], sur, u)
        count = max((context.surname_counts.get(k, 0) for k in (ka_last, kb_last) if k), default=0)
        reasons = {
            "exact": f"Same surname ({a_last})" + (f", shared by {count} candidates" if sur == "exact" and count else ""),
            "fuzzy": f"Similar surnames ({a_last} / {b_last})",
            "different": f"Different surnames ({a_last} / {b_last}); can happen after marriage",
        }
        breakdown.append(_entry("surname", points, reasons[sur]))
    return fore


@dataclass
class _Employer:
    key: str
    display: str
    spans: list = field(default_factory=list)
    titles: list = field(default_factory=list)


def _employers(profile: CandidateProfile, config: dict) -> dict[str, _Employer]:
    """Distinct employers by normalised key (rows are never counted twice).

    Two keys in one record that match each other (for example "abbey capital"
    and the parser's "corporate with abbey capital") are one employer, kept
    under the key with fewer words. ``Candidate.companyName`` is one more
    employer with no dates.
    """
    out: dict[str, _Employer] = {}

    def merge(name, span, title):
        key = normalize_employer(name, config)
        if not key:
            return
        same = next((k for k in out if _employers_match(k, key, config)), None)
        if same is None:
            emp = out[key] = _Employer(key, name)
        else:
            emp = out[same]
            if len(key.split()) < len(same.split()):
                emp.key, emp.display = key, name
                items = list(out.items())  # re-key in place, keeping order
                out.clear()
                out.update(((key if k == same else k), v) for k, v in items)
        if span is not None:
            emp.spans.append(span)
        if title:
            emp.titles.append(title)

    for w in profile.work_history:
        merge(w.company, (w.start_year, w.end_year), w.title)
    merge(profile.current_company, None, None)
    return out


def _word_eq(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 5 and _within_one_edit(a, b))


def _employers_match(ka: str, kb: str, config: dict) -> bool:
    """Word-based match: equal keys, or every word of the shorter in the longer.

    The shorter must hold a distinctive word, so "bank" never matches "bank of
    ireland" while "abbey" matches "abbey capital". Words of 5+ letters may
    differ by one edit (a parser or typing slip).
    """
    if ka == kb:
        return True
    wa, wb = ka.split(), kb.split()
    small, large = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if not any(_distinctive(w, config) for w in small):
        return False
    return all(any(_word_eq(w, x) for x in large) for w in small)


def _contains_employer(text: str | None, key: str, config: dict) -> bool:
    """True when an employer key appears as whole words inside a title."""
    if not text or not any(_distinctive(w, config) for w in key.split()):
        return False
    return f" {key} " in f" {' '.join(_words(text))} "


def _spans_overlap(spans_a, spans_b) -> bool:
    # Year granularity (D3); a missing end year is a current role (CR44), though
    # only as of when the record was written, so an old open-ended role overlaps
    # any later one at the same employer. Accepted (Sprint 42 review m3).
    for sa, ea in spans_a:
        for sb, eb in spans_b:
            if sa is None or sb is None:
                continue
            if max(sa, sb) <= min(ea if ea is not None else 9999, eb if eb is not None else 9999):
                return True
    return False


def _titles_agree(titles_a, titles_b) -> bool:
    for ta in titles_a:
        wa = {w for w in _words(ta) if w not in _STOPWORDS}
        for tb in titles_b:
            wb = {w for w in _words(tb) if w not in _STOPWORDS}
            if wa and wb and len(wa & wb) / len(wa | wb) >= 0.5:
                return True
    return False


def _score_employers(a, b, context, n, config, breakdown) -> None:
    ea, eb = _employers(a, config), _employers(b, config)
    spec = config["employer"]
    pairs = []  # (points, id_a, id_b, reason)

    def add(id_a, id_b, emp_a, emp_b, key_a, key_b, spans_a, spans_b, titles_a, titles_b, via_title):
        u = _count_u(context.employer_counts, [key_a, key_b], n)
        count = max((context.employer_counts.get(k, 0) for k in (key_a, key_b)), default=0)
        points = _agree_points(spec["m"], u if u is not None else spec["default_u"])
        reason = f"Both worked at {emp_a}"
        if emp_b and normalize_employer(emp_b, config) != normalize_employer(emp_a, config):
            reason += f" (listed as {emp_b})"
        if via_title:
            reason += ", found in a job title"
        if count:
            reason += f"; {count} candidates list this employer"
        if _spans_overlap(spans_a, spans_b):
            points += spec["overlap_bonus"]
            reason += "; the dates overlap"
        if _titles_agree(titles_a, titles_b):
            points += spec["title_bonus"]
            reason += "; similar job title there"
        pairs.append((points, id_a, id_b, reason))

    for ka, emp_a in ea.items():
        for kb, emp_b in eb.items():
            if _employers_match(ka, kb, config):
                add(ka, kb, emp_a.display, emp_b.display, ka, kb, emp_a.spans, emp_b.spans, emp_a.titles, emp_b.titles, False)
    # The parser sometimes puts the employer in the title, or swaps the two
    # (critique 5), so each side's employers are also looked for in the other's titles.
    for side_a, emps, other in ((True, ea, b), (False, eb, a)):
        for key, emp in emps.items():
            for w in other.work_history:
                if _contains_employer(w.title, key, config):
                    span, titles = [(w.start_year, w.end_year)], []
                    if side_a:
                        add(key, f"title:{key}", emp.display, w.title, key, key, emp.spans, span, emp.titles, titles, True)
                    else:
                        add(f"title:{key}", key, emp.display, w.title, key, key, span, emp.spans, titles, emp.titles, True)
                    break

    used_a, used_b, chosen = set(), set(), []
    for points, id_a, id_b, reason in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
        if id_a in used_a or id_b in used_b:
            continue
        used_a.add(id_a)
        used_b.add(id_b)
        chosen.append((points, reason))
        if len(chosen) == config["caps"]["max_employers"]:
            break
    for points, reason in chosen:
        breakdown.append(_entry("employer", points, reason))


def _score_education(a, b, config, breakdown) -> None:
    """A capped tiebreaker that is never negative (CR44 design, D4)."""
    spec = config["education"]
    generic = {" ".join(_words(d)) for d in config["generic_degrees"]}
    pairs = []
    for i, x in enumerate(a.education):
        for j, y in enumerate(b.education):
            sx, sy = normalize_employer(x.school, config), normalize_employer(y.school, config)
            if sx and sy and _employers_match(sx, sy, config):
                close = x.year is not None and y.year is not None and abs(x.year - y.year) <= spec["year_tolerance"]
                if close:
                    pairs.append((spec["school_and_year"], i, j, f"Studied at the same school ({x.school}), graduating within a year"))
                else:
                    pairs.append((spec["school"], i, j, f"Studied at the same school ({x.school})"))
                continue
            dx, dy = " ".join(_words(x.degree)), " ".join(_words(y.degree))
            if dx and dx == dy and dx not in generic:
                pairs.append((spec["qualification"], i, j, f"Same qualification ({x.degree})"))
    used_a, used_b, remaining = set(), set(), float(config["caps"]["education_points"])
    for points, i, j, reason in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
        if i in used_a or j in used_b or remaining <= 0:
            continue
        used_a.add(i)
        used_b.add(j)
        points = min(points, remaining)
        remaining -= points
        breakdown.append(_entry("education", points, reason))


def score_pair(profile: CandidateProfile, existing: CandidateProfile, context: MatchContext | None, config: dict) -> dict:
    """Score one existing candidate against a profile.

    Returns ``{points, percentage, band, breakdown: [{signal, points, reason}], flags}``.
    Every reason is plain English because the consultant is shown it (D8b).
    Flags: ``guaranteed_match:<kind>``, ``guard_tripped:<kind>``, ``names_swapped``,
    ``name_only_capped``.
    """
    context = context or MatchContext()
    n = context.n or config["population"]["fallback_n"]
    breakdown: list[dict] = []
    flags: list[str] = []

    forename = _score_names(profile, existing, context, n, config, breakdown, flags)
    _score_identifiers(profile, existing, context, n, config, forename == "different", breakdown, flags)
    _score_employers(profile, existing, context, n, config, breakdown)
    _score_education(profile, existing, config, breakdown)

    prior_points = prior(n, config)
    points = sum(e["_raw"] for e in breakdown)
    # P7: without an identifier or a shared employer, names (and the education
    # tiebreaker) can reach uncertain but never the high band.
    strong = any(e["signal"] in ("email", "phone", "linkedin", "employer") and e["_raw"] > 0 for e in breakdown)
    if not strong:
        cap_pct = config["caps"]["name_only_percentage"] / 100.0
        cap_points = math.log2(cap_pct / (1 - cap_pct)) - prior_points
        if points > cap_points:
            breakdown.append(_entry(
                "name_only_cap", cap_points - points,
                "Only the name (and education) agree, so this is capped below the high band",
            ))
            flags.append("name_only_capped")
            points = cap_points

    percentage = to_percentage(points, prior_points)
    shown = round(percentage, 2)
    if shown >= 100.0 and percentage < 100.0:
        shown = 99.99
    # Rounding never lifts the shown value over a band threshold the band is below.
    for threshold in (config["bands"]["high"], config["bands"]["low"]):
        if percentage < threshold <= shown:
            shown = round(threshold - 0.01, 2)
    for e in breakdown:
        del e["_raw"]
    return {
        "points": round(points, 2),
        "percentage": shown,
        "band": band(percentage, config),
        "breakdown": breakdown,
        "flags": flags,
    }


def rank(profile: CandidateProfile, pool: list[CandidateProfile], context: MatchContext | None, config: dict) -> dict:
    """Every likely match (band above low), best first.

    Returns ``{"matches": [{candidate_id, name, points, percentage, band, breakdown,
    flags}], "flags": [...]}``. ``multiple_strong_matches`` is set when more than one
    candidate is high or a guaranteed match: the duplicates already exist on file,
    and all of them are returned (critique 9).
    """
    matches = []
    for existing in pool:
        result = score_pair(profile, existing, context, config)
        if result["band"] == "low":
            continue
        matches.append({"candidate_id": existing.candidate_id, "name": existing.display_name, **result})
    matches.sort(key=lambda m: (-m["points"], m["candidate_id"] if m["candidate_id"] is not None else 0))
    strong = [
        m for m in matches
        if m["band"] == "high" or any(f.startswith("guaranteed_match:") for f in m["flags"])
    ]
    return {"matches": matches, "flags": ["multiple_strong_matches"] if len(strong) > 1 else []}
