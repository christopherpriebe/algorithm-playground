---
name: feature
description: Build a planned change test-first. This session writes the failing tests, the implementer agent (sonnet) makes them pass, the reviewer agent (opus) audits, and the full gate runs before done. Use after /plan or for any change that needs tests.
argument-hint: <description of the change, or "the plan above">
---

Feature: $ARGUMENTS

You hold the judgment: the plan, the tests, the briefs, the review
decisions. Implementation is delegated.

1. Plan. If a plan was agreed earlier in this conversation, use it.
   Otherwise produce the same sections as `/plan` inline and confirm open
   questions with the user before continuing.
2. Tests, written by you. Turn every behavior into a test under `tests/`
   following `.claude/rules/tests.md`. Run `uv run pytest <file> -n0` and
   confirm each test fails for the expected reason (an assertion or the
   documented exception, not an import error). Then re-read them as a
   skeptic: a test that asserts nothing, restates a mock, or mirrors an
   implementation is rewritten now. Stage them with `git add tests/` so the
   reviewer's diff includes them.
3. Implement, delegated. Spawn `implementer` with the Interface section, the
   failing test file, and the instruction to make exactly those tests pass
   without touching `tests/` (the role guard enforces this). If it returns
   a "Blocked" section, resolve it
   with the user; a disputed test is never settled by the implementer.
   On return run `uv run nox -s lint typecheck tests-3.11`.
4. Review, delegated. Spawn `reviewer` on the diff. Fix blockers and majors
   through `implementer`; note minors. One more review after any blocker.
5. Gate. `uv run nox`, every default session including coverage. Summarize:
   what was built, what the tests cover, what the reviewer flagged, what is
   left open.

Never weaken a test to get green. Never add a dependency without saying so.
Commit only if asked. If a step fails twice, stop and report instead of
looping.
