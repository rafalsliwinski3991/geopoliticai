# Stack address-feedback run log — forecast stack

Run date: 2026-10-08. Trigger: `/rs-gh-stack-address-feedback` (all layers).
Model replying: `CC: GLM 5.3 ->`.

## Step 1 — Stack table (bottom to top)

| order | branch | PR | base | head SHA | state |
|---|---|---|---|---|---|
| 1 | forecast/01-charge-a-forecast-20-units-... | #138 | main | 8b335e2b | OPEN |
| 2 | forecast/02-carry-each-fetched-page-s-own-byline | #139 | 01 | d1746856 | OPEN |
| 3 | forecast/03-add-the-forecaster-s-research-step | #140 | 02 | 0e3ba13e | OPEN |
| 4 | forecast/04-drop-media-processing-from-... | #141 | 03 | f3984730 | OPEN (0 threads) |
| 5 | forecast/05-add-the-claims-and-the-council | #142 | 04 | 124ceac7 | OPEN |
| 6 | forecast/06-wire-the-forecaster-s-fixed-graph | #143 | 05 | 009fc97f | OPEN |
| 7 | forecast/07-bound-a-hung-agent-run | #144 | 06 | cb15f254 | OPEN |
| 8 | forecast/08-replace-the-inkling-seat | #145 | 07 | 5188d6fe | OPEN (0 threads) |
| 9 | forecast/09-log-the-unread-links | #146 | 08 | 924e0dd6 | OPEN (0 threads) |
| 10 | forecast/10-log-every-failed-council-attempt | #147 | 09 | b1b50cf8 | OPEN (0 threads) |
| 11 | forecast/11-route-explicit-forecast-requests | #148 | 10 | 37f596b6 | OPEN |
| 12 | forecast/12-add-forecast-routing-rows-and-eval | #149 | 11 | 9614187b | OPEN |
| 13 | forecast/13-add-a-forecast-backtest | #150 | 12 | f741d149 | OPEN |
| 14 | forecast/14-cache-gemini-s-video-notes | #151 | 13 | a2fa2dd8 | OPEN |

Integrity: every PR bases on the layer below's head; #138 bases on `main`. All 15 open. Fetch done
(`git fetch origin --quiet`). GitHub reviewThreads pagination exhausted for all PRs
(`hasNextPage: False` everywhere).

## Step 2 — Unresolved thread inventory (all `isResolved: false`, `isOutdated: false`)

Counts: #138: 1, #139: 8, #140: 12, #141: 0, #142: 12, #143: 8, #144: 4, #145: 0, #146: 0,
#147: 0, #148: 6, #149: 8, #150: 8, #151: 8. **Total 75.**

Stored as JSON per PR in `/tmp/opencode/threads_*.json` (author, body, path, line, ids for reply
posting).

### Decision clusters raised with the user (2026-10-08)

- D1 — #139 byline questions: remove the byline feature, or keep and apply informational fixes?
- D2 — #142 state.py: move pydantic models to `models.py`, and rename `PassageRef`/`passages`?
- D3 — #144: rename `caps.py` / `run_under_cap` to human-friendly names?
- D4 — #140 config: one approach to "max" prefixes (`max_evidence` vs `max_evidences` etc.)?
- D5 — #140 config: video-notes model (`gemini-3.8-flash`) cheapness?
- D6 — #143 graph.py: checkpointer on the forecaster graph?
- D7 — #150 dataset: cut forecast-backtest cases to 2?
- D8 — #149: add an e2e eval case that launches the whole deep-forecaster agent (incl. research)?

All other threads classified mechanically (AAA tests, copilot doc/test corrections, CC
informational fixes) — decisions per user's answers; replies drafted in Step 3 below.

## Manual review

- Pull-request review bodies and issue comments were not separately enumerated beyond the review
  threads above; none of the 15 PRs shows general reviews with unresolved content distinct from
  the threads (copilot "review" items appear as threads). Re-checked if the user says otherwise.
