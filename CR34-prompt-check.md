# CR34 effectiveness check

Run this prompt in a Claude Code session in the local repo once CR34 is implemented.
It has two parts: Part 1 Claude runs directly against the live tenant from the repo;
Part 2 Claude gives you SSH commands for the deployment server and waits for you to
paste the output back (Claude cannot reach the server itself).

## Usage notes

- "Live tenant" means the script makes real read-only `/meta` calls, so it needs a
  working `.env`. It does not mean it must run on the server. Part 1 runs wherever you
  implemented CR34 (the local repo). Part 2 confirms the deployed server matches.
- Assumes CR34 introduced `GENERIC_DISCOVERY_TOOLS` in `descriptions.py` (the import is
  only used to confirm the constant exists; drop it if you named it differently).
- The headline result is objective A (total under ~20k versus the ~111k baseline).
  Worth recording in the commit message.

## Prompt

```
Verify that CR34 (trimming the startup tool-description enrichment in
src/bullhorn_mcp/descriptions.py) achieved its goals. Do not change any code;
this is measurement only. Read CR34.md first for the intended design and targets.

=== PART 1: local verification (you run this directly in this repo) ===

Step 1 — Measure the real, enriched descriptions.
Run the enrichment exactly as main() does, against the live tenant, and print each
tool's resulting description size. Use this script (same approach as the pre-change
baseline check):

  import asyncio, logging
  logging.basicConfig(level=logging.WARNING)
  from bullhorn_mcp import server
  from bullhorn_mcp.descriptions import enrich_tool_descriptions, GENERIC_DISCOVERY_TOOLS
  async def main():
      client = server.get_client()
      await enrich_tool_descriptions(server.mcp, client)
      tools = await server.mcp.list_tools()
      sizes = {t.name: len(t.description or "") for t in tools}
      total = sum(sizes.values())
      print("TOTAL description chars:", total, " ~tok:", total//4)
      for n in sorted(sizes, key=lambda k: -sizes[k]):
          print(f"{sizes[n]:7} ~{sizes[n]//4:6} tok  {n}")
      cand = next(t for t in tools if t.name == "list_candidates").description
      plac = next(t for t in tools if t.name == "list_placements").description
      gen  = next(t for t in tools if t.name == "update_record").description
      print("\n--- list_candidates excerpt ---\n", cand[-1500:])
      print("\n--- update_record excerpt ---\n", gen[-1500:])
      print("\n--- list_placements has customText41:", "Candidate Source" in plac)
  asyncio.run(main())

Step 2 — Judge against these targets and report PASS/FAIL for each with the actual number:

  A. Total description payload: was ~111k tok. Target: under ~20k tok.
  B. Each of the 4 generic tools (search_entities, query_entities, update_record,
     get_entity_fields): was ~13k tok each. Target: under ~1.5k tok each, and each
     must still contain real field NAMES (compact level) plus a get_entity_fields pointer.
  C. No tool description contains a full uncapped dump: assert no entity section lists
     more than ~45 fields (cap is 40 + footer).
  D. Entity tools still carry useful detail: list_candidates must include a [required]
     marker and a "Valid values:" picklist line; list_placements must include the
     configured custom field "Candidate Source - This Placement" (customText41).
  E. Configured-custom heuristic: a configured custom field (label != API name) is
     present; an unconfigured one (label == API name, e.g. a bare customText40) is absent.

Step 3 — Confirm no capability regression (local).
  - Run: .venv/bin/pytest -q  (report pass count and any failures)
  - Confirm the 4 generic tools' STATIC docstrings (in server.py) mention
    get_entity_fields, so guidance survives an enrichment fallback.

=== PART 2: server verification (you cannot reach the server; instruct me) ===

You do not have access to the deployment server. Do NOT try to SSH or run remote
commands yourself. Instead, print the exact commands below for me to run over my own
SSH session, then STOP and wait for me to paste the output back before judging Part 2.

Tell me to run, on the server, in order:

  # 1. confirm the deployed code is the CR34 commit (paste both lines back)
  cd /opt/bullhorn-mcp && git rev-parse HEAD && git status --short

  # 2. (re)create the measurement script on the server
  cat > /tmp/check_enrich.py <<'PY'
  import asyncio, logging
  logging.basicConfig(level=logging.WARNING)
  from bullhorn_mcp import server
  from bullhorn_mcp.descriptions import enrich_tool_descriptions
  async def main():
      client = server.get_client()
      await enrich_tool_descriptions(server.mcp, client)
      tools = await server.mcp.list_tools()
      sizes = {t.name: len(t.description or "") for t in tools}
      total = sum(sizes.values())
      print("TOTAL description chars:", total, " ~tok:", total//4)
      for n in sorted(sizes, key=lambda k: -sizes[k]):
          print(f"{sizes[n]:7} ~{sizes[n]//4:6} tok  {n}")
  asyncio.run(main())
  PY

  # 3. if step 4 errors with "IndentationError", run this once then retry step 4:
  .venv/bin/python -c "import textwrap,pathlib; p=pathlib.Path('/tmp/check_enrich.py'); p.write_text(textwrap.dedent(p.read_text()))"

  # 4. run it
  cd /opt/bullhorn-mcp && .venv/bin/python /tmp/check_enrich.py 2>&1 | tail -60

Then ask me to paste back:
  - the git rev-parse HEAD and git status output from step 1,
  - the full TOTAL line and per-tool size list from step 4.

When I paste it, judge:
  F. Deployed commit matches the CR34 commit and the tree is clean.
  G. Server TOTAL description tok is under ~20k (matches the local Part 1 number).
  H. The 4 generic tools on the server are each under ~1.5k tok.
If F/G/H differ from Part 1, the deployment did not pick up the change (likely needs
`git pull` + `systemctl restart bullhorn-mcp.service`); say so explicitly.

=== FINAL ===
Summarize Parts 1 and 2 as one table: objective, target, actual, PASS/FAIL, plus an
overall verdict on whether CR34 met its ~80% context-reduction goal without losing
field discovery, and whether the deployed server reflects it. Flag any regression or
any tool still unexpectedly large.
```
