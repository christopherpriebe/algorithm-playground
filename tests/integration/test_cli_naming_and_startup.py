"""CLI tests for naming commands, for implementations that cannot be started, and for help."""

from __future__ import annotations

import json
import re
import shlex
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import FakeRunners, sort_correctly
from support import Invoke, TableRows, WriteExecutable, assert_exits_with

pytestmark = pytest.mark.integration

INSTRUMENTED_SORT = Path(__file__).resolve().parent.parent / "instrumented_sort.py"
SMALL = ["--sizes", "4,8", "--repetitions", "1", "--warmup", "0", "--no-plot"]


def instrumented(algorithm: str) -> str:
    return shlex.join([sys.executable, str(INSTRUMENTED_SORT), algorithm])


class TestCommandNames:
    def test_two_commands_running_one_script_are_told_apart_by_their_arguments(
        self, invoke: Invoke
    ) -> None:
        result = invoke(
            "benchmark",
            "sorting",
            *["--command", instrumented("insertion"), "--command", instrumented("merge")],
            *SMALL,
        )
        assert result.exit_code == 0, result.stdout
        header = next(line for line in result.stdout.splitlines() if line.startswith("┃"))
        assert "instrumented_sort insertion" in header and "instrumented_sort merge" in header

    def test_a_name_replaces_the_default_name_of_the_command_in_its_position(
        self, invoke: Invoke, use_fake_test_runners: Callable[..., FakeRunners]
    ) -> None:
        use_fake_test_runners({"quick": sort_correctly, "b": sort_correctly})
        result = invoke(
            "test",
            "sorting",
            "--command",
            "a",
            "--command",
            "b",
            "--name",
            "quick",
            "--fixture",
            "empty",
        )
        assert result.exit_code == 0, result.stdout
        assert "quick: 1/1 cases passed" in result.stdout
        assert "b: 1/1 cases passed" in result.stdout

    def test_names_pair_with_commands_in_order_in_every_command(
        self, invoke: Invoke, tmp_path: Path
    ) -> None:
        report = tmp_path / "report.json"
        result = invoke(
            "benchmark",
            "sorting",
            *["--command", instrumented("insertion"), "--command", instrumented("merge")],
            *["--name", "slow", "--name", "fast"],
            *SMALL,
            "--json",
            str(report),
        )
        assert result.exit_code == 0, result.stdout
        names = [item["name"] for item in json.loads(report.read_text())["implementations"]]
        assert names == ["slow", "fast"]

    def test_debug_accepts_a_name(self, invoke: Invoke) -> None:
        result = invoke(
            "debug",
            "sorting",
            "--command",
            instrumented("insertion"),
            "--name",
            "mine",
            "--size",
            "4",
        )
        assert result.exit_code == 0, result.stderr

    def test_more_names_than_commands_are_a_usage_error(self, invoke: Invoke) -> None:
        result = invoke("test", "sorting", "--command", "node a.js", "--name", "a", "--name", "b")
        assert_exits_with(result, 2)
        assert "--name was given 2 times, but there are only 1 --command values" in result.stderr
        assert result.stdout == ""

    def test_a_name_without_a_command_is_a_usage_error(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke("test", "sorting", str(python_sort_executable), "--name", "a")
        assert_exits_with(result, 2)
        assert "--name was given 1 times, but there are only 0 --command values" in result.stderr

    def test_the_same_name_twice_is_a_usage_error(self, invoke: Invoke) -> None:
        result = invoke(
            "test",
            "sorting",
            "--command",
            "node a.js",
            "--command",
            "node b.js",
            "--name",
            "same",
            "--name",
            "same",
        )
        assert_exits_with(result, 2)
        assert "'same'" in result.stderr


class TestCommandsThatCannotBeStarted:
    def test_the_other_implementations_run_and_the_matrix_says_cannot_run(
        self, invoke: Invoke, python_sort_executable: Path, table_rows: TableRows, tmp_path: Path
    ) -> None:
        missing = tmp_path / "missing_program"
        result = invoke(
            "test",
            "sorting",
            str(python_sort_executable),
            "--command",
            str(missing),
            "--name",
            "missing_program",
            "--fixture",
            "empty",
        )
        assert_exits_with(result, 1)
        rows = table_rows(result.stdout)
        assert rows[0] == ["fixtures", "1/1", "cannot run"]
        assert all(row[2] == "cannot run" for row in rows)
        assert f"Cannot run missing_program: command not found: {missing}" in result.stderr
        assert "missing_program: cannot run, not run" in result.stdout
        assert "did not pass" not in result.stdout

    def test_it_is_reported_once_and_no_case_is_run_for_it(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        result = invoke(
            "test",
            "sorting",
            str(python_sort_executable),
            "--command",
            str(tmp_path / "ghost"),
            "--name",
            "ghost",
            "--fixture",
            "empty",
        )
        assert result.stderr.count("Cannot run ghost") == 1
        assert "ERROR" not in result.stdout

    def test_a_script_without_the_executable_bit_is_permission_denied_once(
        self, invoke: Invoke, python_sort_executable: Path, plain_sort_script: Path
    ) -> None:
        result = invoke(
            "test",
            "sorting",
            str(python_sort_executable),
            str(plain_sort_script),
            "--fixture",
            "empty",
        )
        assert_exits_with(result, 1)
        assert "(permission denied)" in result.stderr and "chmod +x" in result.stderr
        assert result.stderr.count("permission denied") == 1

    def test_without_any_runnable_implementation_nothing_runs(
        self, invoke: Invoke, tmp_path: Path
    ) -> None:
        result = invoke("test", "sorting", "--command", str(tmp_path / "ghost"), "--name", "ghost")
        assert_exits_with(result, 1)
        assert "No implementation could be started, so nothing was run." in result.stderr
        assert result.stdout == ""

    def test_the_json_report_says_why(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        report = tmp_path / "report.json"
        result = invoke(
            "test",
            "sorting",
            str(python_sort_executable),
            "--command",
            str(tmp_path / "ghost"),
            "--name",
            "ghost",
            "--fixture",
            "empty",
            "--json",
            str(report),
        )
        assert result.exit_code == 1
        document = json.loads(report.read_text())
        good, ghost = document["implementations"]
        assert good["cannot_run"] is None
        assert ghost["cannot_run"] == f"command not found: {tmp_path / 'ghost'}"
        assert ghost["outcomes"] == [] and document["passed"] is False

    def test_the_benchmark_marks_it_failed_and_runs_the_others(
        self, invoke: Invoke, python_sort_executable: Path, table_rows: TableRows, tmp_path: Path
    ) -> None:
        report = tmp_path / "report.json"
        result = invoke(
            "benchmark",
            "sorting",
            str(python_sort_executable),
            "--command",
            str(tmp_path / "ghost"),
            "--name",
            "ghost",
            *SMALL,
            "--json",
            str(report),
        )
        assert_exits_with(result, 1)
        rows = table_rows(result.stdout)
        assert [row[0] for row in rows] == ["startup", "4", "8"]
        assert all(row[2] == "failed" for row in rows)
        assert f"Cannot run ghost: command not found: {tmp_path / 'ghost'}" in result.stderr
        ghost = json.loads(report.read_text())["implementations"][1]
        assert [failure["stage"] for failure in ghost["failures"]] == ["cannot run"]
        assert ghost["failures"][0]["message"].startswith("Cannot run: command not found")

    def test_debug_stops_before_running(self, invoke: Invoke, tmp_path: Path) -> None:
        result = invoke("debug", "sorting", "--command", str(tmp_path / "ghost"), "--name", "ghost")
        assert_exits_with(result, 1)
        assert "No implementation could be started, so nothing was run." in result.stderr

    def test_a_script_through_an_interpreter_passes_the_check(
        self, invoke: Invoke, plain_sort_script: Path
    ) -> None:
        command = shlex.join([sys.executable, str(plain_sort_script)])
        result = invoke("test", "sorting", "--command", command, "--fixture", "empty")
        assert result.exit_code == 0, result.stderr

    def test_a_program_that_is_there_after_the_build_passes(
        self,
        invoke: Invoke,
        configure: Callable[..., Path],
        write_executable: WriteExecutable,
        python_sort_executable: Path,
        tmp_path: Path,
    ) -> None:
        built = tmp_path / "built_program"
        configure(
            "[[implementations]]\n"
            'name = "built"\nproblem = "sorting"\n'
            f"command = {json.dumps([str(built)])}\n"
            f"build_command = {json.dumps([sys.executable, '-c', f'import shutil; shutil.copy({str(python_sort_executable)!r}, {str(built)!r}); import os; os.chmod({str(built)!r}, 0o755)'])}\n"
        )
        result = invoke("test", "sorting", "--fixture", "empty")
        assert result.exit_code == 0, result.stderr


class TestHelpAndErrors:
    @pytest.mark.parametrize("command", ["test", "benchmark", "debug", "list"])
    def test_arguments_are_shown_by_their_user_facing_names(
        self, invoke: Invoke, command: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("COLUMNS", "120")
        text = invoke(command, "--help").stdout
        panel = text[text.index("Arguments") : text.index("Options")]
        assert "problem_name" not in panel
        assert "selectors" not in panel
        assert "implementation_selector" not in panel
        assert "problem_name" not in text
        if command != "list":
            assert "PROBLEM" in panel
        assert ("[IMPLEMENTATION]" in panel) or command == "list"

    def test_the_usage_line_is_unchanged(self, invoke: Invoke) -> None:
        # Typer 0.27 and later put the braces of a required argument around its metavar.
        usage = re.compile(r"test \[OPTIONS\] \{?PROBLEM\}? \[IMPLEMENTATION\]\.\.\.")
        assert usage.search(invoke("test", "--help").stdout)

    def test_an_arguments_default_name_still_binds_the_value(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke("test", "sorting", str(python_sort_executable), "--fixture", "empty")
        assert result.exit_code == 0, result.stdout

    def test_an_unknown_option_suggests_a_close_one_without_a_tuple(self, invoke: Invoke) -> None:
        result = invoke("test", "sorting", "--verbos")
        assert result.exit_code == 2
        assert "No such option: --verbos. Did you mean --verbose?" in result.stderr
        assert "('" not in result.stderr and "',)" not in result.stderr

    def test_an_unknown_option_without_a_suggestion_is_plain(self, invoke: Invoke) -> None:
        result = invoke("benchmark", "sorting", "--zzzzzzzz")
        assert result.exit_code == 2
        assert "No such option: --zzzzzzzz." in result.stderr
        assert "Did you mean" not in result.stderr

    def test_a_missing_argument_is_still_named_by_its_metavar(self, invoke: Invoke) -> None:
        result = invoke("test")
        assert result.exit_code == 2
        assert "Missing argument 'PROBLEM'" in result.stderr


class TestListShowsInputFiles:
    def test_sorting_can_read_its_input_files(self, invoke: Invoke) -> None:
        assert "Input files: readable" in invoke("list", "sorting").stdout

    def test_a_problem_that_cannot_says_so(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from algorithm_playground.core.problem import Problem
        from algorithm_playground.problems.sorting import SortingProblem

        monkeypatch.setattr(SortingProblem, "deserialize_input", Problem.deserialize_input)
        text = invoke("list", "sorting").stdout
        assert "Input files: the problem does not implement deserialize_input" in text
