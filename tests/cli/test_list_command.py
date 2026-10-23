"""Tests for the list command."""

import json
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import Result

from algorithm_playground.core import Problem
from algorithm_playground.problems.sorting import SortingProblem
from helpers.scoring import register_near_sorting_problem
from helpers.support import (
    Configure,
    assert_exits_with,
    invoke_cli,
    parse_table_rows,
)
from helpers.two_dimensions import register_two_dimension_problem

pytestmark = pytest.mark.integration


def format_toml_list(*items: str) -> str:
    """Format the items as a TOML array of strings."""
    return json.dumps(list(items))


def build_configured_entry(
    name: str,
    script: Path,
    *,
    build_command: tuple[str, ...] | None = None,
    problem: str = "sorting",
    extra_lines: tuple[str, ...] = (),
) -> str:
    """Build the text of one ``[[implementations]]`` entry that runs a Python script.

    Args:
        name: The name of the implementation.
        script: The Python script the implementation runs.
        build_command: The build command, if the implementation has one.
        problem: The name of the problem the implementation solves.
        extra_lines: Further lines to add to the entry.

    Returns:
        The entry, ending in a newline.
    """
    lines = [
        "[[implementations]]",
        f"name = {json.dumps(name)}",
        f'problem = "{problem}"',
        f"command = {format_toml_list(sys.executable, str(script))}",
    ]
    if build_command is not None:
        lines.append(f"build_command = {format_toml_list(*build_command)}")
    lines.extend(extra_lines)
    return "\n".join(lines) + "\n"


ForgetModules = Callable[..., None]


MODULE_TEXT = """\
from algorithm_playground.core import Dimension, register_problem
from algorithm_playground.problems.sorting import SortingProblem


@register_problem
class Variant(SortingProblem):
    name = "{problem_name}"
    description = "A sorting variant defined outside the package."
"""


def test_list_shows_the_sorting_problem() -> None:
    """Test list shows the sorting problem."""
    result = invoke_cli("list")

    assert result.exit_code == 0
    assert "sorting" in result.stdout


def test_shows_configured_implementations_when_a_configuration_is_given(
    configure: Configure, python_sort_executable: Path
) -> None:
    """Test list shows the problems and the implementations of the given configuration."""
    path = configure(
        build_configured_entry("configured-sorter", python_sort_executable)
    )

    result = invoke_cli("list", "--configuration", str(path))

    assert result.exit_code == 0, result.stdout
    assert "Registered problems" in result.stdout
    assert "Configured implementations" in result.stdout
    assert "configured-sorter" in result.stdout


def test_omits_the_implementation_table_without_a_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test list shows no implementation table when there is no configuration."""
    monkeypatch.chdir(tmp_path)

    result = invoke_cli("list")

    assert result.exit_code == 0, result.stdout
    assert "Configured implementations" not in result.stdout


def test_a_configuration_without_implementations_is_a_warning_on_standard_error(
    configure: Configure,
) -> None:
    """Test a configuration that configures nothing is reported as a warning."""
    configure("")

    result = invoke_cli("list")

    assert result.exit_code == 0
    assert "algorithm-playground.toml configures no implementations." in result.stderr
    assert "configures no implementations" not in result.stdout


@pytest.fixture
def sorting_listing(
    wide_terminal: None,  # noqa: ARG001  requested for its side effect of widening the terminal
) -> Result:
    """The result of listing the details of the sorting problem."""
    return invoke_cli("list", "sorting")


def test_it_shows_the_description_and_where_the_problem_is_from(
    sorting_listing: Result,
) -> None:
    """Test the listing of a problem shows its description and that it is built in."""
    output = sorting_listing.stdout

    assert sorting_listing.exit_code == 0, sorting_listing.stderr
    assert (
        "sorting: Sort an array of 32-bit signed integers in ascending order." in output
    )
    assert "(built-in)" in output


def test_it_shows_the_fixtures(sorting_listing: Result) -> None:
    """Test the listing of a problem shows its fixtures with their descriptions."""
    output = sorting_listing.stdout

    assert "Fixtures (" in output
    assert "reverse_sorted" in output
    assert "descending input" in output
    assert "length_16" in output
    assert "next to a power of two" in output


def test_it_shows_the_distributions(sorting_listing: Result) -> None:
    """Test the listing of a problem shows its distributions with their descriptions."""
    output = sorting_listing.stdout

    assert "Distributions (10)" in output
    assert "median_of_three_killer" in output
    assert "Musser's sequence" in output


def test_it_shows_the_trace_support(sorting_listing: Result) -> None:
    """Test the listing of a problem says it has a trace format and what it counts."""
    output = sorting_listing.stdout

    assert "Trace format: yes" in output
    assert "compares, swaps, writes" in output


def test_the_default_and_the_debug_distribution_are_marked(
    sorting_listing: Result,
) -> None:
    """Test the listing marks the default distribution and the one used by debug."""
    roles = {
        row[0]: row[2]
        for row in parse_table_rows(sorting_listing.stdout)
        if len(row) == 3
    }

    assert roles["uniform"] == "default"
    assert roles["small_range"] == "debug"
    assert roles["sorted"] == ""


def test_the_minimum_size_is_mentioned_when_it_is_not_zero(
    tmp_path: Path, forget_modules: ForgetModules
) -> None:
    """Test the listing of a problem mentions the smallest size when it is above zero."""
    forget_modules("details_minimum_problem")
    module = tmp_path / "details_minimum_problem.py"
    module.write_text(
        MODULE_TEXT.format(problem_name="needs-two")
        + '    dimensions = (Dimension("size", minimum=2),)\n    operation_names = ()\n'
    )

    result = invoke_cli("list", "needs-two", "--problem-module", str(module))

    assert result.exit_code == 0, result.stderr
    assert "size (at least 2)" in result.stdout


@pytest.mark.usefixtures("wide_terminal")
def test_a_problem_without_a_trace_format_says_so(
    repository_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    forget_modules: ForgetModules,
) -> None:
    """Test the listing of a problem without a trace format says there is none."""
    forget_modules("distinct_count_problem")
    monkeypatch.chdir(repository_root / "examples" / "distinct_count")

    result = invoke_cli(
        "list", "distinct-count", "--problem-module", "distinct_count_problem"
    )

    assert result.exit_code == 0, result.stderr
    assert "Trace format: none" in result.stdout
    assert "all_distinct" in result.stdout
    assert "few_values" in result.stdout


def test_a_trace_format_without_declared_operations_says_what_happens(
    tmp_path: Path, forget_modules: ForgetModules
) -> None:
    """Test the listing says what is shown when the problem does not name its operations."""
    forget_modules("details_traced_problem")
    module = tmp_path / "details_traced_problem.py"
    module.write_text(
        MODULE_TEXT.format(problem_name="traced") + "    operation_names = ()\n"
    )

    result = invoke_cli("list", "traced", "--problem-module", str(module))

    assert (
        "Trace format: yes. The problem does not say which operations" in result.stdout
    )


def test_names_that_look_like_markup_are_shown_as_they_are(
    tmp_path: Path, forget_modules: ForgetModules
) -> None:
    """Test descriptions and fixture names that look like markup are printed as typed."""
    forget_modules("details_markup_problem")
    module = tmp_path / "details_markup_problem.py"
    module.write_text(
        "from algorithm_playground.authoring import Fixture, register_problem\n"
        "from algorithm_playground.problems.sorting import SortingProblem\n\n\n"
        "@register_problem\n"
        "class Markup(SortingProblem):\n"
        "    name = 'markup'\n"
        "    description = '[bold]loud[/bold] [red'\n"
        "    def fixtures(self):\n"
        "        yield Fixture('[red]boom', [1], description='[/oops] text')\n"
    )

    result = invoke_cli("list", "markup", "--problem-module", str(module))

    assert result.exit_code == 0, result.stderr
    assert "[red]boom" in result.stdout
    assert "[/oops] text" in result.stdout
    assert "[bold]loud[/bold] [red" in result.stdout


def test_an_unknown_problem_is_a_usage_error_listing_the_known_ones() -> None:
    """Test listing a problem that is not registered is a usage error naming the known ones."""
    result = invoke_cli("list", "nope")

    assert result.exit_code == 2
    assert "Unknown problem 'nope'. Registered problems: " in result.stderr


def test_the_configured_implementations_shown_are_those_of_the_problem(
    configure: Configure,
) -> None:
    """Test the listing of a problem shows the implementations configured for it."""
    configure(
        "[[implementations]]\nname = 'one'\nproblem = 'sorting'\ncommand = './one'\n",
        "[[implementations]]\nname = 'two'\nproblem = 'sorting'\ncommand = './two'\n",
    )

    result = invoke_cli("list", "sorting")

    assert result.exit_code == 0, result.stderr
    assert "Configured implementations" in result.stdout
    assert "one" in result.stdout
    assert "two" in result.stdout


def test_a_hook_that_raises_ends_in_a_message_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a fixtures hook that raises is reported by name and ends list with exit code 1."""

    def explode(_self: SortingProblem) -> list[object]:
        message = "no fixtures today"
        raise RuntimeError(message)

    monkeypatch.setattr(SortingProblem, "fixtures", explode)

    result = invoke_cli("list", "sorting")

    assert_exits_with(result, 1)
    assert "The problem's fixtures hook raised RuntimeError: no fixtures today." in (
        result.stderr
    )


def test_sorting_can_read_its_input_files() -> None:
    """Test list says that the sorting problem can read input files."""
    assert "Input files: readable" in invoke_cli("list", "sorting").stdout


def test_a_problem_that_cannot_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test list says that a problem without a way to read input files cannot read them."""
    monkeypatch.setattr(SortingProblem, "deserialize_input", Problem.deserialize_input)

    text = invoke_cli("list", "sorting").stdout

    assert "Input files: the problem does not implement deserialize_input" in text


@pytest.mark.usefixtures("wide_terminal")
def test_several_dimensions_are_listed_with_their_minimums() -> None:
    """Test the listing of a problem with two dimensions names them and their minimums."""
    name = register_two_dimension_problem()

    result = invoke_cli("list", name)

    assert result.exit_code == 0, result.stderr
    assert "vertices (at least 1)" in result.stdout
    assert "edges" in result.stdout


def test_a_problem_without_a_score_says_so(sorting_listing: Result) -> None:
    """Test the listing of a problem that scores nothing says there is no score."""
    assert "Score: none" in sorting_listing.stdout


@pytest.mark.usefixtures("wide_terminal")
def test_the_score_of_a_problem_is_named() -> None:
    """Test the listing of a scored problem names what its verifier scores."""
    name = register_near_sorting_problem()

    result = invoke_cli("list", name)

    assert result.exit_code == 0, result.stderr
    assert "Score: inversions" in result.stdout
