---
name: marathon
description: Execute a long, multi-step plan over hours with a committed checkpoint per step, pausing cleanly when the 5-hour or weekly usage window nears its limit and resuming after it resets. Keeps a run ledger under .claude/runs/. Use for work the user expects to take many hours, or to resume such a run.
argument-hint: <run name> | resume <run name>
---

Marathon: $ARGUMENTS

A marathon is a plan executed step by step where every step ends in a
committed checkpoint, so the run can stop at any boundary and continue later
in this session or another. Three parts of the harness carry it:

- `.claude/usage.json`, written by the status line after every assistant
  message, holds the 5-hour and weekly usage windows.
- The usage guard (a PreToolUse hook) warns at the warn threshold and, at
  the stop threshold, allows only checkpoint actions.
- The marathon driver (a Stop hook) sends you back to the next step if you
  stop while the ledger is `active` with steps left.

## Starting

0. Branch: a marathon runs on `dev-<slug>`, cut from an up-to-date `dev`
   (`git switch dev`, `git pull --ff-only` when a remote exists,
   `git switch -c dev-<slug>`). Never on `dev` or `master`.
1. The plan comes from the conversation: `/plan` output or the user's own
   list. Cut it into steps that each take well under an hour and end with
   `uv run nox` green. Keep it under 20 steps; split the run otherwise.
2. Write the ledger at `.claude/runs/<slug>.md` (gitignored) in the format
   below, with `status: active`.
3. Tell the user the steps, that each step gets its own commit, and how
   pausing works. Then start.

## Executing

Repeat until every step is checked:

1. Read `.claude/usage.json`. If any window whose `resets_at` is still in
   the future is at or past the warn threshold (80% unless
   `CLAUDE_USAGE_WARN_PERCENT` says otherwise), go to Pausing instead of
   starting a step.
2. Do the next unchecked step. Use `/feature` for anything that needs
   tests; delegate per the model table in `CLAUDE.md`.
3. Run `uv run nox`. Commit under the user's identity with the
   Conventional Commits type that fits the step (`feat`, `fix`, `refactor`,
   `test`, `docs`, `chore`) and the scope `<slug>`. Mark the step `[x]` with
   the short commit hash and rewrite `## Next`.
4. Don't end the turn between steps.

## Pausing

When the guard warns or denies, or the user asks to stop:

1. Finish only what keeps the tree green; never start a new step.
2. Commit. In the ledger set `status: paused` and `resume_after:` to the
   window's `resets_at` as a local time.
3. If the `CronCreate` tool is available, schedule a one-shot prompt for a
   few minutes after the reset, on a minute that is not :00 or :30:
   `Resume marathon <slug>`. It fires only while this session stays open
   and idle.
4. Tell the user: paused after step N of M, which window, when it resets,
   that the session resumes itself if left open, and that otherwise
   `claude --resume` followed by "resume marathon <slug>" continues it.
5. End the turn.

## Resuming

On "resume marathon <slug>", from the scheduled prompt or the user:

1. Read the ledger, then `git status` and `git log --oneline -5`. The tree
   must be clean and the last checkpoint commit present; otherwise report
   the mismatch and stop.
2. Read `.claude/usage.json`. If a counting window is still at or past the
   warn threshold, go to Pausing and reschedule.
3. Set `status: active` and continue Executing.

## Finishing

Set `status: done`. Summarize what landed, with commit hashes, and anything
skipped or left open. Offer to open a pull request against `dev`
(`gh pr create --base dev`), to be squash-merged; don't open it without a
yes.

## Ledger format

    ---
    run: <slug>
    status: active
    started: 2026-10-21 13:05
    resume_after:
    ---
    # <title>

    Checkpoint rule: every step ends with `uv run nox` green and a commit.

    ## Steps
    1. [ ] <step>
    2. [ ] <step>

    ## Next
    Step 1: <the concrete first action>

    ## Log
    - 13:05 started
