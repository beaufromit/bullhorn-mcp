0a. Study @AGENTS.md. **STRICTLY FOLLOW THE INSTRUCTIONS IN AGENTS.MD**
0b. Read `reviews/latest.md` in full. This is your source of work items.

## Your job

Run a fix-review loop until no CRITICAL or MODERATE issues remain, then push to GitHub.

## Loop

### Step 1: Check the verdict

Read the `## Verdict` section of `reviews/latest.md`.

- If it says "NO CRITICAL ISSUES" and the MODERATE section says "None." — go to Step 5 (push).
- If CRITICALs or MODERATEs exist — continue to Step 2.

### Step 2: Fix all CRITICALs and MODERATEs

Address CRITICALs first (C1, C2, ...), then MODERATEs (M1, M2, ...).

For each finding:

1. Locate the file and line/function referenced.
2. If the finding references a known failure pattern (e.g. "matches pattern #1:
   title vs occupation"), read the corresponding CRx.md file before fixing.
3. Implement the minimal fix. Do not refactor. Do not touch unrelated code.
4. Run the relevant unit tests to confirm the fix.

After all CRITICALs and MODERATEs are addressed, run the full test suite:

```bash
.venv/bin/pytest
```

All tests must pass. If a test fails and relates to a finding you just fixed,
resolve it. If unrelated, document it in @IMPLEMENTATION-PLAN.md using a
subagent and continue.

### Step 3: Commit locally

```bash
git add -A
git commit -m "review: fix C1 <title>, M1 <title>, ..."
```

List every CRITICAL and MODERATE addressed. **Do not push yet.**

### Step 4: Run the review

Act as the adversarial critic. Follow the exact instructions in
`.claude/commands/review.md` — read the new diff, evaluate against all known
failure patterns, and write fresh findings to `reviews/latest.md`, overwriting
the previous review.

Then return to Step 1.

### Step 5: Push

No CRITICALs or MODERATEs remain. The code is clear to push.

1. Update @IMPLEMENTATION-PLAN.md with any learnings from the review cycle,
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

1. Do not address MINOR issues. They are logged for awareness only.
2. Do not touch any code, test, or file not directly related to a CRITICAL or
   MODERATE finding.
3. Do not proceed to the next sprint. Your job ends after the push.
4. **Safety valve:** If you complete Step 4 five times (five consecutive review
   cycles) and CRITICALs or MODERATEs still remain, STOP. Do not push. Document
   the remaining issues in @IMPLEMENTATION-PLAN.md and alert the human. Something
   structural is wrong and needs manual intervention.
