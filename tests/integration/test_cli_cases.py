"""End-to-end CLI tests for case selection, failure reports, shrinking, and the JSON report.

Runs use tiny inputs and few cases; the engine's own behavior is covered in-process.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fakes import FakeRunners, drop_last_above_five
from support import Invoke, TableRows, assert_exits_with, logged_inputs

from algorithm_playground.cli import test_command
from algorithm_playground.core.cases import resolve_case
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration


LARGE_CASE = "generated:uniform:size=12:seed=5"


@pytest.fixture
def nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if the engine is started: the command must have stopped before that."""

    def refuse(*arguments: object, **keywords: object) -> None:
        raise AssertionError("the test engine must not run")

    monkeypatch.setattr(test_command, "run_tests", refuse)


class TestCaseSelection:
    def test_generated_cases_are_summarized_per_distribution(
        self, invoke: Invoke, table_rows: TableRows, python_sort_executable: Path
    ) -> None:
        result = invoke(
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
        assert table_rows(result.stdout) == [
            ["uniform", "1/1"],
            ["sorted", "1/1"],
            ["reversed", "1/1"],
        ]
        assert "python_sort.py: 3/3 cases passed" in result.stdout

    def test_case_runs_exactly_the_named_cases(
        self, invoke: Invoke, table_rows: TableRows, python_sort_executable: Path
    ) -> None:
        result = invoke(
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
        assert table_rows(result.stdout) == [
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
        self, invoke: Invoke, python_sort_executable: Path, options: list[str], message: str
    ) -> None:
        result = invoke("test", "sorting", str(python_sort_executable), *options)
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
        invoke: Invoke,
        use_fake_test_runners: Callable[..., FakeRunners],
        options: list[str],
        runs: int,
    ) -> None:
        runners = use_fake_test_runners({"sorter": sorted})
        result = invoke("test", "sorting", "--command", "sorter", *options)
        assert result.exit_code == 0, result.stdout + result.stderr
        assert len(runners.inputs_of("sorter")) == runs


class TestFailureReport:
    def test_a_failing_generated_case_is_described_shrunk_and_reproducible(
        self, invoke: Invoke, drops_last_executable: Path
    ) -> None:
        result = invoke("test", "sorting", str(drops_last_executable), "--case", LARGE_CASE)
        assert result.exit_code == 1, result.stdout
        output = result.stdout
        assert f"FAIL drops_last.py on {LARGE_CASE}" in output
        assert "message: Output length 11 does not match input length 12" in output
        assert "input: [" in output
        # The windows are around the first difference, the missing last element.
        assert re.search(r"expected: \[\.\.\., -?\d+\] \(12 values, index 11 shown\)", output)
        assert re.search(r"actual: \[\.\.\., -?\d+\] \(11 values, index 10 shown\)", output)
        assert "shrunk case:" not in output
        assert "shrink note" not in output
        assert "shrunk input: [0, 0, 0, 0, 0, 0]" in output
        assert "shrunk message: Output length 5 does not match input length 6" in output
        assert "drops_last.py: 0/1 cases passed" in output

        reproduce = next(
            line.strip().removeprefix("reproduce: ")
            for line in output.splitlines()
            if line.strip().startswith("reproduce: ")
        )
        arguments = shlex.split(reproduce)
        assert arguments[:3] == ["algorithm-playground", "test", "sorting"]
        again = invoke(*arguments[1:], "--no-shrink")
        assert again.exit_code == 1
        assert f"FAIL drops_last on {LARGE_CASE}" in again.stdout

    def test_a_failing_fixture_says_why_it_is_interesting(
        self, invoke: Invoke, use_fake_test_runners: Callable[..., FakeRunners]
    ) -> None:
        use_fake_test_runners({"unsorted": list})
        result = invoke("test", "sorting", "--command", "unsorted", "--fixture", "two_unsorted")
        assert result.exit_code == 1
        assert "fixture: two elements out of order" in result.stdout

    def test_a_generated_failure_has_no_fixture_line(
        self, invoke: Invoke, use_fake_test_runners: Callable[..., FakeRunners]
    ) -> None:
        use_fake_test_runners({"drops": drop_last_above_five})
        result = invoke(
            "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
        )
        assert result.exit_code == 1
        assert "FAIL drops on generated:" in result.stdout
        assert "    fixture:" not in result.stdout

    def test_a_shrink_hook_that_raises_is_noted_in_the_report_and_the_json(
        self,
        invoke: Invoke,
        use_fake_test_runners: Callable[..., FakeRunners],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        def explode(self: SortingProblem, input_data: list[int]) -> Iterator[list[int]]:
            raise RuntimeError("shrink exploded")

        monkeypatch.setattr(SortingProblem, "shrink", explode)
        use_fake_test_runners({"drops": drop_last_above_five})
        path = tmp_path / "report.json"
        result = invoke(
            *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
            *["--json", str(path)],
        )
        assert result.exit_code == 1
        assert (
            "shrink note: the problem's shrink hook raised RuntimeError: shrink exploded"
            in result.stdout
        )
        (outcome,) = json.loads(path.read_text())["implementations"][0]["outcomes"]
        assert outcome["shrink_note"] == (
            "the problem's shrink hook raised RuntimeError: shrink exploded"
        )
        assert outcome["shrunk"] is None

    def test_no_shrink_leaves_the_failure_unshrunk(
        self, invoke: Invoke, drops_last_executable: Path
    ) -> None:
        result = invoke(
            "test", "sorting", str(drops_last_executable), "--case", LARGE_CASE, "--no-shrink"
        )
        assert result.exit_code == 1
        assert "shrunk" not in result.stdout

    def test_identical_error_messages_are_reported_once(
        self, invoke: Invoke, crashing_executable: Path
    ) -> None:
        result = invoke(
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
        self, invoke: Invoke, use_fake_test_runners: Callable[..., FakeRunners]
    ) -> None:
        def unsorted_or_short(values: list[int]) -> list[int]:
            return values[:-1] if len(values) > 5 else list(values)

        use_fake_test_runners({"mixed": unsorted_or_short})
        result = invoke(
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

    def reproduce_command(self, output: str) -> list[str]:
        line = next(
            line.strip().removeprefix("reproduce: ")
            for line in output.splitlines()
            if line.strip().startswith("reproduce: ")
        )
        return shlex.split(line)

    def test_the_reproduce_command_carries_a_timeout_that_is_not_the_default(
        self, invoke: Invoke, use_fake_test_runners: Callable[..., FakeRunners]
    ) -> None:
        use_fake_test_runners({"drops": drop_last_above_five})
        result = invoke(
            *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
            *["--timeout", "7.5", "--no-shrink"],
        )
        arguments = self.reproduce_command(result.stdout)
        assert arguments[arguments.index("--timeout") + 1] == "7.5"
        assert arguments[-2:] == ["--case", LARGE_CASE]

    def test_the_reproduce_command_has_no_timeout_when_it_is_the_default(
        self, invoke: Invoke, use_fake_test_runners: Callable[..., FakeRunners]
    ) -> None:
        use_fake_test_runners({"drops": drop_last_above_five})
        result = invoke(
            "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
        )
        assert "--timeout" not in self.reproduce_command(result.stdout)

    def test_the_reproduce_command_carries_every_option_that_changes_the_outcome(
        self,
        invoke: Invoke,
        use_fake_test_runners: Callable[..., FakeRunners],
        tmp_path: Path,
    ) -> None:
        configuration = tmp_path / "reproduce.toml"
        configuration.write_text("")
        module = tmp_path / "reproduce_problem_module.py"
        module.write_text("VALUE = 1\n")
        use_fake_test_runners({"unsorted": list})
        result = invoke(
            *["test", "sorting", "--command", "unsorted", "--fixture", "two_unsorted"],
            *["--inherit-environment", "--no-build"],
            *["--configuration", str(configuration), "--problem-module", str(module)],
        )
        arguments = self.reproduce_command(result.stdout)
        assert "--inherit-environment" in arguments
        assert "--no-build" in arguments
        assert arguments[arguments.index("--configuration") + 1] == str(configuration)
        assert arguments[arguments.index("--problem-module") + 1] == str(module)

    def test_the_reproduce_command_names_a_configured_implementation(
        self,
        invoke: Invoke,
        configure: Callable[..., Path],
        unsorted_output_executable: Path,
    ) -> None:
        configure(
            "[[implementations]]\n"
            'name = "configured-unsorted"\n'
            'problem = "sorting"\n'
            f"command = {json.dumps([sys.executable, str(unsorted_output_executable)])}\n"
        )
        result = invoke("test", "sorting", "--fixture", "two_unsorted")
        assert result.exit_code == 1
        assert "reproduce: algorithm-playground test sorting configured-unsorted --case" in (
            result.stdout
        )


class TestJsonReport:
    def test_the_report_lists_cases_outcomes_failures_and_shrunk_inputs(
        self,
        invoke: Invoke,
        drops_last_executable: Path,
        python_sort_executable: Path,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "report.json"
        result = invoke(
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
        assert result.exit_code == 1
        assert "Wrote test report to" in result.stdout
        report = json.loads(path.read_text())
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
        good, bad = report["implementations"]
        assert good["name"] == "python_sort.py"
        assert good["command"] == [str(python_sort_executable.resolve())]
        assert good["files"][0]["path"] == str(python_sort_executable.resolve())
        assert good["summary"] == {"passed": 2, "failed": 0, "errors": 0}
        assert bad["summary"] == {"passed": 1, "failed": 1, "errors": 0}
        passing, failing = bad["outcomes"]
        assert passing["status"] == "passed" and passing["failure"] is None
        assert failing["case"] == LARGE_CASE
        assert failing["status"] == "failed"
        assert set(failing["failure"]) == {"input", "expected", "actual"}
        assert failing["shrunk"] is None
        assert {"host", "metadata"} <= set(report)

    def test_a_failed_build_is_recorded(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        path = tmp_path / "report.json"
        configuration = tmp_path / "algorithm-playground.toml"
        configuration.write_text(
            "[[implementations]]\n"
            'name = "unbuildable"\n'
            'problem = "sorting"\n'
            f"command = {json.dumps([sys.executable, str(python_sort_executable)])}\n"
            f"build_command = {json.dumps([sys.executable, '-c', 'raise SystemExit(1)'])}\n"
        )
        result = invoke(
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
        invoke: Invoke,
        use_fake_test_runners: Callable[..., FakeRunners],
        tmp_path: Path,
    ) -> None:
        use_fake_test_runners({"sorter": sorted})
        path = tmp_path / "planned.json"
        result = invoke(
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
    def test_a_directory_is_refused_before_anything_runs(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path, nothing_runs: None
    ) -> None:
        result = invoke("test", "sorting", str(python_sort_executable), "--json", str(tmp_path))
        assert_exits_with(result, 2)
        assert "is a directory" in result.stderr
        assert result.stdout == ""

    def test_a_parent_that_is_a_file_is_refused_before_anything_runs(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path, nothing_runs: None
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("")
        result = invoke(
            "test",
            "sorting",
            str(python_sort_executable),
            "--json",
            str(blocker / "sub" / "r.json"),
        )
        assert_exits_with(result, 2)
        assert "is not a directory" in result.stderr

    @pytest.mark.skipif(os.geteuid() == 0, reason="the superuser can write anywhere")
    def test_a_directory_that_cannot_be_written_is_refused_before_anything_runs(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path, nothing_runs: None
    ) -> None:
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            result = invoke(
                "test", "sorting", str(python_sort_executable), "--json", str(locked / "r.json")
            )
        finally:
            locked.chmod(0o700)
        assert_exits_with(result, 2)
        assert "permission denied" in result.stderr

    def test_missing_directories_are_created(
        self,
        invoke: Invoke,
        use_fake_test_runners: Callable[..., FakeRunners],
        tmp_path: Path,
    ) -> None:
        use_fake_test_runners({"sorter": sorted})
        path = tmp_path / "a" / "b" / "report.json"
        result = invoke(
            *["test", "sorting", "--command", "sorter", "--fixture", "single"],
            *["--json", str(path)],
        )
        assert result.exit_code == 0, result.stdout
        assert json.loads(path.read_text())["problem"] == "sorting"

    def test_a_failure_while_writing_is_a_usage_error_not_a_traceback(
        self,
        invoke: Invoke,
        use_fake_test_runners: Callable[..., FakeRunners],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        use_fake_test_runners({"sorter": sorted})

        def refuse(self: Path, *arguments: object, **keywords: object) -> int:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(Path, "write_text", refuse)
        result = invoke(
            *["test", "sorting", "--command", "sorter", "--fixture", "single"],
            *["--json", str(tmp_path / "full.json")],
        )
        assert_exits_with(result, 2)
        assert "Could not write the test report to" in result.stderr
        assert "No space left on device" in result.stderr
        assert "sorter: 1/1 cases passed" in result.stdout


class TestDebugCaseSelection:
    def test_case_replays_a_generated_input_exactly(
        self, invoke: Invoke, recording_sorter: tuple[Path, Path]
    ) -> None:
        script, log = recording_sorter
        identifier = "generated:uniform:size=4:seed=2"
        result = invoke("debug", "sorting", str(script), "--case", identifier)
        assert result.exit_code == 0, result.stderr
        assert "Output verified." in result.stdout
        assert logged_inputs(log) == [resolve_case(SortingProblem(), identifier).input_data]

    def test_a_fixture_is_replayed_exactly(
        self, invoke: Invoke, recording_sorter: tuple[Path, Path]
    ) -> None:
        script, log = recording_sorter
        result = invoke("debug", "sorting", str(script), "--fixture", "duplicates")
        assert result.exit_code == 0, result.stderr
        assert logged_inputs(log) == [[3, 1, 4, 1, 5, 9, 2, 6, 5, 3]]

    def test_a_generated_input_draws_from_the_distribution_the_problem_prefers(
        self, invoke: Invoke, recording_sorter: tuple[Path, Path]
    ) -> None:
        script, log = recording_sorter
        result = invoke("debug", "sorting", str(script), "--seed", "4")
        assert result.exit_code == 0, result.stderr
        (values,) = logged_inputs(log)
        assert len(values) == 16
        assert all(-10 <= value <= 10 for value in values)

    def test_a_distribution_and_a_size_can_be_chosen(
        self, invoke: Invoke, recording_sorter: tuple[Path, Path]
    ) -> None:
        script, log = recording_sorter
        result = invoke(
            "debug", "sorting", str(script), *["--distribution", "uniform", "--size", "9"]
        )
        assert result.exit_code == 0, result.stderr
        (values,) = logged_inputs(log)
        assert len(values) == 9
        assert any(abs(value) > 1000 for value in values)

    def test_an_unknown_distribution_is_a_usage_error(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke("debug", "sorting", str(python_sort_executable), "--distribution", "nope")
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
        self, invoke: Invoke, python_sort_executable: Path, options: list[str], message: str
    ) -> None:
        result = invoke("debug", "sorting", str(python_sort_executable), *options)
        assert result.exit_code == 2
        assert message in result.stderr
