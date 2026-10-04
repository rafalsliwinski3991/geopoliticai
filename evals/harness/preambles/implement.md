This is a non-interactive CI run of a harness evaluation. No human is watching.

- Never ask a question and never wait for an answer. Wherever the command says to ask, to stop for
  approval, or to offer a choice, take the recommended or default option and continue. Do not ask
  in text either: answer the question yourself and keep going.
- The base branch is the current branch, `eval-base`. Unit 01 is already merged into it. There is
  no git remote: skip `git fetch`, `gh`, and every staleness check that needs a remote.
- Answer the checkpoint yourself: start from Unit 02; pull requests: none; the operator checklist is
  done except for Postgres and Docker, which are not available.
- Implement Unit 02 only. When Unit 02 is complete and its audit has passed, stop: do not start
  Unit 03, do not run the final branch review, and do not open pull requests.
- Skip every gate that needs Postgres, Docker, or a network service (for example
  `make test-integration`) and record it as skipped. Run every other gate.
- Do not push.
