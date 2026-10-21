"""CLI tests for naming commands, for implementations that cannot be started, and for help."""

import json
import re
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from helpers.fakes import FakeRunners, sort_correctly
from helpers.support import (
    Configure,
    assert_exits_with,
    find_table_header,
    invoke_cli,
    parse_table_rows,
)
from typer.testing import Result

from algorithm_playground.core.problem import Problem
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

INSTRUMENTED_SORT = Path(__file__).resolve().parent.parent / "helpers" / "instrumented_sort.py"
SMALL = ["--sizes", "4,8", "--repetitions", "1", "--warmup", "0", "--no-plot"]


class MissingProgramRun(NamedTuple):
    """The outcome of testing a working sorter next to a command that does not exist."""

    result: Result
    missing: Path


def build_instrumented_command(algorithm: str) -> str:
    """Build the command line that runs an instrumented sorter of the given algorithm."""
    return shlex.join([sys.executable, str(INSTRUMENTED_SORT), algorithm])


class TestCommandNames:
    def test_two_commands_running_one_script_are_told_apart_by_their_arguments(self) -> None:
        """Test commands that run the same script are named after their arguments too."""
        result = invoke_cli(
            "benchmark",
            "sorting",
            *[
                "--command",
                build_instrumented_command("insertion"),
                "--command",
                build_instrumented_command("merge"),
            ],
            *SMALL,
        )

        assert result.exit_code == 0, result.stdout
        header = find_table_header(result.stdout)
        assert "instrumented_sort insertion" in header and "instrumented_sort merge" in header

    def test_a_name_replaces_the_default_name_of_the_command_in_its_position(
        self, use_fake_test_runners: Callable[..., FakeRunners]
    ) -> None:
        """Test a name given with the name option replaces the default name of its command."""
        use_fake_test_runners({"quick": sort_correctly, "second": sort_correctly})

        result = invoke_cli(
            "test",
            "sorting",
            "--command",
            "first",
            "--command",
            "second",
            "--name",
            "quick",
            "--fixture",
            "empty",
        )

        assert result.exit_code == 0, result.stdout
        assert "quick: 1/1 cases passed" in result.stdout
        assert "second: 1/1 cases passed" in result.stdout

    def test_names_pair_with_commands_in_order_in_every_command(self, tmp_path: Path) -> None:
        """Test names are matched to commands in the order they are given, in the report."""
        report = tmp_path / "report.json"

        result = invoke_cli(
            "benchmark",
            "sorting",
            *[
                "--command",
                build_instrumented_command("insertion"),
                "--command",
                build_instrumented_command("merge"),
            ],
            *["--name", "slow", "--name", "fast"],
            *SMALL,
            "--json",
            str(report),
        )

        assert result.exit_code == 0, result.stdout
        names = [item["name"] for item in json.loads(report.read_text())["implementations"]]
        assert names == ["slow", "fast"]

    def test_debug_accepts_a_name(self) -> None:
        """Test the debug command accepts the name option."""
        result = invoke_cli(
            "debug",
            "sorting",
            "--command",
            build_instrumented_command("insertion"),
            "--name",
            "mine",
            "--size",
            "4",
        )

        assert result.exit_code == 0, result.stderr

    def test_more_names_than_commands_are_a_usage_error(self) -> None:
        """Test giving more names than commands is a usage error."""
        result = invoke_cli(
            "test", "sorting", "--command", "node first.js", "--name", "first", "--name", "second"
        )

        assert_exits_with(result, 2)
        assert "--name was given 2 times, but there are only 1 --command values" in result.stderr
        assert result.stdout == ""

    def test_a_name_without_a_command_is_a_usage_error(self, python_sort_executable: Path) -> None:
        """Test a name given without any command is a usage error."""
        result = invoke_cli("test", "sorting", str(python_sort_executable), "--name", "first")

        assert_exits_with(result, 2)
        assert "--name was given 1 times, but there are only 0 --command values" in result.stderr

    def test_the_same_name_twice_is_a_usage_error(self) -> None:
        """Test two commands cannot be given the same name."""
        result = invoke_cli(
            "test",
            "sorting",
            "--command",
            "node first.js",
            "--command",
            "node second.js",
            "--name",
            "same",
            "--name",
            "same",
        )

        assert_exits_with(result, 2)
        assert "'same'" in result.stderr


class TestCommandsThatCannotBeStarted:
    @pytest.fixture
    def missing_program_run(
        self, python_sort_executable: Path, tmp_path: Path
    ) -> MissingProgramRun:
        """Run a working sorter and a command that does not exist on one fixture."""
        missing = tmp_path / "missing_program"
        result = invoke_cli(
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
        return MissingProgramRun(result, missing)

    def test_the_matrix_says_the_missing_command_cannot_run(
        self, missing_program_run: MissingProgramRun
    ) -> None:
        """Test the matrix marks a command that cannot be started and the command fails."""
        result = missing_program_run.result

        assert_exits_with(result, 1)
        rows = parse_table_rows(result.stdout)
        assert rows[0] == ["fixtures", "1/1", "cannot run"]
        assert all(row[2] == "cannot run" for row in rows)

    def test_the_other_implementations_run_and_the_missing_command_is_explained(
        self, missing_program_run: MissingProgramRun
    ) -> None:
        """Test the reason is printed and the summary says the command was not run."""
        result = missing_program_run.result

        assert (
            f"Cannot run missing_program: command not found: {missing_program_run.missing}"
            in result.stderr
        )
        assert "missing_program: cannot run, not run" in result.stdout
        assert "did not pass" not in result.stdout

    def test_it_is_reported_once_and_no_case_is_run_for_it(
        self, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test a command that cannot be started is reported once and shows no case errors."""
        result = invoke_cli(
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
        self, python_sort_executable: Path, plain_sort_script: Path
    ) -> None:
        """Test a script that is not executable is reported once with a hint to make it so."""
        result = invoke_cli(
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

    def test_without_any_runnable_implementation_nothing_runs(self, tmp_path: Path) -> None:
        """Test no case is run when no implementation could be started."""
        result = invoke_cli(
            "test", "sorting", "--command", str(tmp_path / "ghost"), "--name", "ghost"
        )

        assert_exits_with(result, 1)
        assert "No implementation could be started, so nothing was run." in result.stderr
        assert result.stdout == ""

    def test_the_json_report_says_why(self, python_sort_executable: Path, tmp_path: Path) -> None:
        """Test the JSON report gives the reason a command could not run."""
        report = tmp_path / "report.json"

        result = invoke_cli(
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
        self, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test the benchmark fails the command that cannot start and measures the others."""
        report = tmp_path / "report.json"

        result = invoke_cli(
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
        rows = parse_table_rows(result.stdout)
        assert [row[0] for row in rows] == ["startup", "4", "8"]
        assert all(row[2] == "failed" for row in rows)
        assert f"Cannot run ghost: command not found: {tmp_path / 'ghost'}" in result.stderr
        ghost = json.loads(report.read_text())["implementations"][1]
        assert [failure["stage"] for failure in ghost["failures"]] == ["cannot run"]
        assert ghost["failures"][0]["message"].startswith("Cannot run: command not found")

    def test_debug_stops_before_running(self, tmp_path: Path) -> None:
        """Test debug stops, without running, when the command cannot be started."""
        result = invoke_cli(
            "debug", "sorting", "--command", str(tmp_path / "ghost"), "--name", "ghost"
        )

        assert_exits_with(result, 1)
        assert "No implementation could be started, so nothing was run." in result.stderr

    def test_a_script_through_an_interpreter_passes_the_check(
        self, plain_sort_script: Path
    ) -> None:
        """Test a script that is started through an interpreter passes the startup check."""
        command = shlex.join([sys.executable, str(plain_sort_script)])

        result = invoke_cli("test", "sorting", "--command", command, "--fixture", "empty")

        assert result.exit_code == 0, result.stderr

    def test_a_program_that_is_there_after_the_build_passes(
        self,
        configure: Configure,
        python_sort_executable: Path,
        tmp_path: Path,
    ) -> None:
        """Test the startup check runs after the build, so a program the build makes is found."""
        built = tmp_path / "built_program"
        build_script = (
            "import os, shutil; "
            f"shutil.copy({str(python_sort_executable)!r}, {str(built)!r}); "
            f"os.chmod({str(built)!r}, 0o755)"
        )
        configure(
            "[[implementations]]\n"
            'name = "built"\nproblem = "sorting"\n'
            f"command = {json.dumps([str(built)])}\n"
            f"build_command = {json.dumps([sys.executable, '-c', build_script])}\n"
        )

        result = invoke_cli("test", "sorting", "--fixture", "empty")

        assert result.exit_code == 0, result.stderr


class TestHelpAndErrors:
    @pytest.fixture
    def help_panel_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make the terminal wide enough for the help panels to keep their lines."""
        monkeypatch.setenv("COLUMNS", "120")

    @pytest.mark.usefixtures("help_panel_terminal")
    @pytest.mark.parametrize("command", ["test", "benchmark", "debug", "list"])
    def test_arguments_are_shown_by_their_user_facing_names(self, command: str) -> None:
        """Test the help of a command does not show the internal names of its arguments."""
        text = invoke_cli(command, "--help").stdout

        panel = text[text.index("Arguments") : text.index("Options")]
        assert "problem_name" not in panel
        assert "selectors" not in panel
        assert "implementation_selector" not in panel
        assert "problem_name" not in text

    @pytest.mark.usefixtures("help_panel_terminal")
    @pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
    def test_the_problem_and_implementation_arguments_are_shown_by_their_metavars(
        self, command: str
    ) -> None:
        """Test the help of a command shows its problem and implementation arguments."""
        text = invoke_cli(command, "--help").stdout

        panel = text[text.index("Arguments") : text.index("Options")]
        assert "PROBLEM" in panel
        assert "[IMPLEMENTATION]" in panel

    def test_the_usage_line_is_unchanged(self) -> None:
        """Test the usage line of the test command shows its arguments as before."""
        # Typer 0.27 and later put the braces of a required argument around its metavar.
        usage = re.compile(r"test \[OPTIONS\] \{?PROBLEM\}? \[IMPLEMENTATION\]\.\.\.")

        assert usage.search(invoke_cli("test", "--help").stdout)

    def test_an_arguments_default_name_still_binds_the_value(
        self, python_sort_executable: Path
    ) -> None:
        """Test arguments given by position reach the command despite their display names."""
        result = invoke_cli("test", "sorting", str(python_sort_executable), "--fixture", "empty")

        assert result.exit_code == 0, result.stdout

    def test_an_unknown_option_suggests_a_close_one_without_a_tuple(self) -> None:
        """Test an unknown option that is close to a known one suggests it as plain text."""
        result = invoke_cli("test", "sorting", "--verbos")

        assert result.exit_code == 2
        assert "No such option: --verbos. Did you mean --verbose?" in result.stderr
        assert "('" not in result.stderr and "',)" not in result.stderr

    def test_an_unknown_option_without_a_suggestion_is_plain(self) -> None:
        """Test an unknown option that is close to no known one gets no suggestion."""
        result = invoke_cli("benchmark", "sorting", "--zzzzzzzz")

        assert result.exit_code == 2
        assert "No such option: --zzzzzzzz." in result.stderr
        assert "Did you mean" not in result.stderr

    def test_a_missing_argument_is_still_named_by_its_metavar(self) -> None:
        """Test a missing required argument is named by its metavar."""
        result = invoke_cli("test")

        assert result.exit_code == 2
        assert "Missing argument 'PROBLEM'" in result.stderr


class TestListShowsInputFiles:
    def test_sorting_can_read_its_input_files(self) -> None:
        """Test list says that the sorting problem can read input files."""
        assert "Input files: readable" in invoke_cli("list", "sorting").stdout

    def test_a_problem_that_cannot_says_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test list says that a problem without a way to read input files cannot read them."""
        monkeypatch.setattr(SortingProblem, "deserialize_input", Problem.deserialize_input)

        text = invoke_cli("list", "sorting").stdout

        assert "Input files: the problem does not implement deserialize_input" in text
