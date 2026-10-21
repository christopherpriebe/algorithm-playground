"""Tests for the stable module a problem author imports from."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import algorithm_playground.authoring as authoring
from algorithm_playground import core, visualization

EXPECTED_NAMES = {
    "BarHighlight",
    "BinaryFormatError",
    "Fixture",
    "Frame",
    "FrameSequence",
    "InputGenerator",
    "Problem",
    "StateTimeline",
    "VerificationResult",
    "assert_valid_problem",
    "describe_sequence",
    "distinct",
    "expect_end_of_stream",
    "read_f64",
    "read_f64_array",
    "read_i32",
    "read_i32_array",
    "read_i64",
    "read_i64_array",
    "read_record_bytes",
    "read_records",
    "read_sections",
    "read_u8",
    "read_u32",
    "read_u32_array",
    "read_u64",
    "register_problem",
    "render_bar_chart",
    "render_side_by_side_bar_charts",
    "shrink_each",
    "shrink_fields",
    "shrink_integer",
    "shrink_integer_sequence",
    "shrink_integers",
    "shrink_sequence",
    "truncate_text",
    "validate_problem",
    "write_f64",
    "write_f64_array",
    "write_i32",
    "write_i32_array",
    "write_i64",
    "write_i64_array",
    "write_u8",
    "write_u32",
    "write_u32_array",
    "write_u64",
}


class TestSurface:
    def test_it_exports_what_a_problem_author_needs(self) -> None:
        assert set(authoring.__all__) == EXPECTED_NAMES

    def test_every_exported_name_exists(self) -> None:
        assert [name for name in authoring.__all__ if not hasattr(authoring, name)] == []

    def test_the_names_are_the_ones_of_the_packages_that_implement_them(self) -> None:
        for name in authoring.__all__:
            source = core if hasattr(core, name) else visualization
            assert getattr(authoring, name) is getattr(source, name), name

    def test_it_does_not_export_engine_internals(self) -> None:
        for name in ("run_tests", "run_benchmark", "Runner", "Implementation", "get_problem"):
            assert name not in authoring.__all__

    def test_the_names_are_in_reading_order(self) -> None:
        def reading_order(name: str) -> tuple[int, list[int | str]]:
            group = 0 if name.isupper() else 1 if name[0].isupper() else 2
            return group, [
                int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)
            ]

        assert authoring.__all__ == sorted(authoring.__all__, key=reading_order)


def imported_modules(source: str) -> set[str]:
    """The ``algorithm_playground`` modules a piece of Python source imports from."""
    modules = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module.split(".")[0] == "algorithm_playground":
                modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(
                alias.name
                for alias in node.names
                if alias.name.split(".")[0] == "algorithm_playground"
            )
    return modules


class TestAuthorsImportOnlyFromIt:
    def test_the_distinct_count_example(self, repository_root: Path) -> None:
        path = repository_root / "examples" / "distinct_count" / "distinct_count_problem.py"
        assert imported_modules(path.read_text()) == {"algorithm_playground.authoring"}

    @pytest.mark.parametrize("page", ["writing-a-problem.rst", "extending.rst"])
    def test_the_code_in_the_guides_for_authors(self, repository_root: Path, page: str) -> None:
        text = (repository_root / "docs" / page).read_text()
        imports = re.findall(r"^\s+from (algorithm_playground[\w.]*) import", text, re.MULTILINE)
        assert imports, page
        assert set(imports) == {"algorithm_playground.authoring"}, page
