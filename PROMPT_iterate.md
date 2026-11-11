0a. Study @AGENTS.md. **STRICTLY FOLLOW THE INSTRUCTIONS IN AGENTS.MD**

## Your job

Review the HEAD commit, then run a fix-review loop until no CRITICAL or MODERATE
issues (and no owner-approved MINOR issues) remain, then push to GitHub.

## Spawning the reviewer

Every review, including the first, is done by a fresh subagent (general-purpose),
never by you. Set the subagent's model explicitly:

- Step 0 (first review): `fable` (Fable 5.2).
- Step 4 re-reviews for cycles 2 and 3: `opus` (Opus 5.5).
- Step 4 re-reviews for cycle 4 onwards: `fable` (Fable 5.2). Reaching cycle 4
  usually means a design problem, so use the stronger reviewer.

Count Step 0 as cycle 1.

Its prompt must contain only:

- the instruction to follow `.claude/commands/review.md` exactly,
- the short hash of the commit under review, and that it is the HEAD commit,
- the instruction to write fresh findings to `reviews/latest.md`, overwriting
  the previous review.

Do not pass it earlier findings, owner decisions, your reasoning, or any summary
of fixes. It must read the diff and the repo itself. Wait for it to finish, then
confirm `reviews/latest.md` was rewritten for the commit hash you gave it.

## Step 0: First review and owner checkpoint

1. Spawn the reviewer for the HEAD commit (see above). Never reuse an existing
   `reviews/latest.md`; it may be stale.
2. Show the owner every finding (CRITICAL, MODERATE and MINOR) with its ID and
   one-line title, then STOP and ask:
   - which MINOR issues to fix: all, a listed subset, or none (default: none),
   - whether any finding should be dismissed as a non-issue.
3. Record the decisions and apply them for the rest of this run:
   - "All minors" also covers MINOR issues raised by later review cycles. A
     listed subset covers only those findings.
   - A dismissed finding is never fixed, and is ignored if a later cycle
     raises it again.

This is the only pause. From here the loop runs without asking.

## Loop

### Step 1: Check the verdict

Read `reviews/latest.md`, ignoring dismissed findings.

- If no CRITICALs or MODERATEs remain, and no MINOR issues the owner asked to
  fix remain, go to Step 5 (push).
- Otherwise continue to Step 2.

### Step 2: Fix the findings

Address CRITICALs first (C1, C2, ...), then MODERATEs (M1, M2, ...), then the
owner-approved MINORs (m1, m2, ...).

For each finding:

1. Locate the file and line/function referenced.
2. If the finding references a known failure pattern (e.g. "matches pattern #1:
   title vs occupation"), read the corresponding CRx.md file before fixing.
3. Implement the minimal fix. Do not refactor. Do not touch unrelated code.
4. Run the relevant unit tests to confirm the fix.

After all findings are addressed, run the full test suite:

```bash
.venv/bin/pytest
```

All tests must pass. If a test fails and relates to a finding you just fixed,
resolve it. If unrelated, document it in @IMPLEMENTATION-PLAN.md using a
subagent and continue.

### Step 3: Commit locally

```bash
git add -A
git commit -m "review: fix C1 <title>, M1 <title>, m1 <title>, ..."
```

List every finding addressed. **Do not push yet.**

### Step 4: Re-review

Spawn the reviewer for the new HEAD commit (see "Spawning the reviewer"). Do
not review your own fixes.

Then return to Step 1.

### Step 5: Push

No CRITICALs, MODERATEs or owner-approved MINORs remain. The code is clear to push.

1. Update @IMPLEMENTATION-PLAN.md with any learnings from the review cycles,
   including the owner's Step 0 decisions (minors fixed, findings dismissed),
   using a subagent.
2. Push to GitHub:
   ```bash
   git push
   ```
3. Create a version tag. Check existing tags with `git tag` and increment the
   patch version (e.g. if latest is v0.0.14, tag v0.0.15):
   ```bash
   git tag v0.0.15
   git push --tags
   ```

## Constraints

1. Do not address MINOR issues unless the owner asked for them in Step 0. The
   rest are logged for awareness only.
2. Do not touch any code, test, or file not directly related to a finding you
   are fixing.
3. Do not proceed to the next sprint. Your job ends after the push.
4. **Safety valve:** If five review cycles (counting Step 0 as the first) have
   run and findings you must fix still remain, STOP. Do not push. Document the
   remaining issues in @IMPLEMENTATION-PLAN.md and alert the human. Something
   structural is wrong and needs manual intervention.
