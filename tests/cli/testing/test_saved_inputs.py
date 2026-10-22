"""Tests for saving the inputs of failing cases from the test command."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from typer.testing import Result

from algorithm_playground.core import make_safe_file_name, resolve_case
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import FakeRunners, drop_last_above_five
from helpers.support import (
    assert_exits_with,
    invoke_cli,
)

pytestmark = pytest.mark.integration


LARGE_CASE = "generated:uniform:size=12:seed=5"


UseFakeRunners = Callable[..., FakeRunners]


SAVED_CASE_DIRECTORY = make_safe_file_name(LARGE_CASE)


FIXTURES = {fixture.name: fixture.input_data for fixture in SortingProblem().fixtures()}


class SavedFailures(NamedTuple):
    """The outcome of a test command that saved its failing inputs."""

    result: Result
    directory: Path


@pytest.fixture
def saved_failures(
    use_fake_test_runners: UseFakeRunners, tmp_path: Path
) -> SavedFailures:
    """Save the failing inputs of a generated case and a fixture, and write a report."""
    use_fake_test_runners({"drops": drop_last_above_five})
    directory = tmp_path / "failures"
    result = invoke_cli(
        *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
        *["--fixture", "duplicates", "--save-failing-inputs", str(directory)],
    )
    return SavedFailures(result, directory)


def test_the_input_and_the_shrunk_input_of_a_generated_case_are_written(
    saved_failures: SavedFailures,
) -> None:
    """Test a failing generated case is saved with its shrunk input."""
    saved = saved_failures.directory / "drops" / SAVED_CASE_DIRECTORY
    problem = SortingProblem()

    assert_exits_with(saved_failures.result, 1)
    assert problem.deserialize_input(saved / "input.bin") == (
        resolve_case(problem, LARGE_CASE).input_data
    )
    assert problem.deserialize_input(saved / "shrunk-input.bin") == [0] * 6


def test_a_failing_fixture_is_saved_without_a_shrunk_input(
    saved_failures: SavedFailures,
) -> None:
    """Test a failing fixture that was not shrunk is saved as its input only."""
    folder = (
        saved_failures.directory / "drops" / make_safe_file_name("fixture:duplicates")
    )

    assert (
        SortingProblem().deserialize_input(folder / "input.bin")
        == FIXTURES["duplicates"]
    )
    assert not (folder / "shrunk-input.bin").exists()


def test_the_saved_files_are_named_in_the_output(saved_failures: SavedFailures) -> None:
    """Test the output names the files that hold the saved inputs."""
    saved = saved_failures.directory / "drops" / SAVED_CASE_DIRECTORY

    assert f"saved input: {saved / 'input.bin'}" in saved_failures.result.stdout
    assert (
        f"saved shrunk input: {saved / 'shrunk-input.bin'}"
        in saved_failures.result.stdout
    )


def test_passing_cases_leave_nothing_behind(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test no directory is created when every case passes."""
    directory = tmp_path / "failures"

    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "--fixture",
        "empty",
        "--save-failing-inputs",
        str(directory),
    )

    assert result.exit_code == 0, result.stdout
    assert not directory.exists()
    assert "saved input" not in result.stdout


def test_a_saved_input_makes_the_same_implementation_fail_under_debug(
    drops_last_executable: Path, tmp_path: Path
) -> None:
    """Test the saved shrunk input, given to debug, fails the implementation again."""
    directory = tmp_path / "failures"
    invoke_cli(
        "test",
        "sorting",
        str(drops_last_executable),
        "--case",
        LARGE_CASE,
        "--save-failing-inputs",
        str(directory),
    )
    saved = directory / "drops_last.py" / SAVED_CASE_DIRECTORY / "shrunk-input.bin"

    result = invoke_cli(
        "debug", "sorting", str(drops_last_executable), "--input-file", str(saved)
    )

    assert_exits_with(result, 1)
    assert "Output length 5 does not match input length 6" in result.stderr
    assert "input: [0, 0, 0, 0, 0, 0]" in result.stderr


def test_the_paths_are_in_the_json_report(
    use_fake_test_runners: UseFakeRunners, tmp_path: Path
) -> None:
    """Test the JSON report gives the paths of the saved input and the saved shrunk input."""
    use_fake_test_runners({"drops": drop_last_above_five})
    directory, report = tmp_path / "failures", tmp_path / "report.json"

    invoke_cli(
        *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
        *["--save-failing-inputs", str(directory), "--json", str(report)],
    )

    (outcome,) = json.loads(report.read_text())["implementations"][0]["outcomes"]
    folder = directory / "drops" / SAVED_CASE_DIRECTORY
    assert outcome["saved_input"] == str(folder / "input.bin")
    assert outcome["saved_shrunk_input"] == str(folder / "shrunk-input.bin")


def test_a_path_that_is_a_file_is_a_usage_error_before_anything_runs(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test a file given as the directory for saved inputs is a usage error."""
    blocker = tmp_path / "blocker"
    blocker.write_text("")

    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "--save-failing-inputs",
        str(blocker),
    )

    assert_exits_with(result, 2)
    assert "Invalid value for '--save-failing-inputs'" in result.stderr
    assert result.stdout == ""


def test_a_path_below_a_file_is_a_usage_error(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test a directory for saved inputs below a file is a usage error."""
    blocker = tmp_path / "blocker"
    blocker.write_text("")

    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "--save-failing-inputs",
        str(blocker / "below"),
    )

    assert_exits_with(result, 2)
    assert "--save-failing-inputs cannot create" in result.stderr
    assert result.stdout == ""
