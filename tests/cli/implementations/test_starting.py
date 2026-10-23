"""Tests for implementations that cannot be started, timeouts, and temporary files."""

import json
import shlex
import sys
from pathlib import Path
from typing import NamedTuple

import pytest
from typer.testing import Result

from helpers.support import (
    Configure,
    assert_exits_with,
    invoke_cli,
    parse_table_rows,
)

pytestmark = pytest.mark.integration


SMALL = ["--sizes", "4,8", "--repetitions", "1", "--warmup", "0", "--no-plot"]


class MissingProgramRun(NamedTuple):
    """The outcome of testing a working sorter next to a command that does not exist."""

    result: Result
    missing: Path


@pytest.fixture
def missing_program_run(
    python_sort_executable: Path, tmp_path: Path
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
    missing_program_run: MissingProgramRun,
) -> None:
    """Test the matrix marks a command that cannot be started and the command fails."""
    result = missing_program_run.result

    assert_exits_with(result, 1)
    rows = parse_table_rows(result.stdout)
    assert rows[0] == ["fixtures", "1/1", "cannot run"]
    assert all(row[2] == "cannot run" for row in rows)


def test_the_other_implementations_run_and_the_missing_command_is_explained(
    missing_program_run: MissingProgramRun,
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
    python_sort_executable: Path, tmp_path: Path
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
    python_sort_executable: Path, plain_sort_script: Path
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
    assert "(permission denied)" in result.stderr
    assert "chmod +x" in result.stderr
    assert result.stderr.count("permission denied") == 1


def test_without_any_runnable_implementation_nothing_runs(tmp_path: Path) -> None:
    """Test no case is run when no implementation could be started."""
    result = invoke_cli(
        "test", "sorting", "--command", str(tmp_path / "ghost"), "--name", "ghost"
    )

    assert_exits_with(result, 1)
    assert "No implementation could be started, so nothing was run." in result.stderr
    assert result.stdout == ""


def test_the_json_report_says_why(python_sort_executable: Path, tmp_path: Path) -> None:
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
    assert ghost["outcomes"] == []
    assert document["passed"] is False


def test_the_benchmark_marks_it_failed_and_runs_the_others(
    python_sort_executable: Path, tmp_path: Path
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


def test_debug_stops_before_running(tmp_path: Path) -> None:
    """Test debug stops, without running, when the command cannot be started."""
    result = invoke_cli(
        "debug", "sorting", "--command", str(tmp_path / "ghost"), "--name", "ghost"
    )

    assert_exits_with(result, 1)
    assert "No implementation could be started, so nothing was run." in result.stderr


def test_a_script_through_an_interpreter_passes_the_check(
    plain_sort_script: Path,
) -> None:
    """Test a script that is started through an interpreter passes the startup check."""
    command = shlex.join([sys.executable, str(plain_sort_script)])

    result = invoke_cli("test", "sorting", "--command", command, "--fixture", "empty")

    assert result.exit_code == 0, result.stderr


def test_a_program_that_is_there_after_the_build_passes(
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


@pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_timeouts_are_usage_errors(
    python_sort_executable: Path, command: str, value: str
) -> None:
    """Test a timeout that is not a finite number is a usage error for every command."""
    result = invoke_cli(
        command, "sorting", str(python_sort_executable), "--timeout", value
    )

    assert_exits_with(result, 2)
    assert "--timeout" in result.stderr
    # Negative infinity already fails the minimum; the others are caught by the finite check.
    assert ("finite" in result.stderr) == (value != "-inf")


def test_a_finite_timeout_is_accepted(python_sort_executable: Path) -> None:
    """Test a timeout that is a finite number is accepted."""
    result = invoke_cli(
        "debug",
        "sorting",
        str(python_sort_executable),
        "--size",
        "4",
        "--timeout",
        "30",
    )

    assert result.exit_code == 0, result.stderr


@pytest.mark.usefixtures("only_first_fixture")
def test_the_kept_directory_is_shown_for_a_failing_case(
    crashing_executable: Path,
    scratch_root: Path,
) -> None:
    """Test the option keeps the files of a failing case and says where they are."""
    result = invoke_cli(
        "test", "sorting", str(crashing_executable), "--keep-temporary-files"
    )

    assert result.exit_code == 1
    assert "Temporary files were kept in " in result.stdout
    line = next(
        line
        for line in result.stdout.splitlines()
        if "Temporary files were kept in" in line
    )
    directory = Path(line.strip().removeprefix("Temporary files were kept in "))
    assert directory.parent == scratch_root
    assert (directory / "input.bin").is_file()


@pytest.mark.usefixtures("only_first_fixture")
def test_nothing_is_said_without_the_option(crashing_executable: Path) -> None:
    """Test no temporary files are mentioned when the option is not given."""
    result = invoke_cli("test", "sorting", str(crashing_executable))

    assert result.exit_code == 1
    assert "Temporary files" not in result.stdout
