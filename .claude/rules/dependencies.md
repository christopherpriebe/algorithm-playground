---
paths:
  - "pyproject.toml"
  - "uv.lock"
---

# Dependencies

- Adding a runtime dependency is a design decision: say why the standard
  library doesn't cover it, and prefer a library that is typed, maintained,
  and small.
- Python: `uv add name` for runtime, `uv add --group dev name` (or `test`,
  `docs`, `lint`, `typecheck`) for tooling. Never edit `uv.lock` by hand;
  run `uv lock` after editing `pyproject.toml` directly. Pin floors
  (`>=1.2`), not exact versions.
- Every dependency must import under the minimum supported Python
  (3.11).
