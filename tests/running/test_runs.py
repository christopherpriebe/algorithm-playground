"""Tests for what a run returns: outputs, traces, failures, and standard streams."""

import os
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import override

from algorithm_playground.core import (
    Implementation,
    Runner,
    RunnerError,
    RunResult,
)
from algorithm_playground.problems.sorting import SortingProblem, SortingTrace
from helpers.executables import INSTRUMENTED_SORT


class UnwritableInputProblem(SortingProblem):
    """The sorting problem whose input hook raises."""

    @override
    def serialize_input(self, data: list[int], path: Path) -> None:
        message = "disk on fire"
        raise RuntimeError(message)


class UnreadableTraceProblem(SortingProblem):
    """The sorting problem whose trace hook raises a KeyError."""

    @override
    def deserialize_trace(self, path: Path, input_data: list[int]) -> SortingTrace:
        message = "section"
        raise KeyError(message)


class UnreadableOutputProblem(SortingProblem):
    """The sorting problem whose output hook raises an IndexError."""

    @override
    def deserialize_output(self, path: Path) -> list[int]:
        message = "list index out of range"
        raise IndexError(message)


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


def build_instrumented_implementation(*flags: str) -> Implementation:
    """Build an implementation that runs the instrumented insertion sort with the given flags."""
    return Implementation(
        name="instrumented",
        command=(sys.executable, str(INSTRUMENTED_SORT), *flags, "insertion"),
    )


@pytest.fixture(scope="module")
def sorted_run(python_sort_executable: Path) -> RunResult[list[int], SortingTrace]:
    """The result of sorting three values with the reference sorter."""
    runner = Runner(
        SortingProblem(), Implementation.from_executable(python_sort_executable)
    )
    return runner.run([3, 1, 2])


def test_runner_returns_sorted_output(
    sorted_run: RunResult[list[int], SortingTrace],
) -> None:
    """Test the run returns the sorted values and no trace when none was requested."""
    assert sorted_run.output == [1, 2, 3]
    assert sorted_run.trace is None


def test_runner_measures_wall_and_cpu_time(
    sorted_run: RunResult[list[int], SortingTrace],
) -> None:
    """Test the run reports a positive wall time and a positive CPU time."""
    assert sorted_run.wall_seconds > 0.0
    assert sorted_run.cpu_user_seconds + sorted_run.cpu_system_seconds > 0.0


def test_runner_leaves_no_temporary_directory_behind(
    sorted_run: RunResult[list[int], SortingTrace],
) -> None:
    """Test the result names no temporary directory when files are not kept."""
    assert sorted_run.temporary_directory is None


def test_runner_returns_trace_when_requested(python_sort_executable: Path) -> None:
    """Test a run with a trace returns the sorted values and the snapshots of the sort."""
    runner = Runner(
        SortingProblem(), Implementation.from_executable(python_sort_executable)
    )

    result = runner.run_with_trace([4, 2, 3, 1])

    assert result.output == [1, 2, 3, 4]
    assert isinstance(result.trace, SortingTrace)
    assert result.trace.snapshots == ((4, 2, 3, 1), (1, 2, 3, 4))


def test_events_are_decoded_without_snapshots() -> None:
    """Test a trace holding only events decodes to the operations of the sort."""
    runner = Runner(
        SortingProblem(), build_instrumented_implementation("--events-only")
    )

    result = runner.run_with_trace([3, 1, 2])

    assert result.output == [1, 2, 3]
    assert isinstance(result.trace, SortingTrace)
    assert result.trace.snapshots == ()
    assert result.trace.events is not None
    assert [event.describe() for event in result.trace.events] == [
        "compare(0, 1)",
        "swap(0, 1)",
        "compare(1, 2)",
        "swap(1, 2)",
        "compare(0, 1)",
    ]


def test_an_event_naming_an_index_outside_the_input_is_a_malformed_trace() -> None:
    """Test an event that names an index beyond the input is reported as a trace error."""
    implementation = build_python_code_implementation(
        """\
            import shutil, struct, sys
            shutil.copyfile(sys.argv[1], sys.argv[2])
            with open(sys.argv[3], "wb") as stream:
                stream.write(struct.pack("<IQ", 1, 1) + struct.pack("<BII", 1, 0, 7))
            """
    )

    result = Runner(SortingProblem(), implementation).run_with_trace([1, 2])

    assert result.trace is None
    assert result.trace_error is not None
    assert "event 0 names index 7, but the array has 2 elements" in result.trace_error


def test_missing_executable_raises_runner_error(tmp_path: Path) -> None:
    """Test running a missing executable raises a RunnerError saying it was not found."""
    runner = Runner(
        SortingProblem(),
        Implementation.from_executable(tmp_path / "does-not-exist"),
    )

    with pytest.raises(RunnerError, match="not found"):
        runner.run([1, 2, 3])


def test_non_zero_exit_raises_runner_error() -> None:
    """Test an implementation that exits with a non-zero code raises a RunnerError."""
    implementation = build_python_code_implementation(
        """\
            import sys
            print("kaboom", file=sys.stderr)
            sys.exit(7)
            """
    )
    runner = Runner(SortingProblem(), implementation)

    with pytest.raises(RunnerError, match="exited with code 7"):
        runner.run([1, 2, 3])


def test_missing_output_file_raises_runner_error() -> None:
    """Test an implementation that writes no output file raises a RunnerError."""
    runner = Runner(
        SortingProblem(),
        build_python_code_implementation("import sys; sys.exit(0)"),
    )

    with pytest.raises(RunnerError, match="did not produce an output file"):
        runner.run([1, 2, 3])


def test_malformed_output_raises_runner_error(
    truncated_output_executable: Path,
) -> None:
    """Test an output file shorter than its header promises raises a RunnerError."""
    runner = Runner(
        SortingProblem(),
        Implementation.from_executable(truncated_output_executable),
    )

    with pytest.raises(RunnerError, match="malformed output file"):
        runner.run([3, 1, 2])


def test_malformed_trace_is_reported_not_raised(
    malformed_trace_executable: Path,
) -> None:
    """Test a malformed trace keeps the output and is reported as a trace error."""
    runner = Runner(
        SortingProblem(), Implementation.from_executable(malformed_trace_executable)
    )

    result = runner.run_with_trace([3, 1, 2])

    assert result.output == [1, 2, 3]
    assert result.trace is None
    assert result.trace_error is not None
    assert "end of stream" in result.trace_error


def test_timeout_raises_runner_error() -> None:
    """Test an implementation that outlasts the timeout raises a RunnerError."""
    runner = Runner(
        SortingProblem(),
        build_python_code_implementation("import time; time.sleep(5)"),
        timeout_seconds=0.2,
    )

    with pytest.raises(RunnerError, match="timed out"):
        runner.run([1, 2, 3])


def test_an_output_path_that_is_a_directory_is_a_runner_error() -> None:
    """Test an output path that is a directory raises a RunnerError."""
    implementation = Implementation(
        name="mkdir", command=("sh", "-c", 'mkdir "$2"', "x")
    )

    with pytest.raises(RunnerError, match="not a regular file"):
        Runner(SortingProblem(), implementation).run([1])


def test_an_absurd_count_header_is_a_malformed_output_not_a_crash() -> None:
    """Test a header that promises an impossible number of elements is a malformed output."""
    implementation = build_python_code_implementation(
        """\
            import struct, sys
            with open(sys.argv[2], "wb") as stream:
                stream.write(struct.pack("<Q", 2**64 - 1))
            """
    )

    with pytest.raises(RunnerError, match="malformed output file"):
        Runner(SortingProblem(), implementation).run([1])


def test_a_trace_path_that_is_a_directory_is_reported_not_raised() -> None:
    """Test a trace path that is a directory gives a result without a trace."""
    implementation = Implementation(
        name="sorter",
        command=("sh", "-c", 'cp "$1" "$2"; [ -n "$3" ] && mkdir "$3"', "x"),
    )

    result = Runner(SortingProblem(), implementation).run_with_trace([])

    assert result.output == []
    assert result.trace is None
    assert result.trace_error is None


def test_an_unreadable_output_file_is_a_runner_error() -> None:
    """Test an output file that cannot be read raises a RunnerError."""
    if os.geteuid() == 0:
        pytest.skip("the superuser can read any file")
    implementation = build_python_code_implementation(
        """\
            import os, sys
            with open(sys.argv[2], "wb") as stream:
                stream.write(b"")
            os.chmod(sys.argv[2], 0)
            """
    )

    with pytest.raises(RunnerError, match="could not be read"):
        Runner(SortingProblem(), implementation).run([1])


def test_a_failed_run_reports_standard_error_under_a_label(
    crashing_executable: Path,
) -> None:
    """Test the error of a failed run holds the standard error under a label."""
    runner = Runner(
        SortingProblem(), Implementation.from_executable(crashing_executable)
    )

    with pytest.raises(RunnerError, match="exited with code 3") as raised:
        runner.run([1])

    assert "exited with code 3.\nstandard error:\nkaboom" in str(raised.value)


def test_a_timeout_reports_the_standard_error_written_so_far() -> None:
    """Test the timeout error holds what the implementation wrote to standard error."""
    implementation = Implementation(
        name="slow",
        command=("sh", "-c", "echo partial progress >&2; exec sleep 30", "x"),
    )
    runner = Runner(SortingProblem(), implementation, timeout_seconds=0.5)

    with pytest.raises(
        RunnerError, match=r"timed out after 0\.500s\nstandard error:\npartial"
    ):
        runner.run([1])


def test_a_missing_output_file_reports_standard_error() -> None:
    """Test the error for a missing output file holds the standard error."""
    implementation = Implementation(
        name="silent", command=("sh", "-c", "echo oops >&2", "x")
    )

    with pytest.raises(
        RunnerError,
        match=r"did not produce an output file.*\nstandard error:\noops",
    ):
        Runner(SortingProblem(), implementation).run([1])


def test_a_malformed_output_file_reports_standard_error() -> None:
    """Test the error for a malformed output file holds the standard error."""
    implementation = build_python_code_implementation(
        """\
            import struct, sys
            print("warning: unsure", file=sys.stderr)
            with open(sys.argv[2], "wb") as stream:
                stream.write(struct.pack("<Q", 5))
            """
    )

    with pytest.raises(
        RunnerError, match=r"malformed output file.*\nstandard error:\nwarning"
    ):
        Runner(SortingProblem(), implementation).run([1])


def test_a_signal_death_names_the_signal() -> None:
    """Test an implementation killed by a signal raises a RunnerError naming the signal."""
    implementation = Implementation(
        name="killed", command=("sh", "-c", "kill -9 $$", "x")
    )

    with pytest.raises(RunnerError, match="terminated by signal SIGKILL"):
        Runner(SortingProblem(), implementation).run([1])


def test_a_long_message_keeps_only_the_end_of_the_output() -> None:
    """Test a very long standard error is cut to its end and says how much was omitted."""
    implementation = Implementation(
        name="chatty",
        command=(
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('a' * 100000 + 'THE END'); sys.exit(1)",
        ),
    )

    with pytest.raises(RunnerError, match="characters omitted") as raised:
        Runner(SortingProblem(), implementation).run([1])

    message = str(raised.value)
    assert len(message) < 30000
    assert message.rstrip().endswith("THE END")


def test_output_larger_than_a_pipe_buffer_does_not_block_the_child() -> None:
    """Test an implementation that writes more than a pipe buffer still finishes."""
    implementation = build_python_code_implementation(
        """\
            import shutil, sys
            sys.stderr.write("x" * 500000)
            sys.stdout.write("y" * 500000)
            shutil.copyfile(sys.argv[1], sys.argv[2])
            """
    )
    runner = Runner(SortingProblem(), implementation, timeout_seconds=30.0)

    result = runner.run([])

    assert result.standard_error == "x" * 500000


def test_the_child_reads_from_the_null_device() -> None:
    """Test the standard input of the implementation is the null device."""
    implementation = build_python_code_implementation(
        """\
            import os, shutil, sys
            if not os.path.samestat(os.fstat(0), os.stat(os.devnull)):
                sys.exit(5)
            shutil.copyfile(sys.argv[1], sys.argv[2])
            """
    )

    result = Runner(SortingProblem(), implementation).run([])

    assert result.output == []


@pytest.mark.parametrize(
    ("code", "message", "category"),
    [
        ("import sys; sys.exit(7)", "exited with code 7", "exit code 7"),
        (
            "import os, signal; os.kill(os.getpid(), signal.SIGKILL)",
            "terminated by signal SIGKILL",
            "signal SIGKILL",
        ),
        (
            "import sys; sys.exit(0)",
            "did not produce an output file",
            "missing output",
        ),
        ("import time; time.sleep(5)", "timed out", "timeout"),
    ],
    ids=["exit code", "signal", "no output", "timeout"],
)
def test_a_failure_names_its_kind(code: str, message: str, category: str) -> None:
    """Test the error of a failed run carries the category of the failure."""
    runner = Runner(
        SortingProblem(),
        build_python_code_implementation(code),
        timeout_seconds=0.3,
    )

    with pytest.raises(RunnerError, match=message) as raised:
        runner.run([1])

    assert raised.value.category == category


def test_a_malformed_output_has_its_own_kind(truncated_output_executable: Path) -> None:
    """Test a malformed output file has the category "malformed output"."""
    runner = Runner(
        SortingProblem(),
        Implementation.from_executable(truncated_output_executable),
    )

    with pytest.raises(RunnerError, match="malformed output file") as raised:
        runner.run([3, 1, 2])

    assert raised.value.category == "malformed output"


def test_a_command_that_cannot_start_has_its_own_kind() -> None:
    """Test a command that cannot be started has the category "cannot start"."""
    runner = Runner(
        SortingProblem(), Implementation(name="ghost", command=("no-such-command",))
    )

    with pytest.raises(RunnerError, match="command not found") as raised:
        runner.run([1])

    assert raised.value.category == "cannot start"


def test_a_plain_runner_error_has_a_generic_kind() -> None:
    """Test a RunnerError built from a message alone has the category "error"."""
    error = RunnerError("something")

    assert error.category == "error"


def test_serialize_input_raising_is_a_runner_error_naming_the_hook() -> None:
    """Test an input hook that raises gives a RunnerError that names the hook and the cause."""
    runner = Runner(
        UnwritableInputProblem(),
        build_python_code_implementation("import sys; sys.exit(0)", name="sorter"),
    )

    with pytest.raises(
        RunnerError,
        match="serialize_input hook could not write the input for 'sorter'",
    ) as raised:
        runner.run([1])

    assert "RuntimeError: disk on fire" in str(raised.value)
    assert raised.value.category == "serialization"


def test_deserialize_trace_raising_is_a_trace_error_not_a_crash() -> None:
    """Test a trace hook that raises is reported as a trace error and keeps the output."""
    implementation = build_python_code_implementation(
        """\
            import shutil, sys
            shutil.copyfile(sys.argv[1], sys.argv[2])
            open(sys.argv[3], "wb").write(b"\\x01")
            """
    )

    result = Runner(UnreadableTraceProblem(), implementation).run_with_trace([2, 1])

    assert result.output == [2, 1]
    assert result.trace is None
    assert (
        result.trace_error
        == "the problem's deserialize_trace hook raised KeyError: 'section'"
    )


def test_deserialize_output_raising_something_unexpected_is_a_malformed_output() -> (
    None
):
    """Test an output hook that raises an unexpected error gives a malformed output error."""
    implementation = build_python_code_implementation(
        "open(__import__('sys').argv[2], 'wb').write(b'x')"
    )

    with pytest.raises(
        RunnerError, match="deserialize_output hook could not read"
    ) as raised:
        Runner(UnreadableOutputProblem(), implementation).run([1])

    assert "IndexError: list index out of range" in str(raised.value)
    assert raised.value.category == "malformed output"
