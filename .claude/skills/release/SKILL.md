---
name: release
description: Cut a release. Bumps the version, runs the full gate, commits, tags, and pushes the tag so the release workflow publishes to PyPI. User-invoked only.
argument-hint: major | minor | patch
disable-model-invocation: true
---

Release bump: $ARGUMENTS

1. Preconditions: `git status` is clean, the current branch is the default
   branch, and `$ARGUMENTS` is one of `major`, `minor`, `patch`. Stop
   otherwise.
2. Bump: `uv run nox -s bump -- $ARGUMENTS`. Show the diff and
   the new version from `uv version --short`.
3. Gate after the bump: `uv run nox`. Nothing is released from a failing
   tree, and the version test must see the new version.
4. Commit and tag. The tag is annotated so `--follow-tags` pushes it:

       git commit -am "chore(release): v$(uv version --short)"
       git tag -a "v$(uv version --short)" -m "v$(uv version --short)"

5. Confirm with the user, then `git push --follow-tags`. The tag runs
   `.github/workflows/release.yml`, which checks that the tag matches the
   project version and publishes with trusted publishing.
