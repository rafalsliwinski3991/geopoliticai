This is a non-interactive CI run of a harness evaluation. No human is watching.

- Never ask a question and never wait for an answer. Wherever the command says to ask, to stop for
  approval, or to offer a choice, take the recommended or default option and continue. Do not ask
  in text either: answer the question yourself and keep going.
- The base branch is the current branch, `eval-base`. There is no git remote: skip `git fetch`,
  `gh`, and every staleness check that needs a remote.
- Answer the checkpoint yourself: start from Unit 01; pull requests: none. The operator checklist is
  done. The root `.env` already holds the API keys the plan's smoke gates need, and a `DATABASE_URL`
  for the Postgres at `127.0.0.1:55432` that `make migrate-web`, `make migrate-agentic`, the
  integration tests, and `make test-web-backend` use. Never open, print, or copy `.env`; the app
  loads it.
- Implement every unit, in order, then run the final review and record `PRs: none`. Stop there.
- Run every gate, including smoke gates and manual steps that need only Python, the keys, and
  Postgres. Skip only a step that needs Docker (`make services`, `docker compose`), a browser or the
  chat UI, Phoenix or Arize, or a human operator, and record each skip in the ledger with its
  reason.
- A live step (a smoke gate or a live eval run) depends on outside services that may have changed
  since the plan was written. When one fails, record its output in the ledger, make at most one fix
  attempt the plan's "act on the results" list allows, then record the outcome and continue to the
  next unit. A failing live step never stops the run and never blocks a unit's commit; `make test`
  and `make lint` still must pass before every commit.
- Do not push.
