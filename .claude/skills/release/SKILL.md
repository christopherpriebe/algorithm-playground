---
name: release
description: Cut a release from dev. Bumps the version on dev, runs the full gate, commits, fast-forwards master to dev, and tags master, then pushes so the release workflow publishes to PyPI. User-invoked only.
argument-hint: major | minor | patch
disable-model-invocation: true
---

Release bump: $ARGUMENTS

Branch model: `master` holds releases only, `dev` accumulates squash-merged
feature PRs, and a release is `dev` fast-forwarded into `master` plus a tag.

1. Preconditions; stop if any fails. `$ARGUMENTS` is `major`, `minor`, or
   `patch`. The tree is clean. The current branch is `dev`. If a remote
   exists, `git fetch` succeeds and `dev` is not behind `origin/dev`.
   `git log dev..master` is empty: `master` has nothing `dev` lacks. Otherwise
   the user merges `master` into `dev` first.
2. Bump: `uv run nox -s bump -- $ARGUMENTS`. Show the diff and
   the new version from `uv version --short`.
3. Gate after the bump: `uv run nox`. Nothing is released from a failing
   tree, and the version test must see the new version.
4. Commit on `dev`: `git commit -am "chore(release): v$(uv version --short)"`.
5. Fast-forward `master` and tag it. The tag is annotated so `--follow-tags`
   pushes it:

       git switch master
       git merge --ff-only dev
       git tag -a "v$(uv version --short)" -m "v$(uv version --short)"
       git switch dev

6. Confirm with the user, then `git push origin dev master --follow-tags`. The
   tag runs `.github/workflows/release.yml`, which checks that the tag is on
   `master` and matches the project version, then publishes with trusted
   publishing.
