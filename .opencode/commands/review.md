---
description: Independent review of current changes
---

Use the `critic` subagent to perform an independent review of the current
working-tree changes.

Have the critic inspect:

- git diff
- modified files
- relevant surrounding implementation
- relevant tests

Focus on:

1. correctness
2. edge cases
3. state-management problems
4. concurrency
5. exception handling
6. security
7. API compatibility
8. missing tests
9. unnecessary complexity

Return BLOCKING findings first.

Do not modify files until the critic has completed the review.
