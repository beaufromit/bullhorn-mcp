"""Fuzzy string matching and confidence scoring for duplicate detection."""

import difflib
import re
import string


# Legal entity suffixes to strip during normalization (not descriptive words like "group")
_SUFFIXES = {
    "ltd", "limited", "inc", "incorporated", "plc", "corp", "corporation",
    "llc", "pty",
}

# Stop words ignored when building candidate initials for acronym matching
_STOP_WORDS = {"of", "and", "the", "a", "an", "for", "in", "at", "by", "to", "&"}


def normalize(name: str) -> str:
    """Normalize a company name for fuzzy comparison.

    Lowercases, strips legal suffixes, removes punctuation, and collapses whitespace.

    Args:
        name: Company name to normalize

    Returns:
        Normalized string suitable for fuzzy comparison
    """
    name = name.lower()
    # Remove punctuation
    name = name.translate(str.maketrans("", "", string.punctuation))
    # Split into words, remove legal suffixes, rejoin
    words = [w for w in name.split() if w not in _SUFFIXES]
    return " ".join(words).strip()


def score_company_match(query: str, candidate: str) -> float:
    """Score how closely a query company name matches a candidate.

    Args:
        query: The name to search for
        candidate: A name from existing records to compare against

    Returns:
        Confidence score between 0.0 and 1.0
    """
    norm_query = normalize(query)
    norm_candidate = normalize(candidate)

    if not norm_query or not norm_candidate:
        return 0.0

    # Base score from sequence matching on normalized strings
    base_score = difflib.SequenceMatcher(None, norm_query, norm_candidate).ratio()

    # Acronym check: if query is all-uppercase letters, check whether they match
    # the initials of significant words in the candidate (stop words excluded).
    query_stripped = re.sub(r"[^A-Z]", "", query)
    candidate_words = [w for w in re.split(r"\s+", candidate.strip()) if w]
    sig_words = [w for w in candidate_words if w.lower() not in _STOP_WORDS]
    if (
        query_stripped
        and query_stripped == query.strip()  # query is purely uppercase letters
        and len(sig_words) >= len(query_stripped)
    ):
        initials = "".join(w[0].upper() for w in sig_words if w)
        if initials.startswith(query_stripped) or initials == query_stripped:
            # Strong acronym match — boost score
            base_score = max(base_score, 0.82)

    return min(max(base_score, 0.0), 1.0)


def categorize_score(score: float) -> str:
    """Return a confidence category for a given score.

    Args:
        score: Confidence score between 0.0 and 1.0

    Returns:
        "exact" (>= 0.95), "likely" (0.75–0.95), "possible" (0.50–0.75), or "none" (< 0.50)
    """
    if score >= 0.95:
        return "exact"
    if score >= 0.75:
        return "likely"
    if score >= 0.50:
        return "possible"
    return "none"


def score_contact_match(query_first: str, query_last: str, candidate: dict) -> float:
    """Score how closely a query contact name matches a candidate record.

    Args:
        query_first: First name to search for
        query_last: Last name to search for
        candidate: Dict with at least "firstName" and "lastName" keys

    Returns:
        Confidence score between 0.0 and 1.0
    """
    cand_first = candidate.get("firstName", "")
    cand_last = candidate.get("lastName", "")

    query_full = f"{query_first} {query_last}".lower().strip()
    cand_full = f"{cand_first} {cand_last}".lower().strip()

    if not query_full or not cand_full:
        return 0.0

    return difflib.SequenceMatcher(None, query_full, cand_full).ratio()
