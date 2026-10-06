"""Candidate match check: Bullhorn retrieval and the one entry point (CR44, FR-23).

Builds the searches that find possible matches for a profile, fetches the pool's
records, fills the ``MatchContext`` the scorer needs, and exposes
``match_candidates``, the single function every caller uses. The scoring itself
lives in ``duplicates.py`` and stays pure.

Every profile-derived value placed in a Lucene query goes through
``_lucene_phrase`` (quoted values) or ``_lucene_term`` (bare words).
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import match_log
from .duplicates import (
    CandidateProfile,
    MatchContext,
    default_match_config,
    employer_words,
    linkedin_key,
    name_forms,
    name_key,
    normalize_email,
    normalize_phone,
    phone_search_variants,
    profile_from_record,
    rank,
)

_logger = logging.getLogger(__name__)

_PHONE_FIELDS = ("mobile", "phone", "workPhone", "phone2", "phone3")
_EMAIL_FIELDS = ("email", "email2", "email3")
_CANDIDATE_FIELDS = (
    "id,firstName,lastName,email,email2,email3,mobile,phone,workPhone,phone2,phone3,"
    "companyURL,companyName"
)
_WORK_FIELDS = "id,candidate,companyName,title,startDate,endDate"
_EDUCATION_FIELDS = "id,candidate,school,degree,certification,graduationDate,endDate"
_CHILD_PAGE = 500
_MAX_VALUES_PER_KIND = 3
_N_TTL_SECONDS = 24 * 60 * 60

_LUCENE_SPECIAL = set('+-!(){}[]^"~*?:\\/&|')


# ---------------------------------------------------------------------------
# Lucene escaping
# ---------------------------------------------------------------------------

def _lucene_phrase(value: str) -> str:
    """A quoted Lucene phrase with backslash and double quote escaped."""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _lucene_term(value: str) -> str:
    """A bare Lucene term with every special character and whitespace escaped."""
    out = []
    for ch in str(value):
        if ch in _LUCENE_SPECIAL or ch.isspace():
            out.append("\\")
        out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Live candidate count (N)
# ---------------------------------------------------------------------------

_n_cache: tuple[float, int] | None = None


def _reset_n_cache() -> None:
    global _n_cache
    _n_cache = None


def live_candidate_count(client, config: dict) -> int:
    """Live Candidate count, cached per process for 24 hours.

    Falls back to ``population.fallback_n`` on any error (the fallback is not cached).
    """
    global _n_cache
    now = time.monotonic()
    if _n_cache is not None and now - _n_cache[0] < _N_TTL_SECONDS:
        return _n_cache[1]
    try:
        total = client.search_with_meta("Candidate", "id:[1 TO *]", fields="id", count=1)["total"]
        if isinstance(total, bool) or not isinstance(total, int) or total <= 1:
            raise ValueError(f"unusable candidate total {total!r}")
    except Exception as exc:
        _logger.warning("live candidate count unavailable, using fallback: %s", exc)
        return config["population"]["fallback_n"]
    _n_cache = (now, total)
    return total


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

def _or(clauses: list[str]) -> str:
    return clauses[0] if len(clauses) == 1 else "(" + " OR ".join(clauses) + ")"


def _email_values(profile: CandidateProfile) -> list[str]:
    values = [e for e in map(normalize_email, profile.emails) if e]
    return list(dict.fromkeys(values))[:_MAX_VALUES_PER_KIND]


def _phone_values(profile: CandidateProfile, config: dict) -> list[str]:
    cc = config["default_country_code"]
    values = [p for p in (normalize_phone(x, cc) for x in profile.phones) if p]
    return list(dict.fromkeys(values))[:_MAX_VALUES_PER_KIND]


def _email_query(value: str) -> str:
    return _or([f"{f}:{_lucene_phrase(value)}" for f in _EMAIL_FIELDS])


def _phone_query(value: str, config: dict) -> str:
    variants = phone_search_variants(value, config["default_country_code"])
    return _or([f"{f}:{_lucene_phrase(v)}" for v in variants for f in _PHONE_FIELDS])


def _linkedin_query(key: str) -> str:
    # /in/<slug> is stored as the slug phrase; the old /pub/ form by its parts.
    phrase = key[3:] if key.startswith("in/") else key[4:].replace("/", " ")
    return f"companyURL:{_lucene_phrase(phrase)}"


def _surname_query(profile: CandidateProfile, with_initial: bool) -> str | None:
    forms = name_forms(profile.last_name)
    if not forms:
        return None
    query = _or([f"lastName:{_lucene_term(f)}~1" for f in forms])
    if with_initial:
        initial = (name_forms(profile.first_name) or [""])[0][:1]
        if initial:
            query = f"{query} AND firstName:{_lucene_term(initial)}*"
    return query


def _surname_count_query(profile: CandidateProfile) -> str | None:
    # Commonness only, and exact: the scorer uses it for an exact surname
    # agreement, and a ~1 total would also count every one-letter variant.
    forms = name_forms(profile.last_name)
    if not forms:
        return None
    return _or([f"lastName:{_lucene_term(f)}" for f in forms])


def _forename_query(profile: CandidateProfile) -> str | None:
    # Commonness only: without it an exact forename falls back to the config u,
    # which puts every same-name pair in the uncertain band and stops the create.
    forms = name_forms(profile.first_name)
    if not forms:
        return None
    return _or([f"firstName:{_lucene_term(f)}" for f in forms])


def _employer_query(key: str, config: dict) -> str | None:
    words = employer_words(key, config)
    if not words:
        return None
    joined = " AND ".join(_lucene_term(w) for w in words)
    return f"(workHistories.companyName:({joined}) OR workHistories.title:({joined}))"


# ---------------------------------------------------------------------------
# Pool retrieval
# ---------------------------------------------------------------------------

def _ids(data: list) -> list[int]:
    return [r["id"] for r in data if isinstance(r, dict) and isinstance(r.get("id"), int)]


def _run_search(client, query: str, cap: int) -> dict:
    result = client.search_with_meta("Candidate", query, fields="id", count=cap)
    return {"ids": _ids(result.get("data") or []), "total": result.get("total") or 0}


def _fetch_children(client, entity: str, ids: list[int], fields: str) -> list[dict]:
    where = f"candidate.id IN ({','.join(str(i) for i in ids)})"
    rows: list[dict] = []
    start = 0
    while True:
        page = client.query_with_meta(entity, where, fields=fields, count=_CHILD_PAGE, start=start)
        data = page.get("data") or []
        rows.extend(data)
        start += len(data)
        total = page.get("total")
        if not data or total is None or start >= total:
            return rows


def _group_by_candidate(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        cand = row.get("candidate")
        cid = cand.get("id") if isinstance(cand, dict) else cand
        if isinstance(cid, int):
            grouped.setdefault(cid, []).append(row)
    return grouped


def _fetch_pool_profiles(client, ids: list[int]) -> list[CandidateProfile]:
    if not ids:
        return []
    # /query/Candidate is refused by Bullhorn, so the records come from one /search.
    query = "id:(" + " OR ".join(str(i) for i in ids) + ")"
    result = client.search_with_meta("Candidate", query, fields=_CANDIDATE_FIELDS, count=len(ids))
    records = {r["id"]: r for r in result.get("data") or [] if isinstance(r, dict) and isinstance(r.get("id"), int)}
    live = [i for i in ids if i in records]
    work = _group_by_candidate(_fetch_children(client, "CandidateWorkHistory", live, _WORK_FIELDS)) if live else {}
    edu = _group_by_candidate(_fetch_children(client, "CandidateEducation", live, _EDUCATION_FIELDS)) if live else {}
    return [profile_from_record(records[i], work.get(i, []), edu.get(i, [])) for i in live]


# Count-only searches (count=1): they fill the context, never the pool.
_COUNT_KINDS = {"surname_count": "surname", "forename_count": "forename"}


def retrieve_pool(client, profile: CandidateProfile, config: dict) -> tuple[list[CandidateProfile], MatchContext, list[str]]:
    """Find, fetch and describe the candidates that could be the same person.

    Returns ``(pool, context, flags)``. One failed search becomes a
    ``lookup_failed:<kind>`` flag; a failed pool fetch raises.
    """
    cap = config["retrieval"]["pool_cap"]
    rerun_over = config["retrieval"]["employer_rerun_over"]
    cc = config["default_country_code"]

    # Settle the session and the Candidate isDeleted gate before fanning out.
    client.prepare_for_parallel("Candidate")

    surname_pool_query = _surname_query(profile, with_initial=True)
    surname_plain_query = _surname_query(profile, with_initial=False)

    # Each task: (kind, key, callable returning {"ids", "total", "flags"?}); order is search order.
    tasks: list[tuple[str, str, Callable[[], dict]]] = []
    for value in _email_values(profile):
        tasks.append(("email", value, lambda q=_email_query(value): _run_search(client, q, cap)))
    for value in _phone_values(profile, config):
        tasks.append(("phone", value, lambda q=_phone_query(value, config): _run_search(client, q, cap)))
    lkey = linkedin_key(profile.linkedin_url)
    if lkey:
        tasks.append(("linkedin", lkey, lambda q=_linkedin_query(lkey): _run_search(client, q, cap)))
    if surname_pool_query:
        tasks.append(("surname", "pool", lambda q=surname_pool_query: _run_search(client, q, cap)))
    surname_count_query = _surname_count_query(profile)
    if surname_count_query:
        tasks.append(("surname_count", "plain", lambda q=surname_count_query: _run_search(client, q, 1)))
    forename_query = _forename_query(profile)
    if forename_query:
        tasks.append(("forename_count", "plain", lambda q=forename_query: _run_search(client, q, 1)))

    def employer_task(emp_query: str) -> dict:
        first = _run_search(client, emp_query, cap)
        if first["total"] > rerun_over and surname_plain_query:
            try:
                second = _run_search(client, f"{emp_query} AND ({surname_plain_query})", cap)
            except Exception as exc:
                _logger.warning("employer rerun failed: %s", exc)
                return {**first, "flags": ["lookup_failed:employer_rerun"]}
            # Narrowed only if the rerun itself fits under the cap; else it is cut too.
            return {"ids": second["ids"], "total": first["total"], "narrowed": second["total"] <= cap}
        return first

    employer_keys = profile.to_echo(config)["employers"][: config["caps"]["max_employers"]]
    for ekey in employer_keys:
        equery = _employer_query(ekey, config)
        if equery:
            tasks.append(("employer", ekey, lambda q=equery: employer_task(q)))

    flags: list[str] = []
    results: list[tuple[str, str, dict | None]] = []
    if tasks:
        with ThreadPoolExecutor(max_workers=min(8, len(tasks))) as pool_exec:
            futures = [(kind, key, pool_exec.submit(fn)) for kind, key, fn in tasks]
            for kind, key, fut in futures:
                try:
                    results.append((kind, key, fut.result()))
                except Exception as exc:
                    _logger.warning("match lookup %s failed: %s", kind, exc)
                    flag = f"lookup_failed:{_COUNT_KINDS.get(kind, kind)}"
                    if flag not in flags:
                        flags.append(flag)
                    results.append((kind, key, None))

    union: list[int] = []
    seen: set[int] = set()
    truncated = False
    context = MatchContext()
    for kind, key, res in results:
        if res is None:
            continue
        for f in res.get("flags", []):
            if f not in flags:
                flags.append(f)
        if kind in ("email", "phone", "linkedin"):
            holders = res["total"]
            if profile.candidate_id is not None and profile.candidate_id in res["ids"]:
                holders = max(0, holders - 1)  # the profile's own record is not another holder
            context.identifier_holders.setdefault(kind, {})[key] = holders
        elif kind == "surname_count":
            skey = name_key(profile.last_name)
            if skey:
                context.surname_counts[skey] = res["total"]
        elif kind == "forename_count":
            fkey = name_key(profile.first_name)
            if fkey:
                context.forename_counts[fkey] = res["total"]
        elif kind == "employer":
            context.employer_counts[key] = res["total"]
        if kind in _COUNT_KINDS:
            continue
        if res["total"] > cap and not res.get("narrowed"):
            truncated = True
        for cid in res["ids"]:
            if cid not in seen:
                seen.add(cid)
                union.append(cid)

    if len(union) > cap:
        truncated = True
        union = union[:cap]
    if truncated:
        flags.append("lookup_hit_cutoff")

    context.n = live_candidate_count(client, config)
    pool = _fetch_pool_profiles(client, union)
    return pool, context, flags


# ---------------------------------------------------------------------------
# Soft-deleted lookup (D8a): ids and names only, never scored
# ---------------------------------------------------------------------------

def _deleted_query(clause: str) -> str:
    return f"({clause}) AND isDeleted:1"


def deleted_matches(client, profile: CandidateProfile, config: dict) -> list[dict]:
    """Soft-deleted candidates sharing an identifier or the exact name."""
    clauses: list[str] = []
    ident = [_email_query(v) for v in _email_values(profile)]
    ident += [_phone_query(v, config) for v in _phone_values(profile, config)]
    lkey = linkedin_key(profile.linkedin_url)
    if lkey:
        ident.append(_linkedin_query(lkey))
    if ident:
        clauses.append(" OR ".join(ident))
    firsts, lasts = name_forms(profile.first_name), name_forms(profile.last_name)
    if firsts and lasts:
        pairs = [f"(firstName:{_lucene_phrase(f)} AND lastName:{_lucene_phrase(l)})" for f in firsts for l in lasts]
        clauses.append(" OR ".join(pairs))

    found: dict[int, str] = {}
    for clause in clauses:
        try:
            result = client.search_with_meta(
                "Candidate", _deleted_query(clause), fields="id,firstName,lastName",
                count=20, exclude_deleted=False,
            )
        except Exception as exc:
            _logger.warning("deleted-candidate lookup failed: %s", exc)
            continue
        for row in result.get("data") or []:
            if isinstance(row, dict) and isinstance(row.get("id"), int) and row["id"] not in found:
                name = " ".join(p for p in (row.get("firstName"), row.get("lastName")) if p)
                found[row["id"]] = name
    return [{"candidate_id": cid, "name": name} for cid, name in found.items()]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def match_candidates(client, profile: CandidateProfile, config: dict | None = None, caller=None) -> dict:
    """Retrieve, score and log one match check; the one function every caller uses."""
    config = config or default_match_config()
    pool, context, retrieval_flags = retrieve_pool(client, profile, config)
    if profile.candidate_id is not None:
        pool = [p for p in pool if p.candidate_id != profile.candidate_id]
    ranked = rank(profile, pool, context, config)
    deleted = deleted_matches(client, profile, config)
    flags = list(dict.fromkeys(retrieval_flags + ranked["flags"]))
    result: dict[str, Any] = {
        "config_version": config["version"],
        "profile": profile.to_echo(config),
        "matches": ranked["matches"],
        "flags": flags,
        "deleted_matches": deleted,
    }
    match_check_id = match_log.new_match_check_id()
    match_log.log_check(
        match_check_id, caller=caller, config_version=config["version"], profile=profile, result=result,
    )
    return {"match_check_id": match_check_id, **result}
