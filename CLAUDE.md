# algorithm-playground

A learning and benchmarking sandbox for algorithms, with a language-agnostic binary executable contract. A src-layout
Python package for Python >= 3.11, managed by uv.

## Commands

Everything runs through uv. Never `pip`; never activate the venv by hand.

    uv sync  # environment and editable install
    uv run nox  # the full gate
    uv run nox -s lint typecheck tests-3.11  # fast gate
    uv run nox -s tests-3.11 -- -k name  # one Python; pytest args after --
    uv run pytest tests/test_x.py -n0 -x  # quick serial loop
    uv add name  # or: uv add --group test name; never edit uv.lock

## Definition of done

- `uv run nox` passes. For docs-only or trivial changes `uv run nox -s lint typecheck` is enough; say which ran.
- New behavior has a test that fails without it. Coverage stays at or above 90%.
- Suppressions (`# noqa`, `# ty: ignore[...]`) carry a reason on the line and appear in your summary. `# type: ignore` is never used; the checker ignores it.
- No new dependency without saying why.
- No commit or push unless asked, and never directly on `master` or `dev`. Commits use Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`; imperative subject under 72 characters; body says why) and the user's own git identity: no `Co-Authored-By` trailer, no AI attribution, never `--author`.

## Branches

`master` holds releases only. `dev` accumulates feature PRs, squash-merged.
Feature work happens on `dev-<slug>` branches cut from `dev`, and PRs target
`dev`. A release is `dev` fast-forwarded into `master` plus an annotated tag
(`/release`). Never merge `master` into anything but `dev`.

## Tests are the contract

Never weaken, skip, xfail, or delete a test to get green. If a test looks
wrong or impossible to satisfy as written, stop and report it: which test,
what is wrong, what you would change. In this session, ask the user. In a
subagent, put it under a "Blocked" heading. Reporting is the expected path.

## Models

Subagents always name a model. `/fix-gate` forks onto sonnet; `/plan` moves
this session to opus for its turn; the other skills run on this session's
model. Never use `fable` unless the user asks for it by name.

| Tier | Use for | Not for |
| --- | --- | --- |
| `opus` | planning, interface and test design, review, triage, anything ambiguous, talking to the user | mechanical edits |
| `sonnet` | implementation against a plan or failing tests, refactors with a written plan, multi-file mechanical edits, lint and type fixes | design decisions, editing tests |
| `haiku` | read-only search, extraction, summarizing files, running a command and reporting | anything that edits |

Agents in `.claude/agents/`: `scout` (haiku, read-only), `implementer`
(sonnet, never touches `tests/`), `reviewer` (opus, read-only). Brief them
with the plan, the files, and the applicable rule; require a report of what
changed, what didn't, and every decision the brief didn't cover.

## Rules and workflows

`.claude/rules/` loads per path: `python.md`, `tests.md`,
`dependencies.md`. Skills: `/plan`
(interface, behaviors to test, open questions; agreed in conversation),
`/feature` (tests by this session,
implementation by `implementer`, review by `reviewer`, full gate),
`/fix-gate`, `/release`, `/marathon`. `/feature-workflow` (the script in
`.claude/workflows/`) is the hands-off variant of `/feature`; use it
deliberately, not by default.

## Long runs

`/marathon` executes a multi-step plan over hours: a ledger under
`.claude/runs/`, a committed checkpoint per step, and a pause-and-resume
protocol tied to the subscription usage windows. The status line records the
5-hour and weekly windows to `.claude/usage.json`; before every tool call the
usage guard warns at 80% and, at 92%, allows only checkpoint actions; the
marathon driver sends you back to the next step if you stop while a run is
active. Pausing means: commit, set the ledger to paused with the reset time,
schedule a one-shot resume with CronCreate, tell the user, end the turn.

## Hooks

Every edited file is formatted. Ending a turn with uncommitted changes runs
ruff, ty, and pytest (plus `cargo check` and a rebuild when there is a
`Cargo.toml`); failures come back instead of ending the turn, except that
the same failures twice in a row let it end. A role guard denies the
implementer edits under `tests/` and limits the reviewer's shell to
inspection. The usage guard and the marathon driver are described under
Long runs.
