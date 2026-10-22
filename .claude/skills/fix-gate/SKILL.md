---
name: fix-gate
description: Run the fast checks (ruff format, ruff check, ty) and fix exactly what they report, mechanically, without changing behavior. Use when the Stop gate or pre-commit fails, or after a large edit.
model: sonnet
effort: low
context: fork
---

Run in order and fix what each reports before moving on:

    uv run ruff format .
    uv run ruff check . --fix
    uv run ruff check .
    uv run ty check

- Fix the code, not the rule. A `# noqa` or `# ty: ignore[...]` is allowed
  only with a reason on the same line, and every one goes in your report.
- Don't change behavior. If a finding can only be resolved by changing what
  the code does, stop and report it.
- Don't touch `tests/` to silence an error in `src/`.

Report the final state of each command and every suppression added.
