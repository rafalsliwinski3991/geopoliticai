"""Local offline evaluation harness. Never imported by application code.

This package is deliberately outside `src/`: `app/Dockerfile` copies only
`src/`, so nothing here can reach the runtime image. The import direction is
one-way — `evals` may import `models`, `config`, and `agents`; nothing under
`src/` may ever import `evals`.
"""
