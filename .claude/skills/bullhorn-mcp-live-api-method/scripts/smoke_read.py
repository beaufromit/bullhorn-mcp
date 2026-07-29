#!/usr/bin/env python
"""Live-tenant smoke check: auth + one read-only call per core entity. READ-ONLY.

Usage (from repo root):
    .venv/bin/python .claude/skills/bullhorn-mcp-live-api-method/scripts/smoke_read.py

Authenticates via BullhornConfig.from_env(), then runs one read-only call per
core entity and prints the total record count Bullhorn reports. Answers "is
the tenant reachable and sane?" in under a minute.

Endpoint choice per entity is itself live-verified knowledge (2026-07-03):
- /search (Lucene) for ClientCorporation, ClientContact, Candidate, JobOrder,
  JobSubmission, Placement. Candidate REJECTS /query entirely on this tenant
  ("Query operation not supported ... please use /search").
- /query for PlacementChangeRequest: it is NOT a search entity
  ("Unknown search entity"). /query returns total only with
  showTotalMatched=true.
- Note has no /query endpoint; reachability is checked via /meta.

Two note-route canaries run at the end. They watch for CHANGE IN EITHER
DIRECTION, not for breakage, because how notes behave here is the design we
build against rather than a fault to escalate:

- /search/Note match-all: 0 on this account today. Read `total`, never
  `fieldsFromIndex` — that key carries no index-health information, since
  working searches return false too (/search/JobOrder: false with
  total=50271). If this total ever goes non-zero, the route has started
  returning documents and search_notes' runtime warning stops firing on its
  own; that is the signal to reconsider which route we prefer, not a failure.
- Nested notes.action on ClientContact: non-zero on this account today. This
  syntax is UNDOCUMENTED by Bullhorn, so it is verified-working rather than
  contractually guaranteed, and the note_action parameter on the list tools is
  built on it. A zero here means the syntax has been withdrawn; the fully
  evidenced fallback is the /query/NoteEntity design in CR37.md Part 3. A
  mocked test cannot catch either shift, by definition.

Exit code 0 = all entity checks passed; 1 = at least one failed. The nested
canary counts as a check; the /search/Note total is informational either way.
Never writes anything.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from bullhorn_mcp.config import BullhornConfig  # noqa: E402
from bullhorn_mcp.auth import BullhornAuth  # noqa: E402
from bullhorn_mcp.client import BullhornClient  # noqa: E402

SEARCH_ENTITIES = [
    "ClientCorporation",
    "ClientContact",
    "Candidate",
    "JobOrder",
    "JobSubmission",
    "Placement",
]


def main() -> int:
    config = BullhornConfig.from_env()
    client = BullhornClient(BullhornAuth(config))

    session = client.auth.session  # triggers the full OAuth + REST login
    print(f"AUTH OK  rest_url={session.rest_url}")

    failures = 0

    # Lucene /search entities: broad id-range query, count=1, total comes free.
    for entity in SEARCH_ENTITIES:
        try:
            res = client.search_with_meta(entity, "id:[1 TO *]", fields="id", count=1)
            print(f"{entity:24s} OK  total={res['total']}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"{entity:24s} FAIL {str(e)[:160]}")

    # PlacementChangeRequest: /query only; showTotalMatched=true for a total.
    try:
        raw = client._request(
            "GET",
            "/query/PlacementChangeRequest",
            {"where": "id>0", "fields": "id", "count": 1, "showTotalMatched": "true"},
        )
        print(f"{'PlacementChangeRequest':24s} OK  total={raw.get('total')}")
    except Exception as e:  # noqa: BLE001
        failures += 1
        print(f"{'PlacementChangeRequest':24s} FAIL {str(e)[:160]}")

    # Note: no /query/Note; check /meta reachability.
    try:
        meta = client.get_meta("Note")
        print(f"{'Note':24s} OK  /meta fields={len(meta.get('fields', []))}")
    except Exception as e:  # noqa: BLE001
        failures += 1
        print(f"{'Note':24s} FAIL {str(e)[:160]}")

    # Canary 1: does /search/Note return documents at all? Match-all, unfiltered,
    # so the question is the route's behaviour and not the query's selectivity.
    # Informational in both directions — see the module docstring.
    try:
        raw = client._request(
            "GET",
            "/search/Note",
            {"query": "id:[0 TO 99999999]", "fields": "id", "count": "1"},
        )
        total = raw.get("total")
        note = (
            "route returns nothing on this account (expected today)"
            if not total
            else "route NOW RETURNS DOCUMENTS — this changed; revisit search_notes"
        )
        print(f"{'/search/Note match-all':24s} total={total} ({note})")
    except Exception as e:  # noqa: BLE001
        print(f"{'/search/Note match-all':24s} probe failed: {str(e)[:160]}")

    # Canary 2: is the undocumented nested association syntax still working?
    # Assert non-zero, never an exact number — the underlying data moves daily.
    try:
        res = client.search_with_meta(
            "ClientContact", 'notes.action:"BD Call"', fields="id", count=1
        )
        total = res["total"]
        if total:
            print(f"{'nested notes.action':24s} OK  total={total} (>0 as expected)")
        else:
            failures += 1
            print(
                f"{'nested notes.action':24s} FAIL total=0 — the nested syntax no "
                "longer filters; note_action is affected. Fallback: CR37.md Part 3"
            )
    except Exception as e:  # noqa: BLE001
        failures += 1
        print(f"{'nested notes.action':24s} FAIL {str(e)[:160]}")

    print("SMOKE FAIL" if failures else "SMOKE PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
