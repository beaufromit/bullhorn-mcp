#!/usr/bin/env python
"""CR44 D10 calibration: live AGGREGATE counts only. READ-ONLY.

Usage (from repo root):
    .venv/bin/python scripts/calibrate_match.py

Prints totals only (population, identifier-holder counts, coverage, totals for
common surnames/forenames/employer words). It never prints, stores or logs a
record, a person's name, an id or a field value. The surname, forename and
employer words below are a fixed list of common terms, not people.
Uses search_with_meta(count=1) only, about 70 calls. Never writes anything.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from bullhorn_mcp.config import BullhornConfig  # noqa: E402
from bullhorn_mcp.auth import BullhornAuth  # noqa: E402
from bullhorn_mcp.client import BullhornClient  # noqa: E402

SURNAMES = ["murphy", "kelly", "byrne", "ryan", "o'brien", "obrien", "walsh", "smith",
            "o'sullivan", "doyle", "mccarthy", "cassidy"]
FORENAMES = ["john", "mary", "sean", "patrick", "aoife", "sarah", "michael", "ciara"]
PAIRS = [("john", "murphy"), ("mary", "kelly")]
EMPLOYER_WORDS = ["bank", "ireland", "group", "services", "capital"]
EMPLOYERS = [("kpmg", "kpmg"), ("deloitte", "deloitte"), ("bank of ireland", "bank AND of AND ireland"),
             ("aib", "aib")]


def main() -> int:
    config = BullhornConfig.from_env()
    client = BullhornClient(BullhornAuth(config))
    client.auth.session  # noqa: B018  (triggers auth)
    calls = 0

    def total(query: str, **kw):
        nonlocal calls
        calls += 1
        try:
            return client.search_with_meta("Candidate", query, fields="id", count=1, **kw)["total"]
        except Exception as e:  # noqa: BLE001
            return f"ERR({str(e)[:60].replace(chr(10), ' ')})"

    out: dict = {}
    n = total("id:[1 TO *]")
    out["N_live"] = n
    out["N_incl_deleted"] = total("id:[1 TO *]", exclude_deleted=False)
    print(f"N live={n} incl_deleted={out['N_incl_deleted']}")

    # Identifier form probe (one prefix) so we know which Lucene form works.
    print("-- email query form probe (prefix 'info')")
    for form in ['email:info@*', 'email:"info@"', 'email:info*', 'email:"info"', 'email:info@thepanel.com']:
        print(f"  {form!r:32} -> {total(form)}")
    print("-- generic mailbox prefix holders (form email:<p>*, local part prefix)")
    prefixes = json.loads((REPO_ROOT / "src/bullhorn_mcp/match_config.json").read_text())["generic_mailbox_prefixes"]
    for p in prefixes:
        print(f"  {p:14} email:{p}@* -> {total(f'email:{p}@*')}")
    print(f"  @thepanel.com email:*@thepanel.com -> {total('email:*@thepanel.com')}")
    print(f"  @thepanel.com email:*thepanel.com  -> {total('email:*thepanel.com')}")
    print(f"  @thepanel.com email:\"thepanel.com\" -> {total('email:\"thepanel.com\"')}")

    print("-- coverage")
    for label, q in [("email", "email:[* TO *]"), ("mobile", "mobile:[* TO *]"),
                     ("companyURL", "companyURL:[* TO *]"), ("companyURL linkedin", "companyURL:*linkedin*")]:
        t = total(q)
        pct = f" ({100 * t / n:.1f}%)" if isinstance(t, int) and isinstance(n, int) else ""
        print(f"  {label:22} {t}{pct}")

    print("-- surnames: exact, fuzzy~1 (total, share of N)")
    sq = 0.0
    for s in SURNAMES:
        q = f'lastName:"{s}"' if "'" in s else f"lastName:{s}"
        e = total(q)
        f = total(f'lastName:{s.replace(chr(39), "")}~1')
        share = f"{e / n:.5f}" if isinstance(e, int) else "-"
        if isinstance(e, int):
            sq += (e / n) ** 2
        print(f"  {s:12} exact={e} share={share} fuzzy={f}")
    print(f"  sum of squared shares over listed surnames = {sq:.2e}")

    print("-- forenames")
    fq = 0.0
    for s in FORENAMES:
        e = total(f"firstName:{s}")
        if isinstance(e, int):
            fq += (e / n) ** 2
        print(f"  {s:10} exact={e} share={e / n if isinstance(e, int) else '-'}")
    print(f"  sum of squared shares over listed forenames = {fq:.2e}")
    for fn, sn in PAIRS:
        print(f"  pair {fn}+{sn}: {total(f'firstName:{fn} AND lastName:{sn}')}")

    print("-- employer words (nested workHistories.companyName)")
    for w in EMPLOYER_WORDS:
        print(f"  {w:10} {total(f'workHistories.companyName:({w})')}")
    for label, expr in EMPLOYERS:
        print(f"  {label:16} {total(f'workHistories.companyName:({expr})')}")
    print(f"live calls: {calls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
