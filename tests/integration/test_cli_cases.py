"""End-to-end CLI tests for case selection, failure reports, shrinking, and the JSON report.

Runs use tiny inputs and few cases; the engine's own behavior is covered in-process.
"""

import json
import os
import re
import shlex
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from helpers.fakes import FakeRunners, drop_last_above_five
from helpers.support import assert_exits_with, invoke_cli, parse_table_rows, read_logged_inputs
from typer.testing import Result

from algorithm_playground.cli import test_command
from algorithm_playground.core.cases import resolve_case
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

UseFakeTestRunners = Callable[..., FakeRunners]

LARGE_CASE = "generated:uniform:size=12:seed=5"


class ReportRun(NamedTuple):
    """The outcome of a test command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]


def extract_reproduce_arguments(output: str) -> list[str]:
    """Return the words of the reproduce command that the output of ``test`` prints."""
    line = next(
        line.strip().removeprefix("reproduce: ")
        for line in output.splitlines()
        if line.strip().startswith("reproduce: ")
    )
    return shlex.split(line)


@pytest.fixture
def nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if the engine is started: the command must have stopped before that."""

    def refuse(*arguments: object, **keywords: object) -> None:
        raise AssertionError("the test engine must not run")

    monkeypatch.setattr(test_command, "run_tests", refuse)


class TestCaseSelection:
    def test_generated_cases_are_summarized_per_distribution(
        self, python_sort_executable: Path
    ) -> None:
        """Test generated cases are counted in one row for each distribution."""
        result = invoke_cli(
            "test",
            "sorting",
            str(python_sort_executable),
            "--no-fixtures",
            "--random-cases",
            "3",
            "--maximum-size",
            "8",
            "--seed",
            "1",
        )

        assert result.exit_code == 0, result.stdout
        assert parse_table_rows(result.stdout) == [
            ["uniform", "1/1"],
            ["sorted", "1/1"],
            ["reversed", "1/1"],
        ]
        assert "python_sort.py: 3/3 cases passed" in result.stdout

    def test_case_runs_exactly_the_named_cases(self, python_sort_executable: Path) -> None:
        """Test the case option runs the named cases together with the chosen fixture."""
        result = invoke_cli(
            "test",
            "sorting",
            str(python_sort_executable),
            "--case",
            "fixture:empty",
            "--case",
            LARGE_CASE,
            "--fixture",
            "single",
        )

        assert result.exit_code == 0, result.stdout
        assert parse_table_rows(result.stdout) == [
            ["fixtures", "2/2"],
            ["uniform", "1/1"],
        ]

    @pytest.mark.parametrize(
        ("options", "message"),
        [
            (["--case", "fixture:nope"], "No fixture named 'nope'"),
            (["--fixture", "nope"], "No fixture named 'nope'"),
            (["--case", "nonsense"], "Unrecognized case identifier"),
            (["--case", "shrunk:fixture:empty"], "cannot be replayed"),
            (["--case", "generated:nope:size=1:seed=1"], "Unknown distribution 'nope'"),
            (["--distribution", "nope"], "Unknown distribution 'nope'"),
            (["--no-fixtures", "--random-cases", "0"], "no cases to run"),
            (["--case", "fixture:empty", "--random-cases", "3"], "cannot be combined with"),
            (["--fixture", "empty", "--distribution", "uniform"], "--distribution"),
            (["--case", "generated:uniform:size=05:seed=1"], "no valid 'size=N' part"),
            (["--case", "generated:uniform:size=+5:seed=1"], "no valid 'size=N' part"),
            (["--case", "generated:uniform:size=1_0:seed=1"], "no valid 'size=N' part"),
            (["--case", "generated:uniform:size=5:seed= 1"], "no valid 'seed=N' part"),
            (["--case", "generated:uniform:size=5:seed=001"], "no valid 'seed=N' part"),
        ],
    )
    def test_bad_case_options_are_usage_errors(
        self, python_sort_executable: Path, options: list[str], message: str
    ) -> None:
        """Test case options that name nothing valid are usage errors and run nothing."""
        result = invoke_cli("test", "sorting", str(python_sort_executable), *options)

        assert_exits_with(result, 2)
        assert message in result.stderr
        assert result.stdout == ""

    @pytest.mark.parametrize(
        ("options", "runs"),
        [
            (["--case", "fixture:single", "--case", "fixture:single"], 1),
            (["--fixture", "single", "--case", "fixture:single"], 1),
            (["--case", LARGE_CASE, "--case", LARGE_CASE, "--fixture", "empty"], 2),
        ],
        ids=["same case twice", "fixture and case", "generated twice"],
    )
    def test_a_case_named_twice_runs_once(
        self,
        use_fake_test_runners: UseFakeTestRunners,
        options: list[str],
        runs: int,
    ) -> None:
        """Test a case that is selected more than once is run once."""
        runners = use_fake_test_runners({"sorter": sorted})

        result = invoke_cli("test", "sorting", "--command", "sorter", *options)

        assert result.exit_code == 0, result.stdout + result.stderr
        assert len(runners.collect_inputs_of("sorter")) == runs


class TestFailureReport:
    @pytest.fixture(scope="class")
    def drops_last_result(self, drops_last_executable: Path) -> Result:
        """The result of testing the sorter that loses its last element on a large case."""
        return invoke_cli("test", "sorting", str(drops_last_executable), "--case", LARGE_CASE)

    @pytest.fixture
    def shrink_failure(
        self,
        use_fake_test_runners: UseFakeTestRunners,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> ReportRun:
        """Run a failing case of a problem whose shrink hook raises, writing a JSON report."""

        def explode(self: SortingProblem, input_data: list[int]) -> Iterator[list[int]]:
            raise RuntimeError("shrink exploded")

        monkeypatch.setattr(SortingProblem, "shrink", explode)
        use_fake_test_runners({"drops": drop_last_above_five})
        path = tmp_path / "report.json"
        result = invoke_cli(
            *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
            *["--json", str(path)],
        )
        return ReportRun(result, json.loads(path.read_text()))

    def test_a_failing_generated_case_is_described_with_a_window_around_the_difference(
        self, drops_last_result: Result
    ) -> None:
        """Test a failing generated case is named, explained, and its output compared."""
        output = drops_last_result.stdout

        assert drops_last_result.exit_code == 1, output
        assert f"FAIL drops_last.py on {LARGE_CASE}" in output
        assert "message: Output length 11 does not match input length 12" in output
        assert "input: [" in output
        # The windows are around the first difference, the missing last element.
        assert re.search(r"expected: \[\.\.\., -?\d+\] \(12 values, index 11 shown\)", output)
        assert re.search(r"actual: \[\.\.\., -?\d+\] \(11 values, index 10 shown\)", output)
        assert "drops_last.py: 0/1 cases passed" in output

    def test_a_failing_generated_case_is_shrunk_to_a_smaller_input(
        self, drops_last_result: Result
    ) -> None:
        """Test a failing generated case is reported again with its shrunk input."""
        output = drops_last_result.stdout

        assert "shrunk case:" not in output
        assert "shrink note" not in output
        assert "shrunk input: [0, 0, 0, 0, 0, 0]" in output
        assert "shrunk message: Output length 5 does not match input length 6" in output

    def test_a_failing_generated_case_is_reproducible_from_the_printed_command(
        self, drops_last_result: Result
    ) -> None:
        """Test running the printed reproduce command fails the same case again."""
        arguments = extract_reproduce_arguments(drops_last_result.stdout)

        again = invoke_cli(*arguments[1:], "--no-shrink")

        assert arguments[:3] == ["algorithm-playground", "test", "sorting"]
        assert again.exit_code == 1
        assert f"FAIL drops_last on {LARGE_CASE}" in again.stdout

    def test_a_failing_fixture_says_why_it_is_interesting(
        self, use_fake_test_runners: UseFakeTestRunners
    ) -> None:
        """Test the failure of a fixture is described with the reason for the fixture."""
        use_fake_test_runners({"unsorted": list})

        result = invoke_cli("test", "sorting", "--command", "unsorted", "--fixture", "two_unsorted")

        assert result.exit_code == 1
        assert "fixture: two elements out of order" in result.stdout

    def test_a_generated_failure_has_no_fixture_line(
        self, use_fake_test_runners: UseFakeTestRunners
    ) -> None:
        """Test the failure of a generated case has no fixture description."""
        use_fake_test_runners({"drops": drop_last_above_five})

        result = invoke_cli(
            "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
        )

        assert result.exit_code == 1
        assert "FAIL drops on generated:" in result.stdout
        assert "    fixture:" not in result.stdout

    def test_a_shrink_hook_that_raises_is_noted_in_the_report(
        self, shrink_failure: ReportRun
    ) -> None:
        """Test a shrink hook that raises is explained in the printed failure."""
        assert shrink_failure.result.exit_code == 1
        assert (
            "shrink note: the problem's shrink hook raised RuntimeError: shrink exploded"
            in shrink_failure.result.stdout
        )

    def test_a_shrink_hook_that_raises_is_noted_in_the_json(
        self, shrink_failure: ReportRun
    ) -> None:
        """Test a shrink hook that raises is recorded in the JSON report as a note."""
        (outcome,) = shrink_failure.report["implementations"][0]["outcomes"]

        assert outcome["shrink_note"] == (
            "the problem's shrink hook raised RuntimeError: shrink exploded"
        )
        assert outcome["shrunk"] is None

    def test_no_shrink_leaves_the_failure_unshrunk(self, drops_last_executable: Path) -> None:
        """Test the no-shrink option reports the failure without a shrunk input."""
        result = invoke_cli(
            "test", "sorting", str(drops_last_executable), "--case", LARGE_CASE, "--no-shrink"
        )

        assert result.exit_code == 1
        assert "shrunk" not in result.stdout

    def test_identical_error_messages_are_reported_once(self, crashing_executable: Path) -> None:
        """Test cases that fail with the same error share one message and list the cases."""
        result = invoke_cli(
            "test",
            "sorting",
            str(crashing_executable),
            "--fixture",
            "single",
            "--fixture",
            "empty",
            "--fixture",
            "two_sorted",
        )

        assert result.exit_code == 1
        assert result.stdout.count("exited with code 3") == 1
        assert result.stdout.count("kaboom") == 1
        assert "crashing.py: 3 of 3 cases did not pass" in result.stdout
        assert "same failure on: fixture:single, fixture:two_sorted" in result.stdout

    def test_failures_beyond_the_maximum_are_only_listed(
        self, use_fake_test_runners: UseFakeTestRunners
    ) -> None:
        """Test only the maximum number of failures is described in full."""

        def unsorted_or_short(values: list[int]) -> list[int]:
            return values[:-1] if len(values) > 5 else list(values)

        use_fake_test_runners({"mixed": unsorted_or_short})

        result = invoke_cli(
            "test",
            "sorting",
            *["--command", "mixed"],
            *["--fixture", "two_unsorted", "--fixture", "reverse_sorted"],
            *["--fixture", "duplicates"],
            "--maximum-failures",
            "1",
        )

        assert result.exit_code == 1
        assert result.stdout.count("FAIL mixed on") == 1
        assert "more failing cases are not described" in result.stdout

    def test_the_reproduce_command_carries_a_timeout_that_is_not_the_default(
        self, use_fake_test_runners: UseFakeTestRunners
    ) -> None:
        """Test the reproduce command repeats a timeout that differs from the default."""
        use_fake_test_runners({"drops": drop_last_above_five})

        result = invoke_cli(
            *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
            *["--timeout", "7.5", "--no-shrink"],
        )

        arguments = extract_reproduce_arguments(result.stdout)
        assert arguments[arguments.index("--timeout") + 1] == "7.5"
        assert arguments[-2:] == ["--case", LARGE_CASE]

    def test_the_reproduce_command_has_no_timeout_when_it_is_the_default(
        self, use_fake_test_runners: UseFakeTestRunners
    ) -> None:
        """Test the reproduce command leaves out the timeout when it has the default value."""
        use_fake_test_runners({"drops": drop_last_above_five})

        result = invoke_cli(
            "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
        )

        assert "--timeout" not in extract_reproduce_arguments(result.stdout)

    def test_the_reproduce_command_carries_every_option_that_changes_the_outcome(
        self,
        use_fake_test_runners: UseFakeTestRunners,
        tmp_path: Path,
    ) -> None:
        """Test the reproduce command repeats the options that affect how a case runs."""
        configuration = tmp_path / "reproduce.toml"
        configuration.write_text("")
        module = tmp_path / "reproduce_problem_module.py"
        module.write_text("VALUE = 1\n")
        use_fake_test_runners({"unsorted": list})

        result = invoke_cli(
            *["test", "sorting", "--command", "unsorted", "--fixture", "two_unsorted"],
            *["--inherit-environment", "--no-build"],
            *["--configuration", str(configuration), "--problem-module", str(module)],
        )

        arguments = extract_reproduce_arguments(result.stdout)
        assert "--inherit-environment" in arguments
        assert "--no-build" in arguments
        assert arguments[arguments.index("--configuration") + 1] == str(configuration)
        assert arguments[arguments.index("--problem-module") + 1] == str(module)

    def test_the_reproduce_command_names_a_configured_implementation(
        self,
        configure: Callable[..., Path],
        unsorted_output_executable: Path,
    ) -> None:
        """Test the reproduce command names a configured implementation instead of its command."""
        configure(
            "[[implementations]]\n"
            'name = "configured-unsorted"\n'
            'problem = "sorting"\n'
            f"command = {json.dumps([sys.executable, str(unsorted_output_executable)])}\n"
        )

        result = invoke_cli("test", "sorting", "--fixture", "two_unsorted")

        assert result.exit_code == 1
        assert "reproduce: algorithm-playground test sorting configured-unsorted --case" in (
            result.stdout
        )


class TestJsonReport:
    @pytest.fixture(scope="class")
    def explicit_cases_run(
        self,
        drops_last_executable: Path,
        python_sort_executable: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> ReportRun:
        """Run a correct and a failing sorter on a fixture and a large case, writing a report."""
        path = tmp_path_factory.mktemp("explicit") / "report.json"
        result = invoke_cli(
            "test",
            "sorting",
            str(python_sort_executable),
            str(drops_last_executable),
            "--fixture",
            "single",
            "--case",
            LARGE_CASE,
            "--no-shrink",
            "--json",
            str(path),
        )
        return ReportRun(result, json.loads(path.read_text()))

    def test_the_command_says_where_it_wrote_the_report(
        self, explicit_cases_run: ReportRun
    ) -> None:
        """Test the command exits with one for a failure and names the report it wrote."""
        assert explicit_cases_run.result.exit_code == 1
        assert "Wrote test report to" in explicit_cases_run.result.stdout

    def test_the_report_records_the_problem_the_settings_and_the_cases(
        self, explicit_cases_run: ReportRun
    ) -> None:
        """Test the report names the problem, whether it passed, the settings, and the cases."""
        report = explicit_cases_run.report

        assert report["report"] == "test"
        assert report["format_version"] == 2
        assert report["problem"] == "sorting"
        assert report["passed"] is False
        assert report["settings"]["cases"] == "explicit"
        assert report["settings"]["shrink"]["enabled"] is False
        assert report["cases"] == [
            {"identifier": "fixture:single", "kind": "fixture", "fixture": "single"},
            {
                "identifier": LARGE_CASE,
                "kind": "generated",
                "distribution": "uniform",
                "size": 12,
                "seed": 5,
            },
        ]

    def test_the_report_summarizes_each_implementation(
        self, explicit_cases_run: ReportRun, python_sort_executable: Path
    ) -> None:
        """Test the report gives each implementation its command, files, and summary."""
        good, bad = explicit_cases_run.report["implementations"]

        assert good["name"] == "python_sort.py"
        assert good["command"] == [str(python_sort_executable.resolve())]
        assert good["files"][0]["path"] == str(python_sort_executable.resolve())
        assert good["summary"] == {"passed": 2, "failed": 0, "errors": 0}
        assert bad["summary"] == {"passed": 1, "failed": 1, "errors": 0}

    def test_the_report_lists_the_outcome_of_every_case_with_the_failure_details(
        self, explicit_cases_run: ReportRun
    ) -> None:
        """Test the report holds an outcome per case, with the failure of the failing one."""
        _, bad = explicit_cases_run.report["implementations"]

        passing, failing = bad["outcomes"]

        assert passing["status"] == "passed" and passing["failure"] is None
        assert failing["case"] == LARGE_CASE
        assert failing["status"] == "failed"
        assert set(failing["failure"]) == {"input", "expected", "actual"}
        assert failing["shrunk"] is None

    def test_the_report_carries_the_host_and_metadata(self, explicit_cases_run: ReportRun) -> None:
        """Test the report describes the host and the run."""
        assert {"host", "metadata"} <= set(explicit_cases_run.report)

    def test_a_failed_build_is_recorded(self, python_sort_executable: Path, tmp_path: Path) -> None:
        """Test an implementation whose build failed is listed with the reason."""
        path = tmp_path / "report.json"
        configuration = tmp_path / "algorithm-playground.toml"
        configuration.write_text(
            "[[implementations]]\n"
            'name = "unbuildable"\n'
            'problem = "sorting"\n'
            f"command = {json.dumps([sys.executable, str(python_sort_executable)])}\n"
            f"build_command = {json.dumps([sys.executable, '-c', 'raise SystemExit(1)'])}\n"
        )

        result = invoke_cli(
            "test",
            "sorting",
            str(python_sort_executable),
            "unbuildable",
            "--configuration",
            str(configuration),
            "--fixture",
            "single",
            "--json",
            str(path),
        )

        assert result.exit_code == 1
        report = json.loads(path.read_text())
        assert report["passed"] is False
        assert [item["name"] for item in report["implementations"]] == [
            "python_sort.py",
            "unbuildable",
        ]
        assert "exited with code 1" in report["implementations"][1]["build_failure"]

    def test_planned_cases_are_recorded_with_the_settings_that_produced_them(
        self,
        use_fake_test_runners: UseFakeTestRunners,
        tmp_path: Path,
    ) -> None:
        """Test the report of planned cases records the options that planned them."""
        use_fake_test_runners({"sorter": sorted})
        path = tmp_path / "planned.json"

        result = invoke_cli(
            *["test", "sorting", "--command", "sorter"],
            *["--random-cases", "2", "--maximum-size", "6", "--seed", "3", "--no-fixtures"],
            *["--distribution", "sorted", "--timeout", "30", "--json", str(path)],
        )

        assert result.exit_code == 0, result.stdout
        settings = json.loads(path.read_text())["settings"]
        assert settings == {
            "cases": "planned",
            "seed": 3,
            "random_cases": 2,
            "maximum_size": 6,
            "distributions": ["sorted"],
            "include_fixtures": False,
            "shrink": {
                "enabled": True,
                "maximum_shrunk_cases": 3,
                "maximum_runs": 200,
                "time_budget_seconds": 30.0,
            },
            "timeout_seconds": 30.0,
        }


class TestJsonPath:
    @pytest.fixture
    def locked_directory(self, tmp_path: Path) -> Iterator[Path]:
        """A directory that cannot be written to; its permissions are restored afterwards."""
        directory = tmp_path / "locked"
        directory.mkdir()
        directory.chmod(0o500)
        yield directory
        directory.chmod(0o700)

    @pytest.mark.usefixtures("nothing_runs")
    def test_a_directory_is_refused_before_anything_runs(
        self, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test a directory given as the report path is a usage error and nothing runs."""
        result = invoke_cli("test", "sorting", str(python_sort_executable), "--json", str(tmp_path))

        assert_exits_with(result, 2)
        assert "is a directory" in result.stderr
        assert result.stdout == ""

    @pytest.mark.usefixtures("nothing_runs")
    def test_a_parent_that_is_a_file_is_refused_before_anything_runs(
        self, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test a report path below a file is a usage error and nothing runs."""
        blocker = tmp_path / "blocker"
        blocker.write_text("")

        result = invoke_cli(
            "test",
            "sorting",
            str(python_sort_executable),
            "--json",
            str(blocker / "sub" / "r.json"),
        )

        assert_exits_with(result, 2)
        assert "is not a directory" in result.stderr

    @pytest.mark.skipif(os.geteuid() == 0, reason="the superuser can write anywhere")
    @pytest.mark.usefixtures("nothing_runs")
    def test_a_directory_that_cannot_be_written_is_refused_before_anything_runs(
        self, python_sort_executable: Path, locked_directory: Path
    ) -> None:
        """Test a report path in a directory without write permission is a usage error."""
        result = invoke_cli(
            "test",
            "sorting",
            str(python_sort_executable),
            "--json",
            str(locked_directory / "r.json"),
        )

        assert_exits_with(result, 2)
        assert "permission denied" in result.stderr

    def test_missing_directories_are_created(
        self,
        use_fake_test_runners: UseFakeTestRunners,
        tmp_path: Path,
    ) -> None:
        """Test the directories above the report path are created when they are missing."""
        use_fake_test_runners({"sorter": sorted})
        path = tmp_path / "a" / "b" / "report.json"

        result = invoke_cli(
            *["test", "sorting", "--command", "sorter", "--fixture", "single"],
            *["--json", str(path)],
        )

        assert result.exit_code == 0, result.stdout
        assert json.loads(path.read_text())["problem"] == "sorting"

    def test_a_failure_while_writing_is_a_usage_error_not_a_traceback(
        self,
        use_fake_test_runners: UseFakeTestRunners,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test a report that cannot be written is reported as an error after the results."""
        use_fake_test_runners({"sorter": sorted})

        def refuse(self: Path, *arguments: object, **keywords: object) -> int:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(Path, "write_text", refuse)

        result = invoke_cli(
            *["test", "sorting", "--command", "sorter", "--fixture", "single"],
            *["--json", str(tmp_path / "full.json")],
        )

        assert_exits_with(result, 2)
        assert "Could not write the test report to" in result.stderr
        assert "No space left on device" in result.stderr
        assert "sorter: 1/1 cases passed" in result.stdout


class TestDebugCaseSelection:
    def test_case_replays_a_generated_input_exactly(
        self, recording_sorter: tuple[Path, Path]
    ) -> None:
        """Test the case option runs the input that the identifier generates."""
        script, log = recording_sorter
        identifier = "generated:uniform:size=4:seed=2"

        result = invoke_cli("debug", "sorting", str(script), "--case", identifier)

        assert result.exit_code == 0, result.stderr
        assert "Output verified." in result.stdout
        assert read_logged_inputs(log) == [resolve_case(SortingProblem(), identifier).input_data]

    def test_a_fixture_is_replayed_exactly(self, recording_sorter: tuple[Path, Path]) -> None:
        """Test the fixture option runs the input of the fixture."""
        script, log = recording_sorter

        result = invoke_cli("debug", "sorting", str(script), "--fixture", "duplicates")

        assert result.exit_code == 0, result.stderr
        assert read_logged_inputs(log) == [[3, 1, 4, 1, 5, 9, 2, 6, 5, 3]]

    def test_a_generated_input_draws_from_the_distribution_the_problem_prefers(
        self, recording_sorter: tuple[Path, Path]
    ) -> None:
        """Test debug generates a small-range input of the debug size by default."""
        script, log = recording_sorter

        result = invoke_cli("debug", "sorting", str(script), "--seed", "4")

        assert result.exit_code == 0, result.stderr
        (values,) = read_logged_inputs(log)
        assert len(values) == 16
        assert all(-10 <= value <= 10 for value in values)

    def test_a_distribution_and_a_size_can_be_chosen(
        self, recording_sorter: tuple[Path, Path]
    ) -> None:
        """Test the distribution and size options choose the generated input."""
        script, log = recording_sorter

        result = invoke_cli(
            "debug", "sorting", str(script), *["--distribution", "uniform", "--size", "9"]
        )

        assert result.exit_code == 0, result.stderr
        (values,) = read_logged_inputs(log)
        assert len(values) == 9
        assert any(abs(value) > 1000 for value in values)

    def test_an_unknown_distribution_is_a_usage_error(self, python_sort_executable: Path) -> None:
        """Test debug refuses a distribution the problem does not have."""
        result = invoke_cli(
            "debug", "sorting", str(python_sort_executable), "--distribution", "nope"
        )

        assert_exits_with(result, 2)
        assert "Unknown distribution 'nope'" in result.stderr

    @pytest.mark.parametrize(
        ("options", "message"),
        [
            (["--case", "fixture:nope"], "No fixture named 'nope'"),
            (["--fixture", "nope"], "No fixture named 'nope'"),
            (["--fixture", "empty", "--case", "fixture:empty"], "cannot be used together"),
        ],
    )
    def test_bad_options_are_usage_errors(
        self, python_sort_executable: Path, options: list[str], message: str
    ) -> None:
        """Test debug options that select no valid input are usage errors."""
        result = invoke_cli("debug", "sorting", str(python_sort_executable), *options)

        assert result.exit_code == 2
        assert message in result.stderr
