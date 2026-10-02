"""Scorer tests for the CR44 match check (signals, guards, caps, bands, rank, cases)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bullhorn_mcp.duplicates import (
    MatchContext,
    band,
    load_match_config,
    prior,
    profile_from_fields,
    rank,
    score_pair,
    to_percentage,
)

CASES = json.loads((Path(__file__).parent / "fixtures" / "match_cases.json").read_text(encoding="utf-8"))
N = 73815


@pytest.fixture(scope="module")
def cfg():
    return load_match_config()


def ms(year: int) -> int:
    return int(datetime(year, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)


def work(company, title=None, start=None, end=None):
    row = {"companyName": company, "title": title}
    if start:
        row["startDate"] = ms(start)
    if end:
        row["endDate"] = ms(end)
    return row


def edu(school=None, degree=None, year=None):
    row = {"school": school, "degree": degree}
    if year:
        row["graduationDate"] = ms(year)
    return row


def prof(fields=None, wh=None, ed=None):
    return profile_from_fields(fields or {}, wh or [], ed or [])


def run(a, b, cfg, **ctx):
    ctx.setdefault("n", N)
    return score_pair(a, b, MatchContext(**ctx), cfg)


def entries(res, signal):
    return [e for e in res["breakdown"] if e["signal"] == signal]


def pts(res, signal):
    return sum(e["points"] for e in entries(res, signal))


def agree(m, u):
    return math.log2(m / u)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

class TestNameSignals:
    @pytest.mark.parametrize("other,level", [
        ("Niamh", "exact"), ("Niaml", "typo"), ("N", "initial"),
    ])
    def test_forename_levels(self, cfg, other, level):
        res = run(prof({"firstName": "Niamh"}), prof({"firstName": other}), cfg)
        spec = cfg["forename"][level]
        assert pts(res, "first_name") == pytest.approx(agree(spec["m"], spec["u"]), abs=0.01)

    def test_forename_equivalent(self, cfg):
        res = run(prof({"firstName": "Sean"}), prof({"firstName": "John"}), cfg)
        spec = cfg["forename"]["equivalent"]
        assert pts(res, "first_name") == pytest.approx(agree(spec["m"], spec["u"]), abs=0.01)
        assert "equivalent" in entries(res, "first_name")[0]["reason"]

    def test_forename_different(self, cfg):
        res = run(prof({"firstName": "Niamh"}), prof({"firstName": "Orla"}), cfg)
        assert pts(res, "first_name") == cfg["forename"]["different"]["points"]

    def test_forename_exact_uses_count_when_given(self, cfg):
        common = run(prof({"firstName": "Niamh"}), prof({"firstName": "Niamh"}), cfg, forename_counts={"niamh": 5000})
        rare = run(prof({"firstName": "Niamh"}), prof({"firstName": "Niamh"}), cfg, forename_counts={"niamh": 5})
        assert pts(rare, "first_name") > pts(common, "first_name") > 0

    @pytest.mark.parametrize("other,level", [("Brennan", "exact"), ("Brennen", "fuzzy"), ("MacBrennan", "fuzzy")])
    def test_surname_levels(self, cfg, other, level):
        a = "McBrennan" if other == "MacBrennan" else "Brennan"
        res = run(prof({"lastName": a}), prof({"lastName": other}), cfg)
        spec = cfg["surname"][level]
        assert pts(res, "surname") == pytest.approx(agree(spec["m"], spec["u"]), abs=0.01)

    def test_surname_different(self, cfg):
        res = run(prof({"lastName": "Brennan"}), prof({"lastName": "Quirke"}), cfg)
        assert pts(res, "surname") == cfg["surname"]["different"]["points"]
        assert "marriage" in entries(res, "surname")[0]["reason"]

    def test_surname_exact_uses_count(self, cfg):
        common = run(prof({"lastName": "Brennan"}), prof({"lastName": "Brennan"}), cfg, surname_counts={"brennan": 3000})
        rare = run(prof({"lastName": "Brennan"}), prof({"lastName": "Brennan"}), cfg, surname_counts={"brennan": 3})
        assert pts(rare, "surname") > pts(common, "surname")

    def test_names_swapped(self, cfg):
        res = run(prof({"firstName": "Ruairi", "lastName": "Delaney"}),
                  prof({"firstName": "Delaney", "lastName": "Ruairi"}), cfg)
        assert "names_swapped" in res["flags"]
        assert pts(res, "first_name") > 0 and pts(res, "surname") > 0


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

class TestIdentifiers:
    def test_email_guaranteed(self, cfg):
        res = run(prof({"firstName": "Niamh", "email": "Niamh.B@Example.test"}),
                  prof({"firstName": "Niamh", "email2": "niamh.b@example.test"}), cfg)
        assert "guaranteed_match:email" in res["flags"]
        assert pts(res, "email") == pytest.approx(agree(cfg["identifiers"]["email"]["m"], cfg["identifiers"]["email"]["u"]), abs=0.01)

    @pytest.mark.parametrize("a,b", [
        ("087 726 0864", "+353 87 726 0864"),
        ("0877260864", "00353877260864"),
        ("(087) 726-0864", "353877260864"),
    ])
    def test_phone_guaranteed_across_stored_formats(self, cfg, a, b):
        res = run(prof({"mobile": a}), prof({"phone": b}), cfg)
        assert "guaranteed_match:phone" in res["flags"]

    @pytest.mark.parametrize("a,b", [
        ("https://www.linkedin.com/in/niamh-b", "ie.linkedin.com/in/Niamh-B/?x=1"),
        ("linkedin.com/pub/niamh-b/1a/2b/3c", "https://ie.linkedin.com/pub/Niamh-B/1a/2b/3c/"),
    ])
    def test_linkedin_guaranteed_both_forms(self, cfg, a, b):
        res = run(prof({"companyURL": a}), prof({"companyURL": b}), cfg)
        assert "guaranteed_match:linkedin" in res["flags"]

    @pytest.mark.parametrize("kind,fa,fb", [
        ("email", {"email": "a@example.test"}, {"email": "b@example.test"}),
        ("phone", {"mobile": "0877260864"}, {"mobile": "0861112222"}),
        ("linkedin", {"companyURL": "linkedin.com/in/one-x"}, {"companyURL": "linkedin.com/in/two-y"}),
    ])
    def test_differing_identifiers_use_differ_points(self, cfg, kind, fa, fb):
        res = run(prof(fa), prof(fb), cfg)
        assert pts(res, kind) == cfg["identifiers"][kind]["differ_points"]
        assert not any(f.startswith("guaranteed_match") for f in res["flags"])

    def test_missing_value_scores_zero(self, cfg):
        names = {"firstName": "Niamh", "lastName": "Brennan"}
        no_email = prof(names)
        with_email = prof({**names, "email": "niamh@example.test"})
        without = prof(names)
        r1 = run(no_email, with_email, cfg)
        r2 = run(no_email, without, cfg)
        assert entries(r1, "email") == []
        assert r1["points"] == r2["points"]
        assert not any("email" in f for f in r1["flags"])

    def test_tripped_guard_downgrades_identifier(self, cfg):
        a = prof({"firstName": "Niamh", "lastName": "Brennan", "email": "n@example.test"})
        b = prof({"firstName": "Niamh", "lastName": "Brennan", "email": "n@example.test"})
        unique = run(a, b, cfg, identifier_holders={"email": {"n@example.test": 1}})
        shared = run(a, b, cfg, identifier_holders={"email": {"n@example.test": 3}})
        assert "guaranteed_match:email" in unique["flags"]
        assert "guard_tripped:email" in shared["flags"]
        assert not any(f.startswith("guaranteed_match") for f in shared["flags"])
        assert shared["points"] < unique["points"]
        assert "3 candidates" in entries(shared, "email")[0]["reason"]

    def test_forenames_clearly_disagree_trips_guard(self, cfg):
        a = prof({"firstName": "Niamh", "email": "x@example.test"})
        b = prof({"firstName": "Orla", "email": "x@example.test"})
        res = run(a, b, cfg)
        assert "guard_tripped:email" in res["flags"]
        assert "first names clearly disagree" in entries(res, "email")[0]["reason"]

    def test_generic_mailbox_trips_guard(self, cfg):
        a = prof({"firstName": "Niamh", "email": "cv@agency.test"})
        res = run(a, a, cfg)
        assert "guard_tripped:email" in res["flags"]
        assert "role mailbox" in entries(res, "email")[0]["reason"]

    def test_generic_mailbox_scores_below_personal(self, cfg):
        gen = prof({"firstName": "Niamh", "email": "info@agency.test"})
        per = prof({"firstName": "Niamh", "email": "niamh@agency.test"})
        assert run(gen, gen, cfg)["points"] < run(per, per, cfg)["points"]

    def test_internal_email_trips_guard(self, cfg):
        a = prof({"firstName": "Niamh", "email": "consultant@thepanel.com"})
        res = run(a, a, cfg)
        assert "guard_tripped:email" in res["flags"]
        assert "internal" in entries(res, "email")[0]["reason"]


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------

class TestEmployers:
    def test_shared_employer_with_suffix_difference(self, cfg):
        res = run(prof(wh=[work("Quillon Brewer Ltd")]), prof(wh=[work("Quillon Brewer")]), cfg)
        assert len(entries(res, "employer")) == 1
        assert pts(res, "employer") == pytest.approx(agree(cfg["employer"]["m"], cfg["employer"]["default_u"]), abs=0.01)

    def test_employer_uses_count(self, cfg):
        a, b = prof(wh=[work("Quillon Brewer")]), prof(wh=[work("Quillon Brewer")])
        rare = run(a, b, cfg, employer_counts={"quillon brewer": 10})
        common = run(a, b, cfg, employer_counts={"quillon brewer": 5000})
        assert pts(rare, "employer") > pts(common, "employer")

    def test_employer_found_inside_title(self, cfg):
        a = prof(wh=[work("Freelance", "Consultant at Marrowfield Tech")])
        b = prof(wh=[work("Marrowfield Tech", "Consultant")])
        res = run(a, b, cfg)
        assert len(entries(res, "employer")) == 1
        assert "job title" in entries(res, "employer")[0]["reason"]

    def test_company_and_title_swapped_by_parser(self, cfg):
        a = prof(wh=[work("Senior Accountant", "Marrowfield Tech")])
        b = prof(wh=[work("Marrowfield Tech", "Senior Accountant")])
        assert len(entries(run(a, b, cfg), "employer")) >= 1

    def test_current_company_matches_work_history(self, cfg):
        a = prof({"companyName": "Quillon Brewer"})
        b = prof(wh=[work("Quillon Brewer", "Analyst", 2015, 2019)])
        assert len(entries(run(a, b, cfg), "employer")) == 1

    def test_generic_only_employer_does_not_match(self, cfg):
        res = run(prof(wh=[work("Bank")]), prof(wh=[work("Bank of Ireland")]), cfg)
        assert entries(res, "employer") == []

    def test_date_overlap_bonus(self, cfg):
        a = prof(wh=[work("Quillon Brewer", "Analyst", 2015, 2018)])
        over = prof(wh=[work("Quillon Brewer", "Director", 2016, 2019)])
        apart = prof(wh=[work("Quillon Brewer", "Director", 2019, 2021)])
        diff = pts(run(a, over, cfg), "employer") - pts(run(a, apart, cfg), "employer")
        assert diff == pytest.approx(cfg["employer"]["overlap_bonus"], abs=0.01)
        assert "dates overlap" in entries(run(a, over, cfg), "employer")[0]["reason"]

    def test_title_bonus_within_shared_employer(self, cfg):
        a = prof(wh=[work("Quillon Brewer", "Senior Accountant")])
        same = prof(wh=[work("Quillon Brewer", "Senior Accountant")])
        other = prof(wh=[work("Quillon Brewer", "Warehouse Operative")])
        diff = pts(run(a, same, cfg), "employer") - pts(run(a, other, cfg), "employer")
        assert diff == pytest.approx(cfg["employer"]["title_bonus"], abs=0.01)

    def test_employer_cap_three(self, cfg):
        names = ["Alderwick Works", "Brightmoor Mills", "Cresswell Press", "Dunmarrow Textiles", "Eastvale Foods"]
        a = prof(wh=[work(n) for n in names])
        b = prof(wh=[work(n + " Ltd") for n in names])
        res = run(a, b, cfg)
        assert len(entries(res, "employer")) == cfg["caps"]["max_employers"] == 3

    def test_duplicate_rows_not_counted_twice(self, cfg):
        a = prof(wh=[work("Quillon Brewer", "Analyst", 2010, 2012), work("Quillon Brewer", "Manager", 2012, 2014)])
        b = prof(wh=[work("Quillon Brewer")])
        assert len(entries(run(a, b, cfg), "employer")) == 1


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

class TestEducation:
    def test_school_and_year(self, cfg):
        res = run(prof(ed=[edu("Tarnmoor Institute", "BSc", 2008)]), prof(ed=[edu("Tarnmoor Institute", "BA", 2009)]), cfg)
        assert pts(res, "education") == cfg["education"]["school_and_year"]

    def test_school_only(self, cfg):
        res = run(prof(ed=[edu("Tarnmoor Institute", "BSc", 2008)]), prof(ed=[edu("Tarnmoor Institute", "BA", 2015)]), cfg)
        assert pts(res, "education") == cfg["education"]["school"]

    def test_school_without_years(self, cfg):
        res = run(prof(ed=[edu("Tarnmoor Institute")]), prof(ed=[edu("Tarnmoor Institute")]), cfg)
        assert pts(res, "education") == cfg["education"]["school"]

    def test_professional_qualification_match(self, cfg):
        res = run(prof(ed=[edu(None, "ACCA")]), prof(ed=[edu("Some Other Place", "ACCA")]), cfg)
        assert pts(res, "education") == cfg["education"]["qualification"]
        assert "ACCA" in entries(res, "education")[0]["reason"]

    def test_generic_degree_does_not_match(self, cfg):
        res = run(prof(ed=[edu("Alpha Hall", "Bachelors")]), prof(ed=[edu("Beta Hall", "Bachelors")]), cfg)
        assert entries(res, "education") == []

    def test_education_never_negative(self, cfg):
        res = run(prof(ed=[edu("Tarnmoor Institute", "BSc", 2008)]), prof(ed=[edu("Corrib College", "Higher Cert", 2001)]), cfg)
        assert entries(res, "education") == []
        assert all(e["points"] >= 0 for e in entries(res, "education"))

    def test_education_capped(self, cfg):
        schools = ["Tarnmoor Institute", "Corrib Polytechnic", "Marlow Academy", "Dunsany Seminary"]
        a = prof(ed=[edu(s, "BSc", 2008) for s in schools])
        b = prof(ed=[edu(s, "BA", 2008) for s in schools])
        res = run(a, b, cfg)
        total = pts(res, "education")
        assert 0 < total <= cfg["caps"]["education_points"] + 1e-9
        assert total == pytest.approx(cfg["caps"]["education_points"], abs=0.01)


# ---------------------------------------------------------------------------
# Whole-pair properties
# ---------------------------------------------------------------------------

def _pairs():
    full = {"firstName": "Ciaran", "lastName": "Dunmore", "email": "c@example.test", "mobile": "0877260864"}
    return [
        (prof(full, [work("Quillon Brewer", "Analyst", 2010, 2014)], [edu("Tarnmoor Institute", "BSc", 2008)]),
         prof({**full, "mobile": "00353877260864"}, [work("Quillon Brewer Ltd", "Analyst", 2011, 2015)], [edu("Tarnmoor Institute", "BA", 2009)])),
        (prof({"firstName": "Ruairi", "lastName": "Delaney"}, [work("Tolbrook Freight")]),
         prof({"firstName": "Delaney", "lastName": "Ruairi"}, [work("Tolbrook Freight")])),
        (prof({"firstName": "Sean", "lastName": "Murphy", "email": "cv@agency.test"}),
         prof({"firstName": "John", "lastName": "Murphy", "email": "cv@agency.test"})),
        (prof({"firstName": "Niamh", "lastName": "Brennan"}, [work("Freelance", "Consultant at Marrowfield Tech")]),
         prof({"firstName": "N", "lastName": "Brennen"}, [work("Marrowfield Tech", "Consultant")])),
        (prof({"firstName": "Niamh", "lastName": "Brennan"}), prof({"firstName": "Orla", "lastName": "Quirke"})),
        (prof({"firstName": "Niamh", "lastName": "Brennan", "companyName": "Quillon Brewer"}), prof({"firstName": "Niamh"}, [work("Quillon Brewer")])),
    ]


def test_pair_signals_symmetric(cfg):
    ctx = MatchContext(n=N, surname_counts={"dunmore": 40}, employer_counts={"quillon brewer": 25})
    for a, b in _pairs():
        ab, ba = score_pair(a, b, ctx, cfg), score_pair(b, a, ctx, cfg)
        assert ab["points"] == pytest.approx(ba["points"], abs=0.011)
        assert ab["band"] == ba["band"]


def test_agreeing_evidence_never_lowers_score(cfg):
    base_a = {"lastName": "Brennan"}
    base_b = {"lastName": "Brennan"}
    wa, wb, ea, eb = [], [], [], []
    last = run(prof(base_a, wa, ea), prof(base_b, wb, eb), cfg)["points"]
    steps = [
        lambda: (base_a.update(firstName="Niamh"), base_b.update(firstName="Niamh")),
        lambda: (base_a.update(email="n@example.test"), base_b.update(email="n@example.test")),
        lambda: (base_a.update(mobile="0877260864"), base_b.update(mobile="+353877260864")),
        lambda: (wa.append(work("Quillon Brewer")), wb.append(work("Quillon Brewer Ltd"))),
        lambda: (ea.append(edu("Tarnmoor Institute", "BSc", 2008)), eb.append(edu("Tarnmoor Institute", "BA", 2008))),
    ]
    for step in steps:
        before = run(prof(base_a, wa, ea), prof(base_b, wb, eb), cfg)["points"]
        step()
        after = run(prof(base_a, wa, ea), prof(base_b, wb, eb), cfg)["points"]
        assert after >= before
        assert after >= last
        last = after


def test_name_only_capped_below_high(cfg):
    a = prof({"firstName": "Niamh", "lastName": "Quillfeather"})
    res = run(a, a, cfg, forename_counts={"niamh": 1}, surname_counts={"quillfeather": 1})
    assert res["band"] != "high"
    assert "name_only_capped" in res["flags"]
    assert res["percentage"] == pytest.approx(cfg["caps"]["name_only_percentage"], abs=0.05)
    assert entries(res, "name_only_cap")


def test_cap_does_not_apply_with_shared_employer(cfg):
    a = prof({"firstName": "Niamh", "lastName": "Quillfeather"}, [work("Quillon Brewer")])
    res = run(a, a, cfg, forename_counts={"niamh": 1}, surname_counts={"quillfeather": 1})
    assert "name_only_capped" not in res["flags"]
    assert res["band"] == "high"


def test_breakdown_entries_well_formed_and_no_leaks(cfg):
    a, b = _pairs()[0]
    res = run(a, b, cfg)
    assert res["breakdown"]
    for e in res["breakdown"]:
        assert set(e) == {"signal", "points", "reason"}
        assert isinstance(e["reason"], str) and e["reason"].strip()
        assert isinstance(e["points"], (int, float))
    assert set(res) == {"points", "percentage", "band", "breakdown", "flags"}
    capped = run(prof({"firstName": "Niamh", "lastName": "Q"}), prof({"firstName": "Niamh", "lastName": "Q"}), cfg,
                 forename_counts={"niamh": 1}, surname_counts={"q": 1})
    for e in capped["breakdown"]:
        assert "_raw" not in e and e["reason"]


# ---------------------------------------------------------------------------
# prior / percentage / band
# ---------------------------------------------------------------------------

class TestMath:
    def test_prior(self, cfg):
        assert prior(N, cfg) == pytest.approx(-17.9, abs=0.05)

    def test_percentage_midpoint(self, cfg):
        p = prior(N, cfg)
        assert to_percentage(-p, p) == pytest.approx(50.0)

    def test_percentage_monotonic(self, cfg):
        p = prior(N, cfg)
        assert to_percentage(5, p) < to_percentage(10, p) < to_percentage(30, p)

    def test_band_boundaries(self, cfg):
        assert band(98.0, cfg) == "high"
        assert band(97.999, cfg) == "uncertain"
        assert band(20.0, cfg) == "uncertain"
        assert band(19.999, cfg) == "low"

    def test_extreme_points_do_not_overflow(self, cfg):
        p = prior(N, cfg)
        assert to_percentage(1e9, p) == pytest.approx(100.0)
        assert to_percentage(-1e9, p) == pytest.approx(0.0, abs=1e-9)
        assert to_percentage(float("inf"), p) == pytest.approx(100.0)

    def test_percentage_never_shows_100_for_non_certain(self, cfg):
        a = prof({"firstName": "Niamh", "lastName": "B", "email": "n@example.test", "mobile": "0877260864"})
        res = run(a, a, cfg)
        assert res["percentage"] <= 100.0

    def test_n_defaults_to_fallback(self, cfg):
        a = prof({"firstName": "Niamh", "lastName": "Brennan"})
        assert score_pair(a, a, None, cfg) == score_pair(a, a, MatchContext(n=cfg["population"]["fallback_n"]), cfg)


# ---------------------------------------------------------------------------
# rank
# ---------------------------------------------------------------------------

def _pool():
    full = {"firstName": "Niamh", "lastName": "Brennan", "email": "n@example.test"}
    strong = prof({**full, "id": 11}, [work("Quillon Brewer"), work("Marrowfield Tech")])
    strong2 = prof({**full, "id": 12})
    stranger = prof({"id": 13, "firstName": "Orla", "lastName": "Quirke", "email": "o@example.test"})
    return strong, strong2, stranger


def test_rank_drops_low_sorts_best_first_and_flags_multiple(cfg):
    strong, strong2, stranger = _pool()
    new = prof({"firstName": "Niamh", "lastName": "Brennan", "email": "n@example.test"},
               [work("Quillon Brewer"), work("Marrowfield Tech")])
    out = rank(new, [stranger, strong2, strong], MatchContext(n=N), cfg)
    ids = [m["candidate_id"] for m in out["matches"]]
    assert ids == [11, 12]
    assert out["matches"][0]["points"] >= out["matches"][1]["points"]
    assert out["flags"] == ["multiple_strong_matches"]
    assert out["matches"][0]["name"] == "Niamh Brennan"
    assert all(m["band"] != "low" for m in out["matches"])
    for m in out["matches"]:
        assert {"candidate_id", "name", "points", "percentage", "band", "breakdown", "flags"} <= set(m)


def test_rank_single_strong_no_multiple_flag(cfg):
    strong, _, stranger = _pool()
    new = prof({"firstName": "Niamh", "lastName": "Brennan", "email": "n@example.test"})
    out = rank(new, [stranger, strong], MatchContext(n=N), cfg)
    assert [m["candidate_id"] for m in out["matches"]] == [11]
    assert out["flags"] == []


def test_rank_empty_pool(cfg):
    assert rank(prof({"firstName": "Niamh"}), [], MatchContext(n=N), cfg) == {"matches": [], "flags": []}


# ---------------------------------------------------------------------------
# Case fixtures
# ---------------------------------------------------------------------------

def _profile(d):
    return profile_from_fields(d["fields"], d.get("work_history"), d.get("education"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_match_case(cfg, case):
    res = score_pair(_profile(case["profile"]), _profile(case["existing"]), MatchContext(**case["context"]), cfg)
    if "expected_band" in case:
        assert res["band"] == case["expected_band"], res
    if "expected_band_not" in case:
        assert res["band"] != case["expected_band_not"], res
    for flag in case.get("expected_flags", []):
        assert flag in res["flags"], res
