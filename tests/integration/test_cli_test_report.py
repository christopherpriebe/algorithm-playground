"""CLI tests for how ``test`` lays out its matrix and its failures.

Most tests use in-process fake runners, so a whole default run (24 fixtures and 20
generated cases) costs milliseconds; the ones that save files use real executables.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from helpers.fakes import FakeRunners, drop_last_above_five, sort_correctly
from helpers.support import assert_exits_with, invoke_cli, parse_table_rows
from typer.testing import Result

from algorithm_playground.core.cases import resolve_case
from algorithm_playground.core.saved_inputs import safe_file_name
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

UseFakeRunners = Callable[..., FakeRunners]

LARGE_CASE = "generated:uniform:size=12:seed=5"
SAVED_CASE_DIRECTORY = safe_file_name(LARGE_CASE)
FIXTURES = {fixture.name: fixture.input_data for fixture in SortingProblem().fixtures()}
FAILING_FIXTURES = [name for name, values in FIXTURES.items() if len(values) > 5]


class SavedFailures(NamedTuple):
    """The outcome of a test command that saved its failing inputs."""

    result: Result
    directory: Path


def drop_last_or_reverse(values: list[int]) -> list[int]:
    """Two kinds of wrong: loses an element of a long input, leaves a short one in reverse."""
    return values[:-1] if len(values) > 5 else sorted(values, reverse=True)


def render_failure_text(columns: int, monkeypatch: pytest.MonkeyPatch) -> str:
    """Return the output of a failing case on a terminal with the given number of columns."""
    monkeypatch.setenv("COLUMNS", str(columns))
    result = invoke_cli(
        "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
    )
    return result.stdout


class TestMatrix:
    def test_the_fixtures_are_one_row_and_only_failing_ones_get_a_row_of_their_own(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test passing fixtures are counted in one row and each failing fixture has its own."""
        use_fake_test_runners({"good": sort_correctly, "bad": drop_last_above_five})

        result = invoke_cli("test", "sorting", "--command", "good", "--command", "bad")

        assert_exits_with(result, 1)
        rows = parse_table_rows(result.stdout)
        failing = len(FAILING_FIXTURES)
        assert rows[0] == ["fixtures", "24/24", f"{24 - failing}/24"]
        assert [row[0] for row in rows[1 : 1 + failing]] == FAILING_FIXTURES
        assert all(row[1:] == ["PASS", "FAIL"] for row in rows[1 : 1 + failing])
        assert rows[1 + failing][0] == "uniform"

    def test_all_passing_fixtures_are_a_single_row(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test fixtures that all pass are summarized in one row, followed by the distributions."""
        use_fake_test_runners({"good": sort_correctly})

        result = invoke_cli("test", "sorting", "--command", "good")

        assert result.exit_code == 0, result.stdout
        rows = parse_table_rows(result.stdout)
        assert rows[0] == ["fixtures", "24/24"]
        assert [row[0] for row in rows[1:]] == [
            generator.name for generator in SortingProblem().generators()
        ]

    def test_the_expanded_fixture_rows_are_indented_under_the_counted_row(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test the rows of failing fixtures are indented below the row that counts fixtures."""
        use_fake_test_runners({"bad": drop_last_above_five})

        result = invoke_cli("test", "sorting", "--command", "bad", "--random-cases", "0")

        lines = [line for line in result.stdout.splitlines() if line.startswith("│")]
        assert lines[0].startswith("│ fixtures")
        assert lines[1].startswith("│   ")

    def test_verbose_shows_every_fixture_and_no_counted_row(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test the verbose option gives every fixture its own row and no counting row."""
        use_fake_test_runners({"good": sort_correctly, "bad": drop_last_above_five})

        result = invoke_cli(
            "test",
            "sorting",
            "--command",
            "good",
            "--command",
            "bad",
            "--verbose",
            "--random-cases",
            "0",
        )

        rows = parse_table_rows(result.stdout)
        assert [row[0] for row in rows] == list(FIXTURES)
        assert {row[1] for row in rows} == {"PASS"}
        assert {row[2] for row in rows} == {"PASS", "FAIL"}
        assert "fixtures" not in {row[0] for row in rows}

    def test_distributions_are_named_without_a_prefix_below_a_rule(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test generated cases are grouped by distribution name, below a rule under fixtures."""
        use_fake_test_runners({"good": sort_correctly})

        result = invoke_cli(
            "test",
            "sorting",
            "--command",
            "good",
            "--distribution",
            "sorted",
            "--random-cases",
            "4",
        )

        assert [row[0] for row in parse_table_rows(result.stdout)] == ["fixtures", "sorted"]
        assert "generated:sorted" not in result.stdout
        assert "├" in result.stdout

    def test_a_matrix_with_only_generated_cases_has_no_rule(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test no rule is drawn when there are no fixtures to separate from the generated cases."""
        use_fake_test_runners({"good": sort_correctly})

        result = invoke_cli(
            "test", "sorting", "--command", "good", "--no-fixtures", "--random-cases", "3"
        )

        assert "├" not in result.stdout
        assert "fixtures" not in {row[0] for row in parse_table_rows(result.stdout)}

    def test_a_long_case_name_is_folded_not_cut(
        self,
        use_fake_test_runners: UseFakeRunners,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test a row label that is too wide for the terminal is folded over lines, not cut."""
        monkeypatch.setenv("COLUMNS", "40")
        use_fake_test_runners({"one": sort_correctly, "two": sort_correctly, "six": sort_correctly})

        result = invoke_cli(
            "test",
            "sorting",
            *["--command", "one", "--command", "two", "--command", "six"],
            *["--distribution", "median_of_three_killer", "--random-cases", "1", "--no-fixtures"],
        )

        assert "…" not in result.stdout
        assert "median_of_three" in result.stdout.replace("\n", "").replace("│", "").replace(
            " ", ""
        )


class TestGroupedFailures:
    def test_failures_that_shrink_to_the_same_input_are_one_block(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test failures that shrink to the same input are described once."""
        use_fake_test_runners({"bad": drop_last_above_five})

        result = invoke_cli(
            "test", "sorting", "--command", "bad", "--fixture", "duplicates", "--case", LARGE_CASE
        )

        assert_exits_with(result, 1)
        assert result.stdout.count("FAIL bad on") == 2  # the shrunk one, and the fixture
        assert "shrunk input: [0, 0, 0, 0, 0, 0]" in result.stdout

    def test_many_generated_failures_become_one_block_naming_the_others(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test generated failures beyond the shrunk ones are grouped in one block."""
        use_fake_test_runners({"bad": drop_last_above_five})

        result = invoke_cli(
            "test",
            "sorting",
            "--command",
            "bad",
            "--no-fixtures",
            "--random-cases",
            "6",
            "--seed",
            "3",
        )

        blocks = [line for line in result.stdout.splitlines() if line.startswith("FAIL bad on")]
        shrunk_blocks = re.findall(r"shrunk input: (.*)", result.stdout)
        assert len(blocks) == 2  # the three that were shrunk, and the rest
        assert shrunk_blocks == ["[0, 0, 0, 0, 0, 0]"]
        assert "same failure on: " in result.stdout

    def test_the_smallest_failing_input_comes_first(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test fixtures come before generated cases, and the smaller generated case leads."""
        use_fake_test_runners({"mixed": drop_last_or_reverse})

        result = invoke_cli(
            "test",
            "sorting",
            *["--command", "mixed", "--no-shrink", "--maximum-failures", "9"],
            *[
                "--case",
                "generated:uniform:size=30:seed=1",
                "--case",
                "generated:uniform:size=9:seed=1",
            ],
            *["--case", "fixture:two_unsorted"],
        )

        order = re.findall(r"^FAIL mixed on (\S+)$", result.stdout, re.MULTILINE)
        # A fixture comes before generated cases, and the smaller generated case leads the
        # block of its kind of failure, with the larger one listed after "same failure on".
        assert order == ["fixture:two_unsorted", "generated:uniform:size=9:seed=1"]
        assert "same failure on: generated:uniform:size=30:seed=1" in result.stdout

    def test_a_shrunk_group_comes_before_unshrunk_failures(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test the failures that were shrunk are described before those that were not."""
        use_fake_test_runners({"bad": drop_last_above_five})

        result = invoke_cli(
            "test",
            "sorting",
            "--command",
            "bad",
            "--fixture",
            "reverse_sorted",
            "--case",
            LARGE_CASE,
        )

        order = re.findall(r"^FAIL bad on (\S+)$", result.stdout, re.MULTILINE)
        assert order == [LARGE_CASE, "fixture:reverse_sorted"]

    def test_failures_of_another_category_are_a_block_of_their_own(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test failures with a different cause are not grouped with the others."""
        use_fake_test_runners({"mixed": drop_last_or_reverse})

        result = invoke_cli(
            "test",
            "sorting",
            "--command",
            "mixed",
            "--no-shrink",
            "--maximum-failures",
            "9",
            *["--fixture", "two_unsorted", "--fixture", "three_321"],
            *["--fixture", "reverse_sorted", "--fixture", "duplicates"],
        )

        headers = re.findall(r"^FAIL mixed on (\S+)$", result.stdout, re.MULTILINE)
        assert sorted(headers) == ["fixture:reverse_sorted", "fixture:two_unsorted"]
        assert "same failure on: fixture:duplicates" in result.stdout
        assert "same failure on: fixture:three_321" in result.stdout

    def test_cases_left_unshrunk_by_the_limit_say_so_once_per_block(
        self, use_fake_test_runners: UseFakeRunners
    ) -> None:
        """Test a block says once that its cases were not shrunk because of the limit."""
        use_fake_test_runners({"bad": drop_last_above_five})

        result = invoke_cli(
            "test",
            "sorting",
            "--command",
            "bad",
            "--no-fixtures",
            "--random-cases",
            "12",
            "--seed",
            "1",
        )

        assert (
            "shrink note: not shrunk: the limit of 3 shrunk cases per implementation"
            in result.stdout
        )
        assert result.stdout.count("shrink note:") == 1

    def test_the_json_report_has_every_failure_even_when_blocks_are_grouped(
        self, use_fake_test_runners: UseFakeRunners, tmp_path: Path
    ) -> None:
        """Test the JSON report lists each failing case, however the printed blocks are grouped."""
        use_fake_test_runners({"bad": drop_last_above_five})
        path = tmp_path / "report.json"

        invoke_cli("test", "sorting", "--command", "bad", "--json", str(path))

        outcomes = json.loads(path.read_text())["implementations"][0]["outcomes"]
        failing = [outcome for outcome in outcomes if outcome["status"] == "failed"]
        assert len(failing) > 10
        assert {outcome["category"] for outcome in failing} == {"wrong length"}


class TestDescriptionWidth:
    def test_a_wide_terminal_shows_the_whole_input(
        self, use_fake_test_runners: UseFakeRunners, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test a wide terminal has room for the whole input in the description of a failure."""
        use_fake_test_runners({"drops": drop_last_above_five})

        text = render_failure_text(300, monkeypatch)

        assert "(12 values)" not in text
        assert re.search(r"input: \[(-?\d+, ){11}-?\d+\]", text)

    def test_a_narrow_terminal_shortens_it_to_fit_a_line(
        self, use_fake_test_runners: UseFakeRunners, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test a narrow terminal shortens the lines that describe a failure to its width."""
        use_fake_test_runners({"drops": drop_last_above_five})

        text = render_failure_text(70, monkeypatch)

        lines = [
            line
            for line in text.splitlines()
            if line.strip().startswith(("input:", "expected:", "actual:"))
        ]
        assert len(lines) == 3
        assert all(len(line) <= 70 for line in lines), lines
        assert "(12 values" in text


class TestSavingFailingInputs:
    @pytest.fixture
    def saved_failures(
        self, use_fake_test_runners: UseFakeRunners, tmp_path: Path
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
        self, saved_failures: SavedFailures
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
        self, saved_failures: SavedFailures
    ) -> None:
        """Test a failing fixture that was not shrunk is saved as its input only."""
        folder = saved_failures.directory / "drops" / safe_file_name("fixture:duplicates")

        assert SortingProblem().deserialize_input(folder / "input.bin") == FIXTURES["duplicates"]
        assert not (folder / "shrunk-input.bin").exists()

    def test_the_saved_files_are_named_in_the_output(self, saved_failures: SavedFailures) -> None:
        """Test the output names the files that hold the saved inputs."""
        saved = saved_failures.directory / "drops" / SAVED_CASE_DIRECTORY

        assert f"saved input: {saved / 'input.bin'}" in saved_failures.result.stdout
        assert f"saved shrunk input: {saved / 'shrunk-input.bin'}" in saved_failures.result.stdout

    def test_passing_cases_leave_nothing_behind(
        self, python_sort_executable: Path, tmp_path: Path
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
        self, drops_last_executable: Path, tmp_path: Path
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
        self, use_fake_test_runners: UseFakeRunners, tmp_path: Path
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
        self, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test a file given as the directory for saved inputs is a usage error."""
        blocker = tmp_path / "blocker"
        blocker.write_text("")

        result = invoke_cli(
            "test", "sorting", str(python_sort_executable), "--save-failing-inputs", str(blocker)
        )

        assert_exits_with(result, 2)
        assert "Invalid value for '--save-failing-inputs'" in result.stderr
        assert result.stdout == ""

    def test_a_path_below_a_file_is_a_usage_error(
        self, python_sort_executable: Path, tmp_path: Path
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
