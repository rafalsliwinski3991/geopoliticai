---
description: Critically review the current implementation plan
---

Use the `critic` subagent to review the proposed implementation plan before any
code is changed.

Ask it to challenge:

- assumptions
- architecture
- state transitions
- failure scenarios
- backward compatibility
- security
- concurrency
- complexity
- missing tests

Return BLOCKING, IMPORTANT, and SUGGESTION findings.

After receiving the critique, summarize which recommendations should actually
be incorporated and why.
