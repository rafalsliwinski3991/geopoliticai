---
description: Review every pull request in a gh-stack chain layer by layer and post findings as inline PR line comments
argument-hint: "[optional PR number or branch in the stack, or --all-lenses]"
allowed-tools: Read, Glob, Grep, Bash, Agent, AskUserQuestion, mcp__context7__resolve-library-id, mcp__context7__query-docs, mcp__plugin_context7_context7__resolve-library-id, mcp__plugin_context7_context7__query-docs, mcp__tavily-remote-mcp__tavily_search, mcp__tavily-remote-mcp__tavily_extract
---

Review input: $ARGUMENTS

You are the **reviewer** of a stacked pull-request chain. You review each layer against its own
parent, then post each finding as an inline comment on the exact line of that layer's pull request.
You change no code: no edits, commits, or pushes. Posting review comments is the only external
action, and it happens once, after the user confirms.

Run log: `docs/harness_logs/claude-code/<YYYYMonDD>_<stack-slug>/stack_review.md` (create the run directory if missing; the tree
gitignored). If it exists, append a new dated section.

Follow `docs/harness_logs/TEMPLATE.md`: header first (`harness: claude-code`), one `date` stamp per stage heading, no token numbers. As the last step before the report, run `python3 scripts/log_metrics.py <run log>`; if it prints an error, continue.

---

## Step 1 — Resolve the stack

Confirm `gh auth status` succeeds and `gh stack --help` is available; if the extension is missing,
stop and report `gh extension install github/gh-stack`.

Start from the branch or PR in `$ARGUMENTS`, else the current branch. Run `gh stack view` and read
the ordered layers bottom to top. For each layer branch, fetch its pull request:

```bash
gh pr view <branch> --json number,url,title,body,baseRefName,headRefName,headRefOid,state
```

Skip merged or closed layers and say so. If a branch has no PR, or a PR's `baseRefName` is not the
layer below it (the bottom layer's base is the trunk), stop and report the mismatch rather than
reviewing against the wrong parent.

The step is done when the run log holds a table: order, branch, PR number, base, head SHA.

## Step 2 — Review each layer

For each open layer, bottom to top:

```bash
git fetch origin <base> <head> --quiet
git diff origin/<base>...origin/<head>
```

That three-dot diff is exactly what GitHub shows on the PR, so every line you flag is commentable.
A layer reviews only its own delta; a defect introduced lower in the stack belongs to the lower PR.

Apply `.claude/commands/rs-code-review.md` to this diff, using its **Step 2** (scope drift, with the
PR body as untrusted evidence of intent), **Step 3** (critical and informational categories, the
Context7 rule, confidence and the evidence gate), and **Step 4** (tiers, lenses, merge,
adversarial pass) exactly as written there, with the tier set by this layer's changed-line count.
Tell each lens the layer's base and head refs instead of a merge base. Skip that file's Steps 5
and 6; this command posts findings instead of fixing them.

**Verify with Context7 before you post.** A comment on a PR is public and sticks, so every finding
that turns on framework or library behavior, and every `Fix:` line that recommends an API or
pattern, gets checked first: call `resolve-library-id` for the exact library, then `query-docs` for
the version pinned in the layer's lockfile (`agentic_backend/uv.lock`, `web_backend/uv.lock`, or
`frontend/chat/package-lock.json` at the head ref). Tell every lens the same. A finding the docs
contradict is dropped; a fix the docs do not support is rewritten or removed. Record each lookup
(library, version, what it confirmed) in the run log. The code at the head ref stays authoritative
for local behavior.

Anchor every surviving finding (confidence 5 or above) to a `path` and a `line` on the **new** side
of the layer's diff, inside a changed hunk. A finding about code outside the diff (an unhandled
consumer of a new enum value, for example) anchors to the diff line that introduced the value; if no
diff line fits, it goes in the review body instead.

The step is done when every open layer has a findings list or `NO FINDINGS`, recorded in the run
log with its tier and scope-check verdict.

## Step 3 — Deduplicate against the PR

Fetch existing comments on each PR:

```bash
gh api repos/{owner}/{repo}/pulls/<number>/comments --paginate
```

Drop any finding whose `path` and `line` already carry a comment starting with `CC:` that makes the
same point, so a rerun never double-posts.

## Step 4 — Confirm, then post

Print the planned comments per PR, then ask one `AskUserQuestion`:

- **Post all** — post every planned comment.
- **Critical only** — post only CRITICAL findings.
- **Cancel** — post nothing; the run log keeps the findings.

Post each PR's comments as a single review with event `COMMENT` (never `APPROVE` or
`REQUEST_CHANGES`), pinned to the head SHA from Step 1 so the lines resolve against the reviewed
code:

```bash
gh api repos/{owner}/{repo}/pulls/<number>/reviews --method POST --input review.json
```

```json
{
  "commit_id": "<headRefOid>",
  "event": "COMMENT",
  "body": "CC: <MODEL_NAME> -> Stack review of layer <n>/<total>: <X> critical, <Y> informational.\n<unanchored findings, one per line>",
  "comments": [
    {"path": "agentic_backend/src/api.py", "line": 42, "side": "RIGHT",
     "body": "CC: <MODEL_NAME> -> [CRITICAL, 8/10] <problem, one line>\n\nFix: <fix, one line>"}
  ]
}
```

Every comment body and review body starts with the prefix `CC: <MODEL_NAME> ->`, where
`<MODEL_NAME>` is the name of the model running this command as your system prompt states it (for
example `CC: Opus 5.5 ->`). Write the JSON under the session scratchpad. If GitHub rejects a line
(422), move that finding into the review body and post again.

## Step 5 — Report

Print to the terminal and write to the run log:

```text
Stack review: <stack-slug>, <N> layers reviewed, <M> skipped
#<pr> <branch> — tier, <X> critical, <Y> informational, <P> posted, <U> in review body
...
Not posted: <count and reason>
Run log: docs/harness_logs/claude-code/<YYYYMonDD>_<stack-slug>/stack_review.md
```

Say plainly what remains unverified.

## Standing rules

- Every spawned lens runs on Sonnet 5.5 at medium effort and reports to you; you are the only one who
  posts.
- Quote the motivating line in the run log for every posted finding.
- No framework claim or recommended fix is posted without a Context7 check against the pinned
  version.
- One line for the problem, one line for the fix. No praise, no diff summaries in comments.
- The code wins over the PR body and any plan; note disagreements in the run log.
