---
description: Create one pull request or a linked gh-stack chain from the current branch's linear commits, with reviewable descriptions
agent: build
model: opencode-go/glm-5.3-flash
---

# Create stacked pull requests

Create a GitHub stacked pull-request chain, or one pull request, from the current branch's committed work.
Use the optional arguments as `[base-branch] [stack-slug]`: `$1` is the base
branch and `$2` is the stack slug when provided. If omitted, use the repository
default branch and derive a slug from the current branch.

## Preconditions

1. Confirm the repository, current branch, and clean working tree. Uncommitted
   changes are not included automatically; stop and ask the user to commit or stash
   them first.
2. Confirm `gh auth status` succeeds and `gh stack --help` is available. If the
   extension is missing, stop and report that the user can install it with
   `gh extension install github/gh-stack`; do not install it automatically. For one PR,
   the gh-stack extension is not needed.
3. Resolve the base branch and verify it is an ancestor of the current branch:
   `git merge-base --is-ancestor <base> HEAD`.
4. Require a linear stack. If `git rev-list --merges <base>..HEAD` returns
   anything, stop rather than flattening or rewriting history. Require at least
   one commit in `<base>..HEAD`.
5. Show the ordered commit list with `git log --reverse --format='%H %s'
   <base>..HEAD`. Treat each commit as one reviewable stack layer and ask the
   user to confirm the proposed order and slug before creating branches.
   In the same question, ask for the shape: **a stack** (one PR per commit) or **one PR** for the whole
   branch, which suits small or simple work. Also ask for the plan path or `rs-implement-plan` ledger this
   work came from, if any, and for each PR's sources (Asana tasks, GitHub issues, Aikido issues), if any.
   For one PR, skip "Build the local stack" below.

## Build the local stack

For each commit from oldest to newest, create a cumulative branch pointer named
`<stack-slug>/<ordinal>-<short-slug>` where the ordinal is zero-padded and the
short slug is derived from the commit subject using lowercase letters, numbers,
 and hyphens. Do not rename or delete the current branch.

- Before `gh stack init`, ensure every proposed branch is local at its expected
   SHA. Check any local ref and the push remote (normally `origin`) with
   `git rev-parse refs/heads/<branch>` and `git ls-remote --exit-code <remote>
   refs/heads/<branch>`. If either existing ref differs, stop; never force-update
   an existing branch.
- If only the remote branch exists at the expected SHA, materialize it locally
   with `git fetch <remote> refs/heads/<branch>:refs/heads/<branch>`, then verify
   the local SHA. If neither ref exists, create the local branch at the expected
   cumulative commit with `git branch <branch> <expected-sha>`.
- The first stack branch points at the first commit and each later branch points at
  the next cumulative commit. The branches must be listed bottom-to-top.

Adopt the branches without modifying their commits:

```text
gh stack init --base <base> <bottom-branch> <next-branch> ... <top-branch>
gh stack view
```

Inspect the view and verify every branch has the intended parent. If the stack is
wrong, stop and report it; do not submit it.

## Submit

Before the command that pushes branches or creates/updates PRs, ask exactly one
confirmation question:

- **Create drafts**: for a stack, `gh stack submit --auto`. For one PR, `git push -u origin <current-branch>`
  after the same remote-ref check as above, then `gh pr create --base <base> --head <current-branch> --draft --title "<subject>" --body-file <file>`.
- **Create ready for review**: the same, with `gh stack submit --auto --open`, or without `--draft`.
- **Cancel**: leave all local branches and PRs untouched.

For one PR, the title is the plan's title when there is a plan, and otherwise the subject of the first
commit. If a PR already heads the branch, reuse it instead of creating one.

The submit command is the only external delivery action in this workflow. After it
succeeds, show the created or updated PR URLs and the final `gh stack view` output.
Do not merge PRs, force-push, delete the original branch, or rewrite commits.

## Descriptions

Load the `writing-for-people` skill. Write each PR's description to a file in the scratchpad and apply it
with `gh pr edit <number> --body-file <file>`. Never invent a section's content.

- **With a plan or ledger:** use the headings and rules of the description template in `rs-implement-plan`'s
  pull-request step (the block that starts `## What this PR does`). Map each commit, or the whole branch, to
  the plan unit it delivers, and take every section from the plan, the ledger, and the diff.
- **Without one:** use only these headings:
  - `## What this PR does`: two to four plain sentences from the diff and commit messages;
  - `## How to review it`: one line per file, riskiest first, tests last;
  - `## Source`: only when the user named sources, in the template's line forms.

End each body with the pull-request attribution line the harness supplies, if it supplies one. Show every
PR URL after its body is set.

## Reruns and failures

A rerun must reuse branches that still point at the expected commits and let
`gh stack submit` update the existing stack. If branch pointers, the base branch,
or existing PR bases do not match the proposed chain, stop and ask the user rather
than repairing them silently.
