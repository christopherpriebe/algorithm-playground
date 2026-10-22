---
paths:
  - "**/*.py"
  - "**/*.pyi"
---

# Python conventions

ruff (the rule set in `pyproject.toml`), ty (every rule an error), and the
formatter own the mechanical rules. This file lists only what differs from
common defaults. When a rule here conflicts with a tool, the tool wins; say
so instead of working around it.

- Suppressions: `# ty: ignore[rule]` with a reason on the same line; the
  configuration does not honor `# type: ignore`. For ruff, `# noqa: RULE`
  with a reason. Both go in your summary.
- Public API: implementation lives in underscore-prefixed modules; names are
  re-exported from `__init__.py` and listed in `__all__`.
- Naming: functions are verb phrases; predicates start with `is_`, `has_`,
  or `can_`; spell words out (`configuration`, not `cfg`) except universal
  abbreviations (`id`, `url`, `io`).
- Value objects are `@dataclass(frozen=True, slots=True)`. Reach for
  `Protocol` before an abstract base class when only structure matters.
- Errors: one package base exception; specific exceptions derive from it.
  Build the message in a variable before `raise` (`EM`); re-raise inside
  `except` with `from err` (`B904`).
- Docstrings: Google style, imperative summary ("Parse a file."), behavior
  only; pydoclint checks the sections. None on dunder methods.
- Syntax targets the minimum Python (3.11); pyupgrade rewrites
  the rest. `X | None`, builtin generics, `collections.abc`.
- Never `print` in library code (`T20`), never `assert` for validation in
  `src/`, always `pathlib`, always timezone-aware datetimes (`DTZ`).
