"""Tests for candidate match retrieval (CR44, Sprint 42B T42B.1). All people are invented."""

from __future__ import annotations

import json
from unittest.mock import Mock, PropertyMock, patch

import httpx
import pytest
import respx

from bullhorn_mcp import duplicate_retrieval as dr
from bullhorn_mcp.auth import BullhornAuth
from bullhorn_mcp.client import BullhornClient
from bullhorn_mcp.duplicates import CandidateProfile, WorkEntry, default_match_config

CONFIG = default_match_config()


@pytest.fixture(autouse=True)
def _reset_n():
    dr._reset_n_cache()
    yield
    dr._reset_n_cache()


class FakeBullhorn:
    """respx-backed Bullhorn: records every request and answers by simple rules."""

    def __init__(self, rest_url: str):
        self.rest_url = rest_url
        self.searches: list[dict] = []   # {"entity", "query", "fields", "count"}
        self.queries: list[dict] = []    # {"entity", "where", "fields", "count", "start"}
        self.search_rules: list[tuple] = []  # (predicate(query), response dict or Exception)
        self.child_rows = {"CandidateWorkHistory": [], "CandidateEducation": []}
        self.candidates: dict[int, dict] = {}
        self.n_total = 5000
        self.fail_children = False

    def on_search(self, predicate, ids=None, total=None, status=200):
        ids = ids or []
        body = {"data": [{"id": i} for i in ids], "total": len(ids) if total is None else total}
        self.search_rules.append((predicate, (status, body)))

    def _search(self, request: httpx.Request):
        p = dict(request.url.params)
        entity = request.url.path.rsplit("/", 1)[-1]
        self.searches.append({"entity": entity, "query": p["query"], "fields": p["fields"], "count": p["count"]})
        q = p["query"]
        if q.startswith("(id:[1 TO *])"):
            return httpx.Response(200, json={"data": [{"id": 1}], "total": self.n_total})
        if q.startswith("(id:(") or q.startswith("id:("):
            wanted = [int(x) for x in q.split("id:(")[1].split(")")[0].split(" OR ")]
            return httpx.Response(200, json={"data": [self.candidates[i] for i in wanted if i in self.candidates], "total": len(wanted)})
        for predicate, (status, body) in self.search_rules:
            if predicate(q):
                return httpx.Response(status, json=body if status == 200 else {"errorMessage": "boom"})
        return httpx.Response(200, json={"data": [], "total": 0})

    def _query(self, request: httpx.Request):
        p = dict(request.url.params)
        entity = request.url.path.rsplit("/", 1)[-1]
        self.queries.append({"entity": entity, "where": p["where"], "fields": p["fields"], "count": p["count"], "start": p["start"]})
        if self.fail_children:
            return httpx.Response(500, text="boom")
        rows = self.child_rows[entity]
        start, count = int(p["start"]), int(p["count"])
        return httpx.Response(200, json={"data": rows[start:start + count], "total": len(rows)})

    def install(self, router: respx.MockRouter):
        base = self.rest_url
        for entity in ("Candidate", "CandidateWorkHistory", "CandidateEducation"):
            router.get(f"{base}/meta/{entity}").mock(
                return_value=httpx.Response(200, json={"entity": entity, "fields": [{"name": "isDeleted"}]})
            )
        router.get(url__regex=rf"{base}/search/Candidate.*").mock(side_effect=self._search)
        router.get(url__regex=rf"{base}/query/Candidate(WorkHistory|Education).*").mock(side_effect=self._query)


@pytest.fixture
def bh(mock_session):
    fake = FakeBullhorn(mock_session.rest_url)
    auth = Mock(spec=BullhornAuth)
    type(auth).session = PropertyMock(return_value=mock_session)
    fake.client = BullhornClient(auth)
    with respx.mock(assert_all_called=False) as router:
        fake.install(router)
        yield fake


def profile(**kw) -> CandidateProfile:
    base = dict(first_name="Aoife", last_name="Zephyr")
    base.update(kw)
    return CandidateProfile(**base)


def queries_matching(bh, needle):
    return [s["query"] for s in bh.searches if needle in s["query"]]


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------

class TestEscaping:
    def test_phrase_escapes_quote_and_backslash(self):
        assert dr._lucene_phrase('a"b\\c') == '"a\\"b\\\\c"'

    def test_term_escapes_every_special(self):
        for ch in '+-!(){}[]^"~*?:\\/ ':
            assert dr._lucene_term(f"a{ch}b") == f"a\\{ch}b"
        assert dr._lucene_term("a&&b||c") == "a\\&\\&b\\|\\|c"
        assert dr._lucene_term("plain") == "plain"

    def test_values_are_escaped(self, bh):
        p = profile(
            last_name='Qu"ux (x)', first_name="Zed",
            emails=['a"b@example.test'], linkedin_url=None,
            work_history=[WorkEntry(company="Wibble+Wobble Ltd")],
        )
        dr.retrieve_pool(bh.client, p, CONFIG)
        qs = [s["query"] for s in bh.searches if not s["query"].startswith(("(id:", "id:"))]
        assert any('email:"a\\"b@example.test"' in q for q in qs)
        assert any('lastName:qu\\"ux\\ \\(x\\)~1' in q for q in qs)
        assert any("wibble\\+wobble" not in q and "wibble AND wobble" in q for q in qs)


# ---------------------------------------------------------------------------
# One test per search shape
# ---------------------------------------------------------------------------

class TestSearchShapes:
    def test_email_search(self, bh):
        dr.retrieve_pool(bh.client, profile(emails=["Aoife.Z@Example.test"]), CONFIG)
        assert queries_matching(bh, "email") == [
            '((email:"aoife.z@example.test" OR email2:"aoife.z@example.test" OR email3:"aoife.z@example.test")) AND isDeleted:0'
        ]

    def test_phone_search_uses_variants_across_fields(self, bh):
        dr.retrieve_pool(bh.client, profile(phones=["085 726 0864"]), CONFIG)
        [q] = queries_matching(bh, "mobile:")
        clauses = [
            f'{f}:"{v}"'
            for v in ("+353857260864", "0857260864", "353857260864")
            for f in ("mobile", "phone", "workPhone", "phone2", "phone3")
        ]
        assert q == "((" + " OR ".join(clauses) + ")) AND isDeleted:0"

    def test_linkedin_in_slug(self, bh):
        dr.retrieve_pool(bh.client, profile(linkedin_url="https://ie.linkedin.com/in/Aoife-Zephyr-12/"), CONFIG)
        assert queries_matching(bh, "companyURL") == ['(companyURL:"aoife-zephyr-12") AND isDeleted:0']

    def test_linkedin_pub_key_uses_parts(self, bh):
        dr.retrieve_pool(bh.client, profile(linkedin_url="linkedin.com/pub/aoife-zephyr/a/216/98"), CONFIG)
        assert queries_matching(bh, "companyURL") == ['(companyURL:"aoife-zephyr a 216 98") AND isDeleted:0']

    def test_surname_with_initial_and_plain_count(self, bh):
        dr.retrieve_pool(bh.client, profile(), CONFIG)
        # searches run in parallel, so arrival order is not fixed
        assert sorted(queries_matching(bh, "lastName")) == sorted([
            "(lastName:zephyr~1 AND firstName:a*) AND isDeleted:0",
            "(lastName:zephyr~1) AND isDeleted:0",
        ])

    def test_surname_both_apostrophe_forms(self, bh):
        dr.retrieve_pool(bh.client, profile(last_name="O'Brien"), CONFIG)
        assert sorted(queries_matching(bh, "lastName")) == sorted([
            "((lastName:o'brien~1 OR lastName:obrien~1) AND firstName:a*) AND isDeleted:0",
            "((lastName:o'brien~1 OR lastName:obrien~1)) AND isDeleted:0",
        ])

    def test_forename_count_search_both_apostrophe_forms(self, bh):
        dr.retrieve_pool(bh.client, profile(first_name="D'Arcy"), CONFIG)
        assert [q for q in queries_matching(bh, "firstName") if "lastName" not in q] == [
            "((firstName:d'arcy OR firstName:darcy)) AND isDeleted:0",
        ]
        counts = [s for s in bh.searches if s["query"].startswith("((firstName:d'arcy")]
        assert counts[0]["count"] == "1"

    def test_forename_count_fills_context_not_pool(self, bh):
        bh.on_search(lambda q: q.startswith("(firstName:aoife)"), ids=[77], total=276)
        bh.candidates = {77: {"id": 77}}
        pool, ctx, flags = dr.retrieve_pool(bh.client, profile(), CONFIG)
        assert ctx.forename_counts == {"aoife": 276}
        assert pool == [] and flags == []

    def test_forename_count_failure_is_flag(self, bh):
        bh.on_search(lambda q: q.startswith("(firstName:aoife)"), status=500)
        _, ctx, flags = dr.retrieve_pool(bh.client, profile(), CONFIG)
        assert "lookup_failed:forename" in flags
        assert ctx.forename_counts == {}

    def test_surname_without_first_name_is_one_search(self, bh):
        dr.retrieve_pool(bh.client, profile(first_name=None), CONFIG)
        assert queries_matching(bh, "lastName") == ["(lastName:zephyr~1) AND isDeleted:0"]

    def test_employer_company_and_title(self, bh):
        p = profile(first_name=None, last_name=None, work_history=[WorkEntry(company="Wibble Wobble Ltd")])
        dr.retrieve_pool(bh.client, p, CONFIG)
        assert queries_matching(bh, "workHistories") == [
            "((workHistories.companyName:(wibble AND wobble) OR workHistories.title:(wibble AND wobble))) AND isDeleted:0"
        ]

    def test_employers_capped_at_three(self, bh):
        wh = [WorkEntry(company=c) for c in ("Alpha One", "Bravo Two", "Charlie Three", "Delta Four")]
        dr.retrieve_pool(bh.client, profile(first_name=None, last_name=None, work_history=wh), CONFIG)
        assert len(queries_matching(bh, "workHistories")) == 3

    def test_absent_inputs_skip_searches(self, bh):
        pool, ctx, flags = dr.retrieve_pool(bh.client, CandidateProfile(), CONFIG)
        assert pool == [] and flags == []
        assert [s for s in bh.searches if not s["query"].startswith("(id:[1")] == []


# ---------------------------------------------------------------------------
# Union, cap, reruns, failures
# ---------------------------------------------------------------------------

class TestPool:
    def test_union_dedupes(self, bh):
        bh.on_search(lambda q: "email:" in q, ids=[11, 12])
        bh.on_search(lambda q: "firstName:a*" in q, ids=[12, 13])
        bh.candidates = {i: {"id": i, "firstName": "A", "lastName": "Zephyr"} for i in (11, 12, 13)}
        pool, _, _ = dr.retrieve_pool(bh.client, profile(emails=["a@example.test"]), CONFIG)
        assert [p.candidate_id for p in pool] == [11, 12, 13]
        [fetch] = [s for s in bh.searches if s["query"].startswith("(id:(")]
        assert fetch["query"] == "(id:(11 OR 12 OR 13)) AND isDeleted:0"
        assert fetch["fields"] == dr._CANDIDATE_FIELDS
        assert fetch["count"] == "3"

    def test_candidate_pool_fetched_by_search_not_query(self, bh):
        bh.on_search(lambda q: "email:" in q, ids=[11])
        bh.candidates = {11: {"id": 11, "firstName": "A", "lastName": "Z"}}
        dr.retrieve_pool(bh.client, profile(emails=["a@example.test"]), CONFIG)
        assert all(q["entity"] != "Candidate" for q in bh.queries)

    def test_pool_fetch_single_query_per_child_entity(self, bh):
        bh.on_search(lambda q: "email:" in q, ids=[11, 12])
        bh.candidates = {i: {"id": i, "firstName": "A", "lastName": "Z"} for i in (11, 12)}
        bh.child_rows["CandidateWorkHistory"] = [
            {"id": 1, "candidate": {"id": 11}, "companyName": "Wibble Ltd", "title": "Analyst"},
            {"id": 2, "candidate": {"id": 12}, "companyName": "Wobble Ltd", "title": "Clerk"},
        ]
        bh.child_rows["CandidateEducation"] = [{"id": 3, "candidate": {"id": 11}, "school": "Quux College"}]
        pool, _, _ = dr.retrieve_pool(bh.client, profile(emails=["a@example.test"]), CONFIG)
        assert bh.queries == [
            {"entity": "CandidateWorkHistory", "where": "(candidate.id IN (11,12)) AND isDeleted=false",
             "fields": dr._WORK_FIELDS, "count": "500", "start": "0"},
            {"entity": "CandidateEducation", "where": "(candidate.id IN (11,12)) AND isDeleted=false",
             "fields": dr._EDUCATION_FIELDS, "count": "500", "start": "0"},
        ]
        assert pool[0].work_history[0].company == "Wibble Ltd"
        assert pool[0].education[0].school == "Quux College"
        assert pool[1].work_history[0].company == "Wobble Ltd"

    def test_child_rows_are_paged(self, bh):
        bh.on_search(lambda q: "email:" in q, ids=[11])
        bh.candidates = {11: {"id": 11, "firstName": "A", "lastName": "Z"}}
        bh.child_rows["CandidateWorkHistory"] = [
            {"id": i, "candidate": {"id": 11}, "companyName": f"Co{i}"} for i in range(1, 701)
        ]
        pool, _, _ = dr.retrieve_pool(bh.client, profile(emails=["a@example.test"]), CONFIG)
        wh = [q for q in bh.queries if q["entity"] == "CandidateWorkHistory"]
        assert [q["start"] for q in wh] == ["0", "500"]
        assert len(pool[0].work_history) == 700

    def test_employer_over_200_reruns_with_surname_keeps_total(self, bh):
        emp = "(workHistories.companyName:(wibble AND wobble) OR workHistories.title:(wibble AND wobble))"
        bh.on_search(lambda q: q.startswith("((" + emp[1:]) and "lastName" in q, ids=[21])
        bh.on_search(lambda q: "workHistories" in q, ids=[1, 2], total=450)
        bh.candidates = {21: {"id": 21, "firstName": "A", "lastName": "Zephyr"}}
        p = profile(first_name=None, work_history=[WorkEntry(company="Wibble Wobble")])
        pool, ctx, flags = dr.retrieve_pool(bh.client, p, CONFIG)
        wh = queries_matching(bh, "workHistories")
        assert wh[1] == f"({emp} AND (lastName:zephyr~1)) AND isDeleted:0"
        assert ctx.employer_counts == {"wibble wobble": 450}
        assert [x.candidate_id for x in pool] == [21]
        assert "lookup_hit_cutoff" not in flags

    def test_employer_over_200_without_surname_not_rerun(self, bh):
        bh.on_search(lambda q: "workHistories" in q, ids=[1], total=450)
        p = profile(first_name=None, last_name=None, work_history=[WorkEntry(company="Wibble Wobble")])
        _, ctx, flags = dr.retrieve_pool(bh.client, p, CONFIG)
        assert len(queries_matching(bh, "workHistories")) == 1
        assert ctx.employer_counts == {"wibble wobble": 450}
        assert "lookup_hit_cutoff" in flags

    def test_pool_cap_sets_cutoff_flag(self, bh):
        cfg = json.loads(json.dumps(CONFIG))
        cfg["retrieval"]["pool_cap"] = 3
        bh.on_search(lambda q: "email:" in q, ids=[1, 2, 3])
        bh.on_search(lambda q: "firstName:a*" in q, ids=[4, 5])
        bh.candidates = {i: {"id": i, "firstName": "A", "lastName": "Z"} for i in range(1, 6)}
        pool, _, flags = dr.retrieve_pool(bh.client, profile(emails=["a@example.test"]), cfg)
        assert [p.candidate_id for p in pool] == [1, 2, 3]
        assert "lookup_hit_cutoff" in flags
        assert all(s["count"] == "3" for s in bh.searches if "email:" in s["query"])

    def test_one_search_failure_is_flag(self, bh):
        bh.on_search(lambda q: "email:" in q, status=500)
        bh.on_search(lambda q: "firstName:a*" in q, ids=[7])
        bh.candidates = {7: {"id": 7, "firstName": "A", "lastName": "Zephyr"}}
        pool, _, flags = dr.retrieve_pool(bh.client, profile(emails=["a@example.test"]), CONFIG)
        assert flags == ["lookup_failed:email"]
        assert [p.candidate_id for p in pool] == [7]

    def test_pool_fetch_failure_raises(self, bh):
        bh.on_search(lambda q: "email:" in q, ids=[7])
        bh.candidates = {7: {"id": 7}}
        bh.fail_children = True
        with pytest.raises(Exception):
            dr.retrieve_pool(bh.client, profile(emails=["a@example.test"]), CONFIG)

    def test_context_counts(self, bh):
        bh.on_search(lambda q: "email:" in q, ids=[11, 12])
        bh.on_search(lambda q: "mobile:" in q, ids=[11], total=1)
        bh.on_search(lambda q: "lastName" in q and "firstName" not in q, ids=[11], total=80)
        bh.candidates = {i: {"id": i} for i in (11, 12)}
        p = profile(emails=["a@example.test"], phones=["0857260864"])
        _, ctx, _ = dr.retrieve_pool(bh.client, p, CONFIG)
        assert ctx.n == 5000
        assert ctx.identifier_holders == {"email": {"a@example.test": 2}, "phone": {"+353857260864": 1}}
        assert ctx.surname_counts == {"zephyr": 80}

    def test_own_record_not_counted_as_holder(self, bh):
        bh.on_search(lambda q: "email:" in q, ids=[11, 12])
        bh.candidates = {i: {"id": i} for i in (11, 12)}
        _, ctx, _ = dr.retrieve_pool(bh.client, profile(emails=["a@example.test"], candidate_id=11), CONFIG)
        assert ctx.identifier_holders["email"] == {"a@example.test": 1}


# ---------------------------------------------------------------------------
# Deleted lookup
# ---------------------------------------------------------------------------

class TestDeleted:
    def test_deleted_lookup_not_scored(self, bh):
        bh.on_search(lambda q: "isDeleted:1" in q and "email:" in q, ids=[])
        bh.search_rules.append((lambda q: "isDeleted:1" in q, (200, {
            "data": [{"id": 91, "firstName": "Aoife", "lastName": "Zephyr"}], "total": 1})))
        out = dr.deleted_matches(bh.client, profile(emails=["a@example.test"]), CONFIG)
        assert out == [{"candidate_id": 91, "name": "Aoife Zephyr"}]
        assert [s["query"] for s in bh.searches] == [
            '((email:"a@example.test" OR email2:"a@example.test" OR email3:"a@example.test")) AND isDeleted:1',
            '((firstName:"aoife" AND lastName:"zephyr")) AND isDeleted:1',
        ]
        assert all(s["fields"] == "id,firstName,lastName" for s in bh.searches)

    def test_deleted_failure_gives_empty(self, bh):
        bh.on_search(lambda q: "isDeleted:1" in q, status=500)
        assert dr.deleted_matches(bh.client, profile(emails=["a@example.test"]), CONFIG) == []

    def test_deleted_lookup_needs_a_signal(self, bh):
        assert dr.deleted_matches(bh.client, CandidateProfile(), CONFIG) == []
        assert bh.searches == []


# ---------------------------------------------------------------------------
# N
# ---------------------------------------------------------------------------

class TestN:
    def test_n_cached_and_falls_back(self):
        client = Mock()
        client.search_with_meta.return_value = {"total": 70000}
        assert dr.live_candidate_count(client, CONFIG) == 70000
        client.search_with_meta.return_value = {"total": 99}
        assert dr.live_candidate_count(client, CONFIG) == 70000
        assert client.search_with_meta.call_count == 1
        client.search_with_meta.assert_called_once_with("Candidate", "id:[1 TO *]", fields="id", count=1)

        dr._reset_n_cache()
        client.search_with_meta.side_effect = RuntimeError("down")
        assert dr.live_candidate_count(client, CONFIG) == CONFIG["population"]["fallback_n"]

    def test_n_cache_expires_after_24_hours(self):
        client = Mock()
        client.search_with_meta.return_value = {"total": 70000}
        with patch("bullhorn_mcp.duplicate_retrieval.time.monotonic", return_value=1000.0):
            dr.live_candidate_count(client, CONFIG)
        client.search_with_meta.return_value = {"total": 71000}
        with patch("bullhorn_mcp.duplicate_retrieval.time.monotonic", return_value=1000.0 + 24 * 3600 + 1):
            assert dr.live_candidate_count(client, CONFIG) == 71000

    def test_unusable_total_falls_back(self):
        client = Mock()
        client.search_with_meta.return_value = {"total": None}
        assert dr.live_candidate_count(client, CONFIG) == CONFIG["population"]["fallback_n"]


# ---------------------------------------------------------------------------
# match_candidates
# ---------------------------------------------------------------------------

class TestMatchCandidates:
    @pytest.fixture
    def log(self):
        with patch("bullhorn_mcp.duplicate_retrieval.match_log") as m:
            m.new_match_check_id.return_value = "mc-1"
            yield m

    def test_match_candidates_logs_once(self, bh, log):
        bh.on_search(lambda q: "email:" in q and "isDeleted:0" in q, ids=[11])
        bh.candidates = {11: {"id": 11, "firstName": "Aoife", "lastName": "Zephyr", "email": "a@example.test"}}
        out = dr.match_candidates(bh.client, profile(emails=["a@example.test"]), caller={"id": 5})
        log.log_check.assert_called_once()
        args, kw = log.log_check.call_args
        assert args == ("mc-1",)
        assert kw["caller"] == {"id": 5}
        assert kw["config_version"] == CONFIG["version"]
        assert kw["result"]["matches"] == out["matches"]
        assert "match_check_id" not in kw["result"]
        assert out["match_check_id"] == "mc-1"
        assert out["matches"][0]["candidate_id"] == 11
        assert out["matches"][0]["band"] == "high"

    def test_match_candidates_echoes_profile(self, bh, log):
        p = profile(emails=[" A@Example.TEST "])
        out = dr.match_candidates(bh.client, p)
        assert out["profile"] == p.to_echo(CONFIG)
        assert out["profile"]["emails"] == ["a@example.test"]
        assert set(out) == {"match_check_id", "config_version", "profile", "matches", "flags", "deleted_matches"}
        assert out["config_version"] == CONFIG["version"]

    def test_match_candidates_excludes_self(self, bh, log):
        bh.on_search(lambda q: "email:" in q and "isDeleted:0" in q, ids=[11, 12])
        rec = {"firstName": "Aoife", "lastName": "Zephyr", "email": "a@example.test"}
        bh.candidates = {11: {"id": 11, **rec}, 12: {"id": 12, **rec}}
        out = dr.match_candidates(bh.client, profile(emails=["a@example.test"], candidate_id=11))
        assert [m["candidate_id"] for m in out["matches"]] == [12]

    def test_match_candidates_reports_flags_and_deleted(self, bh, log):
        bh.on_search(lambda q: "isDeleted:1" in q, ids=[91])
        bh.on_search(lambda q: "email:" in q, status=500)
        out = dr.match_candidates(bh.client, profile(emails=["a@example.test"]))
        assert "lookup_failed:email" in out["flags"]
        assert out["deleted_matches"][0]["candidate_id"] == 91
