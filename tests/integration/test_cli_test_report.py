"""CLI tests for how ``test`` lays out its matrix and its failures.

Most tests use in-process fake runners, so a whole default run (24 fixtures and 20
generated cases) costs milliseconds; the ones that save files use real executables.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import FakeRunners, drop_last_above_five, sort_correctly
from support import Invoke, TableRows, assert_exits_with

from algorithm_playground.core.cases import resolve_case
from algorithm_playground.core.saved_inputs import safe_file_name
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

UseFakeRunners = Callable[..., FakeRunners]

LARGE_CASE = "generated:uniform:size=12:seed=5"
SAVED_CASE_DIRECTORY = safe_file_name(LARGE_CASE)
FIXTURES = {fixture.name: fixture.input_data for fixture in SortingProblem().fixtures()}
FAILING_FIXTURES = [name for name, values in FIXTURES.items() if len(values) > 5]


def short_or_unsorted(values: list[int]) -> list[int]:
    """Two kinds of wrong: loses an element of a long input, leaves a short one in reverse."""
    return values[:-1] if len(values) > 5 else sorted(values, reverse=True)


class TestMatrix:
    def test_the_fixtures_are_one_row_and_only_failing_ones_get_a_row_of_their_own(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_test_runners({"good": sort_correctly, "bad": drop_last_above_five})
        result = invoke("test", "sorting", "--command", "good", "--command", "bad")
        assert_exits_with(result, 1)
        rows = table_rows(result.stdout)
        failing = len(FAILING_FIXTURES)
        assert rows[0] == ["fixtures", "24/24", f"{24 - failing}/24"]
        assert [row[0] for row in rows[1 : 1 + failing]] == FAILING_FIXTURES
        assert all(row[1:] == ["PASS", "FAIL"] for row in rows[1 : 1 + failing])
        assert rows[1 + failing][0] == "uniform"

    def test_all_passing_fixtures_are_a_single_row(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_test_runners({"good": sort_correctly})
        result = invoke("test", "sorting", "--command", "good")
        assert result.exit_code == 0, result.stdout
        rows = table_rows(result.stdout)
        assert rows[0] == ["fixtures", "24/24"]
        assert [row[0] for row in rows[1:]] == [
            generator.name for generator in SortingProblem().generators()
        ]

    def test_the_expanded_fixture_rows_are_indented_under_the_counted_row(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners
    ) -> None:
        use_fake_test_runners({"bad": drop_last_above_five})
        result = invoke("test", "sorting", "--command", "bad", "--random-cases", "0")
        lines = [line for line in result.stdout.splitlines() if line.startswith("│")]
        assert lines[0].startswith("│ fixtures")
        assert lines[1].startswith("│   ")

    def test_verbose_shows_every_fixture_and_no_counted_row(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_test_runners({"good": sort_correctly, "bad": drop_last_above_five})
        result = invoke(
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
        rows = table_rows(result.stdout)
        assert [row[0] for row in rows] == list(FIXTURES)
        assert {row[1] for row in rows} == {"PASS"}
        assert {row[2] for row in rows} == {"PASS", "FAIL"}
        assert "fixtures" not in {row[0] for row in rows}

    def test_distributions_are_named_without_a_prefix_below_a_rule(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_test_runners({"good": sort_correctly})
        result = invoke(
            "test",
            "sorting",
            "--command",
            "good",
            "--distribution",
            "sorted",
            "--random-cases",
            "4",
        )
        assert [row[0] for row in table_rows(result.stdout)] == ["fixtures", "sorted"]
        assert "generated:sorted" not in result.stdout
        assert "├" in result.stdout

    def test_a_matrix_with_only_generated_cases_has_no_rule(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_test_runners({"good": sort_correctly})
        result = invoke(
            "test", "sorting", "--command", "good", "--no-fixtures", "--random-cases", "3"
        )
        assert "├" not in result.stdout
        assert "fixtures" not in {row[0] for row in table_rows(result.stdout)}

    def test_a_long_case_name_is_folded_not_cut(
        self,
        invoke: Invoke,
        use_fake_test_runners: UseFakeRunners,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("COLUMNS", "40")
        use_fake_test_runners({"a": sort_correctly, "b": sort_correctly, "c": sort_correctly})
        result = invoke(
            "test",
            "sorting",
            *["--command", "a", "--command", "b", "--command", "c"],
            *["--distribution", "median_of_three_killer", "--random-cases", "1", "--no-fixtures"],
        )
        assert "…" not in result.stdout
        assert "median_of_three" in result.stdout.replace("\n", "").replace("│", "").replace(
            " ", ""
        )


class TestGroupedFailures:
    def test_failures_that_shrink_to_the_same_input_are_one_block(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners
    ) -> None:
        use_fake_test_runners({"bad": drop_last_above_five})
        result = invoke(
            "test", "sorting", "--command", "bad", "--fixture", "duplicates", "--case", LARGE_CASE
        )
        assert_exits_with(result, 1)
        assert result.stdout.count("FAIL bad on") == 2  # the shrunk one, and the fixture
        assert "shrunk input: [0, 0, 0, 0, 0, 0]" in result.stdout

    def test_many_generated_failures_become_one_block_naming_the_others(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners
    ) -> None:
        use_fake_test_runners({"bad": drop_last_above_five})
        result = invoke(
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
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners
    ) -> None:
        use_fake_test_runners({"mixed": short_or_unsorted})
        result = invoke(
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
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners
    ) -> None:
        use_fake_test_runners({"bad": drop_last_above_five})
        result = invoke(
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
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners
    ) -> None:
        use_fake_test_runners({"mixed": short_or_unsorted})
        result = invoke(
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
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners
    ) -> None:
        use_fake_test_runners({"bad": drop_last_above_five})
        result = invoke(
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
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, tmp_path: Path
    ) -> None:
        use_fake_test_runners({"bad": drop_last_above_five})
        path = tmp_path / "report.json"
        invoke("test", "sorting", "--command", "bad", "--json", str(path))
        outcomes = json.loads(path.read_text())["implementations"][0]["outcomes"]
        failing = [outcome for outcome in outcomes if outcome["status"] == "failed"]
        assert len(failing) > 10
        assert {outcome["category"] for outcome in failing} == {"wrong length"}


class TestDescriptionWidth:
    def failure_text(self, invoke: Invoke, columns: int, monkeypatch: pytest.MonkeyPatch) -> str:
        monkeypatch.setenv("COLUMNS", str(columns))
        result = invoke(
            "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
        )
        return result.stdout

    def test_a_wide_terminal_shows_the_whole_input(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        use_fake_test_runners({"drops": drop_last_above_five})
        text = self.failure_text(invoke, 300, monkeypatch)
        assert "(12 values)" not in text
        assert re.search(r"input: \[(-?\d+, ){11}-?\d+\]", text)

    def test_a_narrow_terminal_shortens_it_to_fit_a_line(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        use_fake_test_runners({"drops": drop_last_above_five})
        text = self.failure_text(invoke, 70, monkeypatch)
        lines = [
            line
            for line in text.splitlines()
            if line.strip().startswith(("input:", "expected:", "actual:"))
        ]
        assert len(lines) == 3
        assert all(len(line) <= 70 for line in lines), lines
        assert "(12 values" in text


class TestSavingFailingInputs:
    def test_every_failing_input_is_written_and_named_in_the_report(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, tmp_path: Path
    ) -> None:
        use_fake_test_runners({"drops": drop_last_above_five})
        directory = tmp_path / "failures"
        result = invoke(
            *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
            *["--fixture", "duplicates", "--save-failing-inputs", str(directory)],
        )
        assert_exits_with(result, 1)
        root = directory / "drops"
        problem = SortingProblem()
        saved = root / SAVED_CASE_DIRECTORY
        fixture_folder = root / safe_file_name("fixture:duplicates")
        assert problem.deserialize_input(saved / "input.bin") == (
            resolve_case(problem, LARGE_CASE).input_data
        )
        assert problem.deserialize_input(saved / "shrunk-input.bin") == [0] * 6
        assert problem.deserialize_input(fixture_folder / "input.bin") == FIXTURES["duplicates"]
        assert not (fixture_folder / "shrunk-input.bin").exists()
        assert f"saved input: {saved / 'input.bin'}" in result.stdout
        assert f"saved shrunk input: {saved / 'shrunk-input.bin'}" in result.stdout

    def test_passing_cases_leave_nothing_behind(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        directory = tmp_path / "failures"
        result = invoke(
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
        self, invoke: Invoke, drops_last_executable: Path, tmp_path: Path
    ) -> None:
        directory = tmp_path / "failures"
        invoke(
            "test",
            "sorting",
            str(drops_last_executable),
            "--case",
            LARGE_CASE,
            "--save-failing-inputs",
            str(directory),
        )
        saved = directory / "drops_last.py" / SAVED_CASE_DIRECTORY / "shrunk-input.bin"
        result = invoke("debug", "sorting", str(drops_last_executable), "--input-file", str(saved))
        assert_exits_with(result, 1)
        assert "Output length 5 does not match input length 6" in result.stderr
        assert "input: [0, 0, 0, 0, 0, 0]" in result.stderr

    def test_the_paths_are_in_the_json_report(
        self, invoke: Invoke, use_fake_test_runners: UseFakeRunners, tmp_path: Path
    ) -> None:
        use_fake_test_runners({"drops": drop_last_above_five})
        directory, report = tmp_path / "failures", tmp_path / "report.json"
        invoke(
            *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
            *["--save-failing-inputs", str(directory), "--json", str(report)],
        )
        (outcome,) = json.loads(report.read_text())["implementations"][0]["outcomes"]
        folder = directory / "drops" / SAVED_CASE_DIRECTORY
        assert outcome["saved_input"] == str(folder / "input.bin")
        assert outcome["saved_shrunk_input"] == str(folder / "shrunk-input.bin")

    def test_a_path_that_is_a_file_is_a_usage_error_before_anything_runs(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        result = invoke(
            "test", "sorting", str(python_sort_executable), "--save-failing-inputs", str(blocker)
        )
        assert_exits_with(result, 2)
        assert "Invalid value for '--save-failing-inputs'" in result.stderr
        assert result.stdout == ""

    def test_a_path_below_a_file_is_a_usage_error(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        result = invoke(
            "test",
            "sorting",
            str(python_sort_executable),
            "--save-failing-inputs",
            str(blocker / "below"),
        )
        assert_exits_with(result, 2)
        assert "--save-failing-inputs cannot create" in result.stderr
        assert result.stdout == ""
