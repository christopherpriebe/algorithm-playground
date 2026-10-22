"""Tests for what the public packages export."""

import ast
import dataclasses
import inspect
import re
from pathlib import Path
from types import ModuleType

import pytest

from algorithm_playground import authoring, cli, core, visualization
from algorithm_playground.core import AlgorithmPlaygroundError
from algorithm_playground.problems import sorting

PUBLIC_PACKAGES = [authoring, cli, core, sorting, visualization]
DOCUMENTED_PACKAGES = [core, sorting, visualization]
API_PAGES = Path(__file__).resolve().parent.parent / "docs" / "api"


def exported_objects() -> list[tuple[str, object]]:
    """List every name the public packages export, with the object it names."""
    return [
        (f"{package.__name__}.{name}", getattr(package, name))
        for package in PUBLIC_PACKAGES
        for name in package.__all__
    ]


def exported_exceptions() -> list[type[BaseException]]:
    """List the exception classes the public packages export, each once."""
    found = {
        value
        for _, value in exported_objects()
        if isinstance(value, type) and issubclass(value, BaseException)
    }
    return sorted(found, key=lambda exception: exception.__name__)


def documented_names() -> set[str]:
    """Collect the dotted names that the API pages document with an autodoc directive."""
    pages = "".join(page.read_text() for page in API_PAGES.glob("*.rst"))
    return set(re.findall(r"^\.\. auto\w+:: ([\w.]+)$", pages, flags=re.MULTILINE))


def exported_dataclasses() -> list[type]:
    """List the dataclasses the public packages export, each once."""
    found = {
        value
        for _, value in exported_objects()
        if isinstance(value, type) and dataclasses.is_dataclass(value)
    }
    return sorted(found, key=lambda dataclass: dataclass.__name__)


EXPECTED_NAMES = {
    "AlgorithmPlaygroundError",
    "BarHighlight",
    "BinaryFormatError",
    "Dimension",
    "Fixture",
    "Frame",
    "FrameSequence",
    "InputGenerator",
    "Problem",
    "StateTimeline",
    "VerificationResult",
    "assert_valid_problem",
    "describe_sequence",
    "deduplicate_candidates",
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
    return group, [
        int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)
    ]


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


@pytest.mark.parametrize(
    "package",
    PUBLIC_PACKAGES,
    ids=[package.__name__ for package in PUBLIC_PACKAGES],
)
def test_every_exported_name_exists(package: ModuleType) -> None:
    """Test every name listed in a package's exports is defined."""
    missing = [name for name in package.__all__ if not hasattr(package, name)]

    assert missing == []


@pytest.mark.parametrize(
    "package",
    DOCUMENTED_PACKAGES,
    ids=[package.__name__ for package in DOCUMENTED_PACKAGES],
)
def test_every_exported_class_and_function_is_on_an_api_page(
    package: ModuleType,
) -> None:
    """Test the API pages document every class and function a package exports."""
    documented = documented_names()
    exported = [
        name
        for name in package.__all__
        if isinstance(getattr(package, name), type)
        or inspect.isfunction(getattr(package, name))
    ]

    missing = [
        name for name in exported if f"{package.__name__}.{name}" not in documented
    ]

    assert missing == []


def test_the_visualization_package_lists_its_lazily_loaded_names() -> None:
    """Test dir() of the visualization package includes the stepper and key names."""
    assert set(visualization.__all__) <= set(dir(visualization))


def test_an_unknown_name_of_the_visualization_package_is_an_attribute_error() -> None:
    """Test asking the visualization package for a name it lacks raises AttributeError."""
    name = "not_a_visualization_name"

    with pytest.raises(
        AttributeError, match="has no attribute 'not_a_visualization_name'"
    ):
        getattr(visualization, name)


@pytest.mark.parametrize(
    "exception", exported_exceptions(), ids=lambda exception: exception.__name__
)
def test_every_exported_exception_derives_from_the_package_base(
    exception: type[BaseException],
) -> None:
    """Test every exported exception can be caught as the package's base exception."""
    assert issubclass(exception, AlgorithmPlaygroundError)


@pytest.mark.parametrize(
    "value_type", exported_dataclasses(), ids=lambda value_type: value_type.__name__
)
def test_every_exported_dataclass_is_a_frozen_slotted_value(value_type: type) -> None:
    """Test every exported dataclass is frozen and uses slots."""
    parameters = value_type.__dataclass_params__  # ty: ignore[unresolved-attribute]  set by @dataclass on every dataclass

    assert parameters.frozen
    assert "__slots__" in vars(value_type)


# How many leading fields of each exported dataclass may be passed by position.
# Every other field is keyword-only, so its order is not part of the API.
POSITIONAL_FIELD_COUNTS = {
    "BarHighlight": 1,
    "BenchmarkFailure": 0,
    "BenchmarkProgress": 0,
    "BenchmarkReport": 0,
    "BenchmarkSettings": 0,
    "Case": 2,
    "CaseOutcome": 0,
    "CasePlan": 0,
    "CaseProgress": 0,
    "ChartSeries": 0,
    "CommandDependencies": 0,
    "Configuration": 0,
    "ConfiguredImplementation": 0,
    "Dimension": 1,
    "FailureDetail": 0,
    "Fixture": 2,
    "FixtureOrigin": 1,
    "Frame": 1,
    "GeneratedOrigin": 0,
    "Growth": 0,
    "Implementation": 2,
    "ImplementationBenchmark": 0,
    "InputGenerator": 1,
    "KeyPress": 1,
    "OperationIssue": 0,
    "ProblemSource": 0,
    "RegistrySnapshot": 0,
    "RunResult": 0,
    "SavedInputs": 0,
    "ShrinkOptions": 0,
    "ShrunkFailure": 0,
    "ShrunkOrigin": 1,
    "SingleRun": 0,
    "SizeMeasurement": 0,
    "SortingEvent": 3,
    "SortingTrace": 1,
    "StepperOptions": 0,
    "StepperState": 0,
    "TestReport": 0,
    "TestRunOptions": 0,
    "TestSettings": 0,
    "TimingSummary": 1,
    "VerificationResult": 1,
}


def test_every_exported_dataclass_has_a_positional_field_count() -> None:
    """Test a newly exported dataclass gets a decision on which fields are positional."""
    assert {value_type.__name__ for value_type in exported_dataclasses()} == set(
        POSITIONAL_FIELD_COUNTS
    )


@pytest.mark.parametrize(
    "value_type", exported_dataclasses(), ids=lambda value_type: value_type.__name__
)
def test_only_the_leading_fields_of_an_exported_dataclass_are_positional(
    value_type: type,
) -> None:
    """Test every field after the allowed leading ones must be passed by keyword."""
    parameters = list(inspect.signature(value_type).parameters.values())
    count = POSITIONAL_FIELD_COUNTS.get(value_type.__name__, 0)

    assert [parameter.kind for parameter in parameters] == [
        inspect.Parameter.POSITIONAL_OR_KEYWORD
    ] * count + [inspect.Parameter.KEYWORD_ONLY] * (len(parameters) - count)


@pytest.mark.parametrize(
    "name",
    [
        "Problem",
        "Fixture",
        "InputGenerator",
        "Case",
        "CasePlan",
        "Dimension",
        "Size",
        "VerificationResult",
        "register_problem",
        "BinaryFormatError",
        "write_u64",
        "read_u64",
        "write_i32_array",
        "read_i32_array",
        "assert_valid_problem",
        "validate_problem",
    ],
)
def test_a_problem_author_needs_only_the_core_package(name: str) -> None:
    """Test the package exports the names a problem author needs."""
    assert name in core.__all__


def test_it_exports_what_a_problem_author_needs() -> None:
    """Test the module exports exactly the names a problem author needs."""
    assert set(authoring.__all__) == EXPECTED_NAMES


def test_every_name_authoring_exports_exists() -> None:
    """Test every name listed in the module's exports is defined."""
    missing = [name for name in authoring.__all__ if not hasattr(authoring, name)]

    assert missing == []


def test_the_names_are_the_ones_of_the_packages_that_implement_them() -> None:
    """Test each exported name is the object of the package that implements it."""
    reexported_copies = [
        name
        for name in authoring.__all__
        if getattr(authoring, name)
        is not getattr(core if hasattr(core, name) else visualization, name)
    ]

    assert reexported_copies == []


@pytest.mark.parametrize(
    "name",
    ["run_tests", "run_benchmark", "Runner", "Implementation", "get_problem"],
)
def test_it_does_not_export_engine_internals(name: str) -> None:
    """Test the names that belong to the engines are not exported."""
    assert name not in authoring.__all__


def test_the_names_are_in_reading_order() -> None:
    """Test the exports list constants, then classes, then functions, each in natural order."""
    assert authoring.__all__ == sorted(authoring.__all__, key=compute_reading_order)


def test_the_distinct_count_example_imports_only_from_the_authoring_module(
    repository_root: Path,
) -> None:
    """Test the distinct-count example problem imports nothing but the authoring module."""
    path = repository_root / "examples" / "distinct_count" / "distinct_count_problem.py"

    assert find_imported_modules(path.read_text()) == {"algorithm_playground.authoring"}


@pytest.mark.parametrize("page", ["writing-a-problem.rst", "extending.rst"])
def test_the_code_in_the_guides_for_authors_imports_only_from_the_authoring_module(
    repository_root: Path, page: str
) -> None:
    """Test the code samples in a guide for authors import nothing but the authoring module."""
    text = (repository_root / "docs" / page).read_text()

    imports = re.findall(
        r"^\s+from (algorithm_playground[\w.]*) import", text, re.MULTILINE
    )

    assert imports, page
    assert set(imports) == {"algorithm_playground.authoring"}, page
