---
name: rs-create-stacked-prs
description: Create linked stacked pull requests from the current branch's linear commits using GitHub's gh-stack workflow. Use when explicitly invoked with `$rs-create-stacked-prs`.
---

# Create stacked pull requests

Create a GitHub stacked pull-request chain from the current branch's committed work.
The optional arguments are `[base-branch] [stack-slug]`; otherwise use the repository
default branch and derive a slug from the current branch.

1. Confirm the current repository, branch, and clean working tree. Stop for any
   uncommitted changes; do not include them automatically.
2. Confirm `gh auth status` and `gh stack --help`. If unavailable, report
   `gh extension install github/gh-stack` and stop without installing it.
3. Resolve the base branch, require it to be an ancestor of `HEAD`, require at least
   one commit in `<base>..HEAD`, and stop if `git rev-list --merges <base>..HEAD`
   finds a merge commit.
4. Show `git log --reverse --format='%H %s' <base>..HEAD` and obtain explicit user
   approval for the proposed order and stack slug before creating branches.
5. For each commit oldest-first, ensure a local cumulative branch pointer named
   `<stack-slug>/<ordinal>-<short-slug>` points at the expected commit. Check both
   the local ref and the push remote (normally `origin`); if only the remote ref
   exists at the expected commit, materialize it with
   `git fetch <remote> refs/heads/<branch>:refs/heads/<branch>` before
   `gh stack init`. If either ref differs, stop; never force-update a branch.
   If neither exists, create the local branch at the expected commit.
6. Adopt the bottom-to-top branches without modifying commits:

   ```text
   gh stack init --base <base> <bottom-branch> <next-branch> ... <top-branch>
   gh stack view
   ```

7. Inspect the view and ask once whether to create draft PRs, create ready-for-review
   PRs, or cancel. Drafts use `gh stack submit --auto`; ready PRs use
   `gh stack submit --auto --open`. This is the only step that pushes branches or
   creates or updates PRs.
8. Show resulting PR URLs and final `gh stack view`. Never merge, force-push, delete
   the original branch, or rewrite commits. On rerun, reuse matching branches and
   stop if branch pointers or PR bases no longer match the proposed chain.
