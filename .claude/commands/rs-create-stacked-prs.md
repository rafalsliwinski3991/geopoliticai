---
description: Create linked stacked pull requests from the current branch's linear commits using GitHub's gh-stack workflow
argument-hint: "[base-branch] [stack-slug]"
allowed-tools: Read, Glob, Grep, Bash, AskUserQuestion
---

# Create stacked pull requests

Create a GitHub stacked pull-request chain from the current branch's committed work.
Use the optional arguments as `[base-branch] [stack-slug]`. If omitted, use the
repository default branch and derive a slug from the current branch.

## Preconditions

1. Confirm the repository, current branch, and clean working tree. Uncommitted
   changes are not included automatically; stop and ask the user to commit or stash
   them first.
2. Confirm `gh auth status` succeeds and `gh stack --help` is available. If the
   extension is missing, stop and report that the user can install it with
   `gh extension install github/gh-stack`; do not install it automatically.
3. Resolve the base branch and verify it is an ancestor of the current branch:
   `git merge-base --is-ancestor <base> HEAD`.
4. Require a linear stack. If `git rev-list --merges <base>..HEAD` returns
   anything, stop rather than flattening or rewriting history. Require at least
   one commit in `<base>..HEAD`.
5. Show the ordered commit list with `git log --reverse --format='%H %s'
   <base>..HEAD`. Treat each commit as one reviewable stack layer and ask the
   user to confirm the proposed order and slug before creating branches.

## Build the local stack

For each commit from oldest to newest, create a cumulative branch pointer named
`<stack-slug>/<ordinal>-<short-slug>` where the ordinal is zero-padded and the
short slug is derived from the commit subject using lowercase letters, numbers,
 and hyphens. Do not rename or delete the current branch.

- If a local or remote branch with the proposed name already exists at the expected
  commit, reuse it.
- If it exists at another commit, stop. Never force-update an existing branch.
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

- **Create draft stacked PRs**: run `gh stack submit --auto`.
- **Create ready-for-review stacked PRs**: run `gh stack submit --auto --open`.
- **Cancel**: leave all local branches and PRs untouched.

The submit command is the only external delivery action in this workflow. After it
succeeds, show the created or updated PR URLs and the final `gh stack view` output.
Do not merge PRs, force-push, delete the original branch, or rewrite commits.

## Reruns and failures

A rerun must reuse branches that still point at the expected commits and let
`gh stack submit` update the existing stack. If branch pointers, the base branch,
or existing PR bases do not match the proposed chain, stop and ask the user rather
than repairing them silently.
