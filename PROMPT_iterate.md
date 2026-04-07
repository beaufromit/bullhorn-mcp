0a. Study @AGENTS.md. **STRICTLY FOLLOW THE INSTRUCTIONS IN AGENTS.MD**
0b. Read `reviews/latest.md` in full. This is your source of work items.

## Your job

Run a fix-review loop until no CRITICAL issues remain, then push to GitHub.

## Loop

### Step 1: Check the verdict

Read the `## Verdict` section of `reviews/latest.md`.

- If it says "NO CRITICAL ISSUES" — go to Step 5 (push).
- If CRITICALs exist — continue to Step 2.

### Step 2: Fix all CRITICALs

For each CRITICAL finding (C1, C2, ...) in `reviews/latest.md`:

1. Locate the file and line/function referenced.
2. If the finding references a known failure pattern (e.g. "matches pattern #1:
   title vs occupation"), read the corresponding CRx.md file before fixing.
3. Implement the minimal fix. Do not refactor. Do not touch unrelated code.
4. Run the relevant unit tests to confirm the fix.

After all CRITICALs are addressed, run the full test suite:

```bash
.venv/bin/pytest
```

All tests must pass. If a test fails and relates to a CRITICAL you just fixed,
resolve it. If unrelated, document it in @IMPLEMENTATION-PLAN.md using a
subagent and continue.

### Step 3: Commit locally

```bash
git add -A
git commit -m "review: fix C1 <title>, C2 <title>, ..."
```

List every CRITICAL addressed. **Do not push yet.**

### Step 4: Run the review

Act as the adversarial critic. Follow the exact instructions in
`.claude/commands/review.md` — read the new diff, evaluate against all known
failure patterns, and write fresh findings to `reviews/latest.md`, overwriting
the previous review.

Then return to Step 1.

### Step 5: Push

The review verdict says "NO CRITICAL ISSUES". The code is clear to push.

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

1. Do not address MODERATE or MINOR issues. They are logged for awareness only.
   If you believe a MODERATE is actually a CRITICAL, document your reasoning in
   the commit message but fix it anyway.
2. Do not touch any code, test, or file not directly related to a CRITICAL finding.
3. Do not proceed to the next sprint. Your job ends after the push.
4. **Safety valve:** If you complete Step 4 five times (five consecutive review
   cycles) and CRITICALs still remain, STOP. Do not push. Document the remaining
   issues in @IMPLEMENTATION-PLAN.md and alert the human. Something structural
   is wrong and needs manual intervention.
