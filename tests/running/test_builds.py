"""Tests for building implementations before they run."""

import sys
from pathlib import Path

import pytest

from algorithm_playground.core import (
    BuildError,
    Implementation,
    RunnerError,
    build_implementation,
    build_implementations,
)


def test_no_build_command_is_a_no_op(tmp_path: Path) -> None:
    """Test an implementation without a build command runs nothing."""
    implementation = Implementation(
        name="plain", command=("true",), working_directory=tmp_path
    )

    build_implementation(implementation)

    assert list(tmp_path.iterdir()) == []


def test_build_command_runs_in_the_working_directory(tmp_path: Path) -> None:
    """Test the build command runs with the working directory of the implementation."""
    implementation = Implementation(
        name="built",
        command=("true",),
        working_directory=tmp_path,
        build_command=(
            sys.executable,
            "-c",
            "open('artifact.txt', 'w').write('built')",
        ),
    )

    build_implementation(implementation)

    assert (tmp_path / "artifact.txt").read_text() == "built"


def test_failed_build_includes_captured_output(tmp_path: Path) -> None:
    """Test a failed build raises a BuildError naming the implementation and its output."""
    program = "import sys; print('compiling'); print('syntax problem', file=sys.stderr); sys.exit(4)"
    implementation = Implementation(
        name="broken",
        command=("true",),
        working_directory=tmp_path,
        build_command=(sys.executable, "-c", program),
    )

    with pytest.raises(BuildError, match="exited with code 4") as raised:
        build_implementation(implementation)

    message = str(raised.value)
    assert "'broken'" in message
    assert "compiling" in message
    assert "syntax problem" in message


def test_build_error_is_a_runner_error() -> None:
    """Test a BuildError can be handled as a RunnerError."""
    assert issubclass(BuildError, RunnerError)


def test_missing_build_command_raises_build_error() -> None:
    """Test a build command that does not exist raises a BuildError."""
    implementation = Implementation(
        name="ghost",
        command=("true",),
        build_command=("algorithm-playground-no-such-builder",),
    )

    with pytest.raises(BuildError, match="not found"):
        build_implementation(implementation)


def test_build_timeout_raises_build_error() -> None:
    """Test a build that outlasts its timeout raises a BuildError."""
    implementation = Implementation(
        name="slow",
        command=("true",),
        build_command=(sys.executable, "-c", "import time; time.sleep(5)"),
    )

    with pytest.raises(BuildError, match="timed out"):
        build_implementation(implementation, timeout_seconds=0.2)


def test_missing_working_directory_raises_build_error(tmp_path: Path) -> None:
    """Test a build in a working directory that does not exist raises a BuildError."""
    implementation = Implementation(
        name="lost",
        command=("true",),
        working_directory=tmp_path / "missing",
        build_command=("true",),
    )

    with pytest.raises(BuildError, match="working directory not found"):
        build_implementation(implementation)


FAILING_BUILD = (
    sys.executable,
    "-c",
    "import sys; print('compile exploded', file=sys.stderr); sys.exit(1)",
)


def test_builds_only_implementations_with_a_build_command(tmp_path: Path) -> None:
    """Test only the implementation with a build command is announced and built."""
    with_build = Implementation(
        name="compiled",
        command=("./compiled",),
        working_directory=tmp_path,
        build_command=(sys.executable, "-c", "open('marker', 'w').write('built')"),
    )
    without_build = Implementation(name="plain", command=("./plain",))
    announced: list[str] = []

    failures = build_implementations(
        [without_build, with_build],
        on_build_started=lambda implementation: announced.append(implementation.name),
    )

    assert failures == {}
    assert announced == ["compiled"]
    assert (tmp_path / "marker").read_text() == "built"


def test_a_failing_build_is_returned_with_its_output(tmp_path: Path) -> None:
    """Test a failed build is returned by name as a BuildError holding its output."""
    failing = Implementation(
        name="broken",
        command=("./broken",),
        working_directory=tmp_path,
        build_command=FAILING_BUILD,
    )

    failures = build_implementations([failing])

    assert list(failures) == ["broken"]
    assert isinstance(failures["broken"], BuildError)
    assert "compile exploded" in str(failures["broken"])


def test_a_failing_build_is_reported_through_the_callback(tmp_path: Path) -> None:
    """Test the failed-build callback receives the implementation and its error."""
    failing = Implementation(
        name="broken",
        command=("./broken",),
        working_directory=tmp_path,
        build_command=FAILING_BUILD,
    )
    reported: list[str] = []

    build_implementations(
        [failing],
        on_build_failed=lambda implementation, error: reported.append(
            f"{implementation.name}: {error}"
        ),
    )

    assert len(reported) == 1
    assert reported[0].startswith("broken: Build of 'broken'")


def test_the_others_still_build_after_a_failing_build(tmp_path: Path) -> None:
    """Test an implementation after a failed build is still built."""
    failing = Implementation(
        name="broken",
        command=("./broken",),
        working_directory=tmp_path,
        build_command=FAILING_BUILD,
    )
    later = Implementation(
        name="later",
        command=("./later",),
        working_directory=tmp_path,
        build_command=(sys.executable, "-c", "open('marker', 'w').write('built')"),
    )

    build_implementations([failing, later])

    assert (tmp_path / "marker").read_text() == "built"


def test_nothing_to_build_is_a_no_op() -> None:
    """Test implementations without build commands produce no failures."""
    failures = build_implementations(
        [Implementation(name="plain", command=("./plain",))]
    )

    assert failures == {}


def test_a_failed_build_labels_both_streams() -> None:
    """Test a failed build reports standard output and standard error under labels."""
    implementation = Implementation(
        name="broken",
        command=("true",),
        build_command=("sh", "-c", "echo to-out; echo to-err >&2; exit 2"),
    )

    with pytest.raises(BuildError, match="exited with code 2") as raised:
        build_implementation(implementation)

    assert (
        "exited with code 2.\nstandard output:\nto-out\nstandard error:\nto-err"
        in str(raised.value)
    )


def test_a_build_timeout_includes_the_output_so_far() -> None:
    """Test a build timeout reports the output the build wrote before it was stopped."""
    implementation = Implementation(
        name="slow",
        command=("true",),
        build_command=(
            "sh",
            "-c",
            "echo compiling; echo trouble >&2; exec sleep 30",
        ),
    )

    with pytest.raises(
        BuildError,
        match=r"timed out.*\nstandard output:\ncompiling\nstandard error:\ntrouble",
    ):
        build_implementation(implementation, timeout_seconds=0.5)
