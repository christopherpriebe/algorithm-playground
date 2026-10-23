"""Tests for implementations that cannot be started and the check made before starting."""

from pathlib import Path

import pytest

from algorithm_playground.core import (
    BuildError,
    Implementation,
    Runner,
    RunnerError,
    build_implementation,
    check_can_start,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.executables import write_executable


def test_a_script_without_an_interpreter_line_is_a_runner_error(tmp_path: Path) -> None:
    """Test a script without a first interpreter line raises a RunnerError that says so."""
    script = write_executable(tmp_path / "no_shebang", "echo hello\n")
    implementation = Implementation(name="bare", command=(str(script),))

    with pytest.raises(RunnerError, match=r"'bare': could not start .*first line"):
        Runner(SortingProblem(), implementation).run([1])


def test_a_missing_command_mentions_a_missing_interpreter(tmp_path: Path) -> None:
    """Test the error for a missing command suggests that an interpreter may be missing."""
    implementation = Implementation(name="ghost", command=(str(tmp_path / "ghost"),))

    with pytest.raises(RunnerError, match=r"command not found.*interpreter"):
        Runner(SortingProblem(), implementation).run([1])


def test_a_script_naming_a_missing_interpreter_is_a_runner_error(
    tmp_path: Path,
) -> None:
    """Test a script whose interpreter does not exist raises a RunnerError."""
    script = write_executable(
        tmp_path / "lost.py", "#!/algorithm-playground/no/such/interpreter\n"
    )
    implementation = Implementation(name="lost", command=(str(script),))

    with pytest.raises(RunnerError, match="command not found"):
        Runner(SortingProblem(), implementation).run([1])


def test_an_embedded_null_character_is_a_runner_error() -> None:
    """Test a command with a null character raises a RunnerError naming the implementation."""
    implementation = Implementation(name="nul", command=("sort\0er",))

    with pytest.raises(RunnerError, match="'nul': invalid command"):
        Runner(SortingProblem(), implementation).run([1])


def test_a_build_command_that_cannot_start_is_a_build_error() -> None:
    """Test a build command with a null character raises a BuildError."""
    implementation = Implementation(
        name="nul", command=("true",), build_command=("make\0",)
    )

    with pytest.raises(BuildError, match="invalid command"):
        build_implementation(implementation)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_the_timeout_must_be_a_finite_positive_number(timeout: float) -> None:
    """Test a runner rejects a timeout that is not a finite positive number."""
    implementation = Implementation(name="any", command=("true",))

    with pytest.raises(ValueError, match="finite positive"):
        Runner(SortingProblem(), implementation, timeout_seconds=timeout)


def test_an_executable_file_can_be_started(tmp_path: Path) -> None:
    """Test an executable file has no reason why it cannot start."""
    script = write_executable(tmp_path / "ok.py", "#!/usr/bin/env python3\n")

    reason = check_can_start(Implementation(name="ok", command=(str(script),)))

    assert reason is None


def test_a_program_on_the_path_can_be_started() -> None:
    """Test a program found on the search path has no reason why it cannot start."""
    reason = check_can_start(Implementation(name="ok", command=("sh", "-c", "true")))

    assert reason is None


def test_the_program_is_not_run(tmp_path: Path) -> None:
    """Test checking a command does not run it."""
    marker = tmp_path / "ran"
    script = write_executable(tmp_path / "touch.sh", f"#!/bin/sh\ntouch {marker}\n")

    reason = check_can_start(Implementation(name="touch", command=(str(script),)))

    assert reason is None
    assert not marker.exists()


def test_a_missing_file_is_not_found(tmp_path: Path) -> None:
    """Test a path that does not exist is reported as not found."""
    implementation = Implementation(name="ghost", command=(str(tmp_path / "ghost"),))

    reason = check_can_start(implementation)

    assert reason == f"command not found: {tmp_path / 'ghost'}"


def test_a_file_without_the_executable_bit_is_permission_denied(tmp_path: Path) -> None:
    """Test a file that is not executable is reported with a hint to make it executable."""
    script = tmp_path / "plain.py"
    script.write_text("#!/usr/bin/env python3\n")

    reason = check_can_start(Implementation(name="plain", command=(str(script),)))

    assert reason is not None
    assert reason.startswith(f"command is not runnable (permission denied): {script}")
    assert "chmod +x" in reason


def test_a_directory_is_not_a_command(tmp_path: Path) -> None:
    """Test a directory is reported as not a file."""
    reason = check_can_start(Implementation(name="dir", command=(str(tmp_path),)))

    assert reason == f"command is not a file: {tmp_path}"


def test_a_name_that_is_not_on_the_path_is_not_found() -> None:
    """Test a bare name that is not on the search path is reported as not found."""
    implementation = Implementation(
        name="ghost", command=("algorithm-playground-no-such-tool",)
    )

    reason = check_can_start(implementation)

    assert reason is not None
    assert reason.startswith("command not found: algorithm-playground-no-such-tool")


def test_a_relative_path_is_looked_up_in_the_working_directory(tmp_path: Path) -> None:
    """Test a relative command is found below the working directory."""
    (tmp_path / "bin").mkdir()
    write_executable(tmp_path / "bin" / "tool", "#!/bin/sh\n")
    implementation = Implementation(
        name="tool", command=("./bin/tool",), working_directory=tmp_path
    )

    reason = check_can_start(implementation)

    assert reason is None


def test_a_relative_path_is_not_found_from_another_working_directory(
    tmp_path: Path,
) -> None:
    """Test a relative command is not found when the working directory does not hold it."""
    (tmp_path / "bin").mkdir()
    write_executable(tmp_path / "bin" / "tool", "#!/bin/sh\n")
    elsewhere = Implementation(
        name="tool", command=("./bin/tool",), working_directory=tmp_path / "bin"
    )

    reason = check_can_start(elsewhere)

    assert reason == "command not found: ./bin/tool"


def test_a_missing_working_directory_is_named(tmp_path: Path) -> None:
    """Test a working directory that does not exist is named in the reason."""
    implementation = Implementation(
        name="tool", command=("sh",), working_directory=tmp_path / "missing"
    )

    reason = check_can_start(implementation)

    assert reason == f"working directory not found: {tmp_path / 'missing'}"


def test_a_bare_name_is_looked_up_on_the_path_of_the_environment_the_run_uses(
    tmp_path: Path,
) -> None:
    """Test a bare name is found on the PATH that the implementation sets."""
    write_executable(tmp_path / "special-tool", "#!/bin/sh\n")
    implementation = Implementation(
        name="tool",
        command=("special-tool",),
        environment={"PATH": f"{tmp_path}:/usr/bin:/bin"},
    )

    reason = check_can_start(implementation)

    assert reason is None


def test_a_bare_name_is_not_found_without_the_path_of_the_implementation(
    tmp_path: Path,
) -> None:
    """Test a tool outside the default search path is not found without the PATH setting."""
    write_executable(tmp_path / "special-tool", "#!/bin/sh\n")
    implementation = Implementation(name="tool", command=("special-tool",))

    reason = check_can_start(implementation)

    assert reason is not None
