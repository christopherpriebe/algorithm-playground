"""Tests for process groups, temporary files, and timeouts."""

import os
import shlex
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from algorithm_playground.core import (
    BuildError,
    Implementation,
    Runner,
    RunnerError,
    TemporaryFilePolicy,
    build_implementation,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.executables import write_executable

requires_process_groups = pytest.mark.skipif(
    not hasattr(os, "killpg"),
    reason="process groups are not available on this platform",
)


def build_python_code_implementation(
    code: str,
    *,
    name: str = "inline",
    **options: Any,  # noqa: ANN401  forwarded unchanged to Implementation
) -> Implementation:
    """Build an implementation that runs ``code`` with ``python -c``.

    The harness appends the input, output and trace paths, which the code reads
    from ``sys.argv[1:]`` just as a script file would. Unlike a script, it needs
    no file, and the operating system does not scan a new file on its first run.
    """
    return Implementation(
        name=name, command=(sys.executable, "-c", textwrap.dedent(code)), **options
    )


def build_spawner_implementation(identifier_file: Path) -> Implementation:
    """Build an implementation that starts a long sleep, records its process identifier, and waits."""
    return Implementation(
        name="spawner",
        command=("sh", "-c", 'sleep 30 & echo $! > "$0"; wait', str(identifier_file)),
    )


def is_process_running(process_identifier: int) -> bool:
    """Tell whether a process is alive (a zombie awaiting its parent counts as gone)."""
    state = subprocess.run(  # noqa: S603  fixed arguments, no untrusted input
        ["ps", "-o", "stat=", "-p", str(process_identifier)],  # noqa: S607  ps is resolved from PATH on every platform
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")


def wait_until_process_exits(process_identifier: int, seconds: float = 5.0) -> bool:
    """Poll until a real operating-system process is gone, and tell whether that happened in time."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not is_process_running(process_identifier):
            return True
        time.sleep(0.02)
    return False


def read_process_identifier(path: Path) -> int:
    """Read the process identifier that a spawned script wrote to a file."""
    return int(path.read_text().strip())


@requires_process_groups
def test_a_timeout_kills_everything_the_child_started(tmp_path: Path) -> None:
    """Test a timeout also kills the background process the implementation started."""
    identifier_file = tmp_path / "identifier"
    runner = Runner(
        SortingProblem(),
        build_spawner_implementation(identifier_file),
        timeout_seconds=0.5,
    )

    with pytest.raises(RunnerError, match="timed out"):
        runner.run([1])

    assert wait_until_process_exits(read_process_identifier(identifier_file))


@requires_process_groups
def test_a_build_timeout_kills_everything_the_build_started(tmp_path: Path) -> None:
    """Test a build timeout also kills the background process the build started."""
    identifier_file = tmp_path / "identifier"
    implementation = Implementation(
        name="slow-build",
        command=("true",),
        build_command=(
            "sh",
            "-c",
            'sleep 30 & echo $! > "$0"; wait',
            str(identifier_file),
        ),
    )

    with pytest.raises(BuildError, match="timed out"):
        build_implementation(implementation, timeout_seconds=0.5)

    assert wait_until_process_exits(read_process_identifier(identifier_file))


@requires_process_groups
def test_an_interrupt_kills_everything_the_child_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test a keyboard interrupt also kills the background process the implementation started."""
    identifier_file = tmp_path / "identifier"
    original_wait = subprocess.Popen.wait

    def interrupting_wait(
        self: subprocess.Popen[bytes], timeout: float | None = None
    ) -> int:
        if timeout is None:
            return original_wait(self)
        deadline = time.monotonic() + 10
        while not (identifier_file.exists() and identifier_file.read_text().strip()):
            assert time.monotonic() < deadline, "the child never started its helper"
            time.sleep(0.01)
        message = "interrupted by the test"
        raise KeyboardInterrupt(message)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupting_wait)
    runner = Runner(
        SortingProblem(),
        build_spawner_implementation(identifier_file),
        timeout_seconds=30.0,
    )

    with pytest.raises(KeyboardInterrupt, match="interrupted by the test"):
        runner.run([1])

    assert wait_until_process_exits(read_process_identifier(identifier_file))


@pytest.fixture
def background_sorter(tmp_path: Path, python_sort_executable: Path) -> Implementation:
    """A sorter that leaves a long-running background process behind."""
    script = write_executable(
        tmp_path / "background.sh",
        f"""\
            #!/bin/sh
            sleep 30 &
            echo $! > {shlex.quote(str(tmp_path / "identifier"))}
            exec {shlex.quote(sys.executable)} {shlex.quote(str(python_sort_executable))} "$1" "$2"
            """,
    )
    return Implementation.from_executable(script)


@requires_process_groups
def test_a_background_process_does_not_delay_a_successful_run(
    background_sorter: Implementation,
) -> None:
    """Test a successful run returns without waiting for its background process."""
    started = time.monotonic()

    result = Runner(SortingProblem(), background_sorter, timeout_seconds=20.0).run(
        [2, 1]
    )

    assert result.output == [1, 2]
    assert result.wall_seconds < 10.0
    assert time.monotonic() - started < 10.0


@requires_process_groups
def test_a_background_process_is_killed_after_a_successful_run(
    tmp_path: Path, background_sorter: Implementation
) -> None:
    """Test the background process of a successful run is gone once the run returns."""
    Runner(SortingProblem(), background_sorter, timeout_seconds=20.0).run([2, 1])

    assert wait_until_process_exits(read_process_identifier(tmp_path / "identifier"))


@pytest.fixture
def without_process_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the runner behave as on a platform without process groups."""
    monkeypatch.delattr(os, "killpg", raising=False)


@pytest.mark.usefixtures("without_process_groups")
def test_a_run_succeeds(python_sort_executable: Path) -> None:
    """Test a run still returns the sorted values without process groups."""
    implementation = Implementation.from_executable(python_sort_executable)

    result = Runner(SortingProblem(), implementation).run([2, 1])

    assert result.output == [1, 2]


@pytest.mark.usefixtures("without_process_groups")
def test_a_timeout_kills_the_child(tmp_path: Path) -> None:
    """Test a timeout still kills the implementation without process groups."""
    identifier_file = tmp_path / "identifier"
    implementation = Implementation(
        name="sleeper",
        command=("sh", "-c", 'echo $$ > "$0"; exec sleep 30', str(identifier_file)),
    )

    with pytest.raises(RunnerError, match="timed out"):
        Runner(SortingProblem(), implementation, timeout_seconds=0.5).run([1])

    assert wait_until_process_exits(read_process_identifier(identifier_file))


def test_the_scratch_directory_is_removed_after_a_timeout(scratch_root: Path) -> None:
    """Test no scratch directory remains after a run that timed out."""
    implementation = Implementation(
        name="slow", command=("sh", "-c", "exec sleep 30", "x")
    )

    with pytest.raises(RunnerError, match="timed out"):
        Runner(SortingProblem(), implementation, timeout_seconds=0.3).run([1])

    assert list(scratch_root.iterdir()) == []


def test_the_scratch_directory_is_removed_after_a_success(
    scratch_root: Path, python_sort_executable: Path
) -> None:
    """Test no scratch directory remains after a successful run."""
    implementation = Implementation.from_executable(python_sort_executable)

    result = Runner(SortingProblem(), implementation).run([2, 1])

    assert result.temporary_directory is None
    assert list(scratch_root.iterdir()) == []


def test_a_kept_directory_is_in_the_result(
    scratch_root: Path, python_sort_executable: Path
) -> None:
    """Test a run that keeps its files names the directory in the result."""
    implementation = Implementation.from_executable(python_sort_executable)
    runner = Runner(
        SortingProblem(), implementation, temporary_files=TemporaryFilePolicy.KEEP
    )

    result = runner.run([2, 1])

    assert result.temporary_directory is not None
    assert list(scratch_root.iterdir()) == [result.temporary_directory]
    assert (result.temporary_directory / "input.bin").is_file()


def test_a_kept_directory_is_in_the_error(
    scratch_root: Path, crashing_executable: Path
) -> None:
    """Test a failed run that keeps its files names the directory in the error."""
    implementation = Implementation.from_executable(crashing_executable)
    runner = Runner(
        SortingProblem(), implementation, temporary_files=TemporaryFilePolicy.KEEP
    )

    with pytest.raises(RunnerError, match="exited with code 3") as raised:
        runner.run([1])

    directory = raised.value.temporary_directory
    assert directory is not None
    assert list(scratch_root.iterdir()) == [directory]
    assert f"Temporary files were kept in {directory}" in str(raised.value)


@pytest.mark.usefixtures("scratch_root")
def test_an_error_does_not_mention_a_deleted_directory(
    crashing_executable: Path,
) -> None:
    """Test the error of a failed run that deleted its files mentions no directory."""
    runner = Runner(
        SortingProblem(), Implementation.from_executable(crashing_executable)
    )

    with pytest.raises(RunnerError, match="exited with code 3") as raised:
        runner.run([1])

    assert raised.value.temporary_directory is None
    assert "Temporary files" not in str(raised.value)


SLEEPING = "import time; time.sleep(5)"


def test_the_timeout_of_an_implementation_replaces_the_one_of_the_runner() -> None:
    """Test the timeout of an implementation stops its run before the timeout of the runner."""
    implementation = build_python_code_implementation(SLEEPING, timeout_seconds=0.2)
    runner = Runner(SortingProblem(), implementation, timeout_seconds=100.0)
    started = time.monotonic()

    with pytest.raises(RunnerError, match=r"timed out after 0\.200s"):
        runner.run([1])

    assert time.monotonic() - started < 4


def test_a_single_run_can_be_given_a_shorter_timeout() -> None:
    """Test the timeout given to one run replaces the timeout of the runner."""
    runner = Runner(
        SortingProblem(),
        build_python_code_implementation(SLEEPING),
        timeout_seconds=100.0,
    )

    with pytest.raises(RunnerError, match=r"timed out after 0\.150s"):
        runner.run([1], timeout_seconds=0.15)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_the_timeout_of_a_single_run_must_be_a_finite_positive_number(
    timeout: float,
) -> None:
    """Test a run rejects a timeout that is not a finite positive number."""
    runner = Runner(
        SortingProblem(),
        build_python_code_implementation("import sys; sys.exit(0)"),
    )

    with pytest.raises(ValueError, match="finite positive"):
        runner.run([1], timeout_seconds=timeout)
