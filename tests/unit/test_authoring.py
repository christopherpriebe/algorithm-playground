"""Tests for the stable module a problem author imports from."""

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


def compute_reading_order(name: str) -> tuple[int, list[int | str]]:
    """Return the sort key that puts constants, then classes, then functions in natural order."""
    group = 0 if name.isupper() else 1 if name[0].isupper() else 2
    return group, [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def find_imported_modules(source: str) -> set[str]:
    """Find the ``algorithm_playground`` modules a piece of Python source imports from."""
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


class TestSurface:
    def test_it_exports_what_a_problem_author_needs(self) -> None:
        """Test the module exports exactly the names a problem author needs."""
        assert set(authoring.__all__) == EXPECTED_NAMES

    def test_every_exported_name_exists(self) -> None:
        """Test every name listed in the module's exports is defined."""
        missing = [name for name in authoring.__all__ if not hasattr(authoring, name)]

        assert missing == []

    def test_the_names_are_the_ones_of_the_packages_that_implement_them(self) -> None:
        """Test each exported name is the object of the package that implements it."""
        reexported_copies = [
            name
            for name in authoring.__all__
            if getattr(authoring, name)
            is not getattr(core if hasattr(core, name) else visualization, name)
        ]

        assert reexported_copies == []

    @pytest.mark.parametrize(
        "name", ["run_tests", "run_benchmark", "Runner", "Implementation", "get_problem"]
    )
    def test_it_does_not_export_engine_internals(self, name: str) -> None:
        """Test the names that belong to the engines are not exported."""
        assert name not in authoring.__all__

    def test_the_names_are_in_reading_order(self) -> None:
        """Test the exports list constants, then classes, then functions, each in natural order."""
        assert authoring.__all__ == sorted(authoring.__all__, key=compute_reading_order)


class TestAuthorsImportOnlyFromIt:
    def test_the_distinct_count_example_imports_only_from_the_authoring_module(
        self, repository_root: Path
    ) -> None:
        """Test the distinct-count example problem imports nothing but the authoring module."""
        path = repository_root / "examples" / "distinct_count" / "distinct_count_problem.py"

        assert find_imported_modules(path.read_text()) == {"algorithm_playground.authoring"}

    @pytest.mark.parametrize("page", ["writing-a-problem.rst", "extending.rst"])
    def test_the_code_in_the_guides_for_authors_imports_only_from_the_authoring_module(
        self, repository_root: Path, page: str
    ) -> None:
        """Test the code samples in a guide for authors import nothing but the authoring module."""
        text = (repository_root / "docs" / page).read_text()

        imports = re.findall(r"^\s+from (algorithm_playground[\w.]*) import", text, re.MULTILINE)

        assert imports, page
        assert set(imports) == {"algorithm_playground.authoring"}, page
