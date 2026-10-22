---
paths:
  - "tests/**"
---

# Tests

- One version: `uv run nox -s tests-3.11`; all with coverage:
  `uv run nox`. Pytest arguments go after `--`; `-n0` turns off xdist for
  `--pdb`. `uv run pytest tests/test_x.py -n0 -x` is the quick loop.
- `tests/` is organized by behavior, not by module: `test_parsing.py`,
  `test_cli.py`, never a file per `_module`. Internal refactors then touch no
  test. Shared fixtures live in `tests/conftest.py`.
- Names state the behavior: `test_parse_rejects_unknown_key`. No docstrings
  needed; `assert` and literal values are allowed here (`D`, `S101`,
  `PLR2004` are off under `tests/`).
- Tests import only from `algorithm_playground`, never from a private module.
  Private helpers are covered through the public behavior that uses them. A
  helper that needs tests of its own is promoted to the public API or a
  public submodule; it is not imported from `_module`.
- `parametrize` over copies; `pytest.raises(..., match=...)` always with
  `match`; `tmp_path` and `monkeypatch` before mocks; mocks only at process
  boundaries, with `autospec=True`.
- Hypothesis for pure functions with an invariant; add it with
  `uv add --group test hypothesis`.
- Coverage fails under 90%. It is a floor, not a target.

## Rules that don't bend

- A failing test is never fixed by weakening its assertion, adding a skip or
  xfail, widening a `match`, or deleting it.
- If a test looks wrong or impossible to satisfy as written, stop and report
  it: which test, what is wrong, what you would change. In the main session,
  ask the user. In a subagent, put it under a "Blocked" heading in your
  report. Reporting is the expected path, not a failure.
