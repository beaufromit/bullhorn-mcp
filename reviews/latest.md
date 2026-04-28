# Review: Fix M1 inaccurate Token Lifetime Policy docs, M2 heading nesting

**Commit:** e3207ef
**Date:** 2026-04-28
**Files changed:** 2

## CRITICAL

None.

## MODERATE

None.

## MINOR

- **m1: Variable name `$ref` is ambiguous** — `README.md`, PowerShell example
  The hashtable assigned to `$ref` and then passed as `-Body $ref` has the same name as the Graph API URI segment `` `$ref `` in the preceding line. The code is correct (the backtick-escaped `$ref` in the URI string is a literal path segment, not the variable), but a reader unfamiliar with PowerShell string escaping may misread the relationship between the variable and the URI. A less ambiguous variable name (e.g. `$policyRef`) would eliminate the confusion without changing behaviour.

## Verdict

NO CRITICAL ISSUES. This diff is clear to push.
