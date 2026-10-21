"""Tests for the subprocess Runner.

We drive a real Python sorting executable rather than a mocked subprocess so
that the input/output/trace round-trip is exercised end-to-end. Specialized
failure-mode fixtures are written into the test's tmp_path on demand.
"""

import os
import shlex
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.executables import write_executable

from algorithm_playground.core import runner as runner_module
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.runner import (
    BuildError,
    Runner,
    RunnerError,
    RunResult,
    TemporaryFilePolicy,
    build_implementation,
    build_implementations,
    check_can_start,
)
from algorithm_playground.problems.sorting import SortingProblem, SortingTrace

requires_process_groups = pytest.mark.skipif(
    not hasattr(os, "killpg"), reason="process groups are not available on this platform"
)

INSTRUMENTED_SORT_SCRIPT = Path(__file__).resolve().parents[2] / "helpers" / "instrumented_sort.py"

# Copies the input to the output (valid sorting output only for sorted input)
# and reports facts about its process on stderr.
INSPECTING_CODE = textwrap.dedent(
    """\
    import os, shutil, sys
    shutil.copyfile(sys.argv[1], sys.argv[2])
    print(os.getcwd(), file=sys.stderr)
    print(",".join(sorted(os.environ)), file=sys.stderr)
    """
)


class UnwritableInputProblem(SortingProblem):
    """The sorting problem whose input hook raises."""

    def serialize_input(self, data: list[int], path: Path) -> None:
        raise RuntimeError("disk on fire")


class UnreadableTraceProblem(SortingProblem):
    """The sorting problem whose trace hook raises a KeyError."""

    def deserialize_trace(self, path: Path, input_data: list[int]) -> SortingTrace:
        raise KeyError("section")


class UnreadableOutputProblem(SortingProblem):
    """The sorting problem whose output hook raises an IndexError."""

    def deserialize_output(self, path: Path) -> list[int]:
        raise IndexError("list index out of range")


def build_python_code_implementation(
    code: str, *, name: str = "inline", **options: Any
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
        command=(sys.executable, str(INSTRUMENTED_SORT_SCRIPT), *flags, "insertion"),
    )


def build_spawner_implementation(identifier_file: Path) -> Implementation:
    """Build an implementation that starts a long sleep, records its process identifier, and waits."""
    return Implementation(
        name="spawner",
        command=("sh", "-c", 'sleep 30 & echo $! > "$0"; wait', str(identifier_file)),
    )


def is_process_running(process_identifier: int) -> bool:
    """Tell whether a process is alive (a zombie awaiting its parent counts as gone)."""
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(process_identifier)],
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


def collect_environment_keys(implementation: Implementation) -> set[str]:
    """Run the inspecting implementation and collect the names of the variables it saw."""
    result = Runner(SortingProblem(), implementation).run([1, 2])
    return set(result.standard_error.splitlines()[1].split(","))


class TestSuccessfulRun:
    @pytest.fixture(scope="class")
    def sorted_run(self, python_sort_executable: Path) -> RunResult[list[int], SortingTrace]:
        """The result of sorting three values with the reference sorter."""
        runner = Runner(SortingProblem(), Implementation.from_executable(python_sort_executable))
        return runner.run([3, 1, 2])

    def test_runner_returns_sorted_output(
        self, sorted_run: RunResult[list[int], SortingTrace]
    ) -> None:
        """Test the run returns the sorted values and no trace when none was requested."""
        assert sorted_run.output == [1, 2, 3]
        assert sorted_run.trace is None

    def test_runner_measures_wall_and_cpu_time(
        self, sorted_run: RunResult[list[int], SortingTrace]
    ) -> None:
        """Test the run reports a positive wall time and a positive CPU time."""
        assert sorted_run.wall_seconds > 0.0
        assert sorted_run.cpu_user_seconds + sorted_run.cpu_system_seconds > 0.0

    def test_runner_leaves_no_temporary_directory_behind(
        self, sorted_run: RunResult[list[int], SortingTrace]
    ) -> None:
        """Test the result names no temporary directory when files are not kept."""
        assert sorted_run.temporary_directory is None

    def test_runner_returns_trace_when_requested(self, python_sort_executable: Path) -> None:
        """Test a run with a trace returns the sorted values and the snapshots of the sort."""
        runner = Runner(SortingProblem(), Implementation.from_executable(python_sort_executable))

        result = runner.run_with_trace([4, 2, 3, 1])

        assert result.output == [1, 2, 3, 4]
        assert isinstance(result.trace, SortingTrace)
        assert result.trace.snapshots == ((4, 2, 3, 1), (1, 2, 3, 4))


class TestEventTraces:
    def test_events_are_decoded_without_snapshots(self) -> None:
        """Test a trace holding only events decodes to the operations of the sort."""
        runner = Runner(SortingProblem(), build_instrumented_implementation("--events-only"))

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

    def test_an_event_naming_an_index_outside_the_input_is_a_malformed_trace(self) -> None:
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


class TestFailureModes:
    def test_missing_executable_raises_runner_error(self, tmp_path: Path) -> None:
        """Test running a missing executable raises a RunnerError saying it was not found."""
        runner = Runner(
            SortingProblem(), Implementation.from_executable(tmp_path / "does-not-exist")
        )

        with pytest.raises(RunnerError, match="not found"):
            runner.run([1, 2, 3])

    def test_non_zero_exit_raises_runner_error(self) -> None:
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

    def test_missing_output_file_raises_runner_error(self) -> None:
        """Test an implementation that writes no output file raises a RunnerError."""
        runner = Runner(
            SortingProblem(), build_python_code_implementation("import sys; sys.exit(0)")
        )

        with pytest.raises(RunnerError, match="did not produce an output file"):
            runner.run([1, 2, 3])

    def test_malformed_output_raises_runner_error(self, truncated_output_executable: Path) -> None:
        """Test an output file shorter than its header promises raises a RunnerError."""
        runner = Runner(
            SortingProblem(), Implementation.from_executable(truncated_output_executable)
        )

        with pytest.raises(RunnerError, match="malformed output file"):
            runner.run([3, 1, 2])

    def test_malformed_trace_is_reported_not_raised(self, malformed_trace_executable: Path) -> None:
        """Test a malformed trace keeps the output and is reported as a trace error."""
        runner = Runner(
            SortingProblem(), Implementation.from_executable(malformed_trace_executable)
        )

        result = runner.run_with_trace([3, 1, 2])

        assert result.output == [1, 2, 3]
        assert result.trace is None
        assert result.trace_error is not None
        assert "end of stream" in result.trace_error

    def test_timeout_raises_runner_error(self) -> None:
        """Test an implementation that outlasts the timeout raises a RunnerError."""
        runner = Runner(
            SortingProblem(),
            build_python_code_implementation("import time; time.sleep(5)"),
            timeout_seconds=0.2,
        )

        with pytest.raises(RunnerError, match="timed out"):
            runner.run([1, 2, 3])


class TestCommandPrefix:
    def test_runs_a_script_without_the_executable_bit_through_an_interpreter(
        self, plain_sort_script: Path
    ) -> None:
        """Test a script that is not executable runs when an interpreter precedes it."""
        implementation = Implementation.from_command_text(
            shlex.join([sys.executable, str(plain_sort_script)])
        )

        result = Runner(SortingProblem(), implementation).run([3, 1, 2])

        assert result.output == [1, 2, 3]

    def test_missing_command_names_the_implementation(self) -> None:
        """Test the error for a missing command names the implementation and the command."""
        implementation = Implementation(
            name="ghost", command=("algorithm-playground-no-such-command",)
        )

        with pytest.raises(RunnerError, match=r"'ghost'.*not found.*no-such-command"):
            Runner(SortingProblem(), implementation).run([1])

    def test_non_executable_file_reports_permission_denied(self, tmp_path: Path) -> None:
        """Test running a file without the executable bit raises a permission error."""
        script = tmp_path / "plain.py"
        script.write_text("print('hello')\n")
        implementation = Implementation(name="plain", command=(str(script),))

        with pytest.raises(RunnerError, match="permission denied"):
            Runner(SortingProblem(), implementation).run([1])


class TestWorkingDirectory:
    def test_command_runs_in_the_working_directory(self, tmp_path: Path) -> None:
        """Test the command starts with the working directory of the implementation."""
        directory = tmp_path / "work"
        directory.mkdir()
        implementation = build_python_code_implementation(
            INSPECTING_CODE, working_directory=directory
        )

        result = Runner(SortingProblem(), implementation).run([1, 2])

        assert Path(result.standard_error.splitlines()[0]).resolve() == directory.resolve()

    def test_relative_command_resolves_against_the_working_directory(self, tmp_path: Path) -> None:
        """Test a command given as a relative path is found in the working directory."""
        directory = tmp_path / "work"
        directory.mkdir()
        write_executable(directory / "local.py", "#!/usr/bin/env python3\n" + INSPECTING_CODE)
        implementation = Implementation(
            name="local", command=("./local.py",), working_directory=directory
        )

        result = Runner(SortingProblem(), implementation).run([1, 2])

        assert result.output == [1, 2]

    def test_missing_working_directory_raises_runner_error(self, tmp_path: Path) -> None:
        """Test a working directory that does not exist raises a RunnerError."""
        implementation = Implementation(
            name="lost", command=("true",), working_directory=tmp_path / "missing"
        )

        with pytest.raises(RunnerError, match="working directory not found"):
            Runner(SortingProblem(), implementation).run([1])


class TestEnvironment:
    def test_minimal_environment_does_not_include_random_host_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test a variable of the host is not passed to a run with the minimal environment."""
        monkeypatch.setenv("ALGORITHM_PLAYGROUND_TEST_SECRET", "must-not-leak")

        keys = collect_environment_keys(build_python_code_implementation(INSPECTING_CODE))

        assert "ALGORITHM_PLAYGROUND_TEST_SECRET" not in keys

    def test_minimal_environment_keeps_the_path(self) -> None:
        """Test the minimal environment still holds PATH."""
        keys = collect_environment_keys(build_python_code_implementation(INSPECTING_CODE))

        assert "PATH" in keys

    def test_inherit_environment_passes_the_full_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test an implementation that inherits the environment sees the host variables."""
        monkeypatch.setenv("ALGORITHM_PLAYGROUND_TEST_VARIABLE", "visible")
        inheriting = build_python_code_implementation(INSPECTING_CODE, inherit_environment=True)

        keys = collect_environment_keys(inheriting)

        assert "ALGORITHM_PLAYGROUND_TEST_VARIABLE" in keys


class TestBuildImplementation:
    def test_no_build_command_is_a_no_op(self, tmp_path: Path) -> None:
        """Test an implementation without a build command runs nothing."""
        implementation = Implementation(name="plain", command=("true",), working_directory=tmp_path)

        build_implementation(implementation)

        assert list(tmp_path.iterdir()) == []

    def test_build_command_runs_in_the_working_directory(self, tmp_path: Path) -> None:
        """Test the build command runs with the working directory of the implementation."""
        implementation = Implementation(
            name="built",
            command=("true",),
            working_directory=tmp_path,
            build_command=(sys.executable, "-c", "open('artifact.txt', 'w').write('built')"),
        )

        build_implementation(implementation)

        assert (tmp_path / "artifact.txt").read_text() == "built"

    def test_failed_build_includes_captured_output(self, tmp_path: Path) -> None:
        """Test a failed build raises a BuildError naming the implementation and its output."""
        program = (
            "import sys; print('compiling'); print('syntax problem', file=sys.stderr); sys.exit(4)"
        )
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

    def test_build_error_is_a_runner_error(self) -> None:
        """Test a BuildError can be handled as a RunnerError."""
        assert issubclass(BuildError, RunnerError)

    def test_missing_build_command_raises_build_error(self) -> None:
        """Test a build command that does not exist raises a BuildError."""
        implementation = Implementation(
            name="ghost",
            command=("true",),
            build_command=("algorithm-playground-no-such-builder",),
        )

        with pytest.raises(BuildError, match="not found"):
            build_implementation(implementation)

    def test_build_timeout_raises_build_error(self) -> None:
        """Test a build that outlasts its timeout raises a BuildError."""
        implementation = Implementation(
            name="slow",
            command=("true",),
            build_command=(sys.executable, "-c", "import time; time.sleep(5)"),
        )

        with pytest.raises(BuildError, match="timed out"):
            build_implementation(implementation, timeout_seconds=0.2)

    def test_missing_working_directory_raises_build_error(self, tmp_path: Path) -> None:
        """Test a build in a working directory that does not exist raises a BuildError."""
        implementation = Implementation(
            name="lost",
            command=("true",),
            working_directory=tmp_path / "missing",
            build_command=("true",),
        )

        with pytest.raises(BuildError, match="working directory not found"):
            build_implementation(implementation)


class TestBuildImplementations:
    FAILING_BUILD = (
        sys.executable,
        "-c",
        "import sys; print('compile exploded', file=sys.stderr); sys.exit(1)",
    )

    def test_builds_only_implementations_with_a_build_command(self, tmp_path: Path) -> None:
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

    def test_a_failing_build_is_returned_with_its_output(self, tmp_path: Path) -> None:
        """Test a failed build is returned by name as a BuildError holding its output."""
        failing = Implementation(
            name="broken",
            command=("./broken",),
            working_directory=tmp_path,
            build_command=self.FAILING_BUILD,
        )

        failures = build_implementations([failing])

        assert list(failures) == ["broken"]
        assert isinstance(failures["broken"], BuildError)
        assert "compile exploded" in str(failures["broken"])

    def test_a_failing_build_is_reported_through_the_callback(self, tmp_path: Path) -> None:
        """Test the failed-build callback receives the implementation and its error."""
        failing = Implementation(
            name="broken",
            command=("./broken",),
            working_directory=tmp_path,
            build_command=self.FAILING_BUILD,
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

    def test_the_others_still_build_after_a_failing_build(self, tmp_path: Path) -> None:
        """Test an implementation after a failed build is still built."""
        failing = Implementation(
            name="broken",
            command=("./broken",),
            working_directory=tmp_path,
            build_command=self.FAILING_BUILD,
        )
        later = Implementation(
            name="later",
            command=("./later",),
            working_directory=tmp_path,
            build_command=(sys.executable, "-c", "open('marker', 'w').write('built')"),
        )

        build_implementations([failing, later])

        assert (tmp_path / "marker").read_text() == "built"

    def test_nothing_to_build_is_a_no_op(self) -> None:
        """Test implementations without build commands produce no failures."""
        failures = build_implementations([Implementation(name="plain", command=("./plain",))])

        assert failures == {}


class TestStartFailures:
    def test_a_script_without_an_interpreter_line_is_a_runner_error(self, tmp_path: Path) -> None:
        """Test a script without a first interpreter line raises a RunnerError that says so."""
        script = write_executable(tmp_path / "no_shebang", "echo hello\n")
        implementation = Implementation(name="bare", command=(str(script),))

        with pytest.raises(RunnerError, match=r"'bare': could not start .*first line"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_missing_command_mentions_a_missing_interpreter(self, tmp_path: Path) -> None:
        """Test the error for a missing command suggests that an interpreter may be missing."""
        implementation = Implementation(name="ghost", command=(str(tmp_path / "ghost"),))

        with pytest.raises(RunnerError, match=r"command not found.*interpreter"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_script_naming_a_missing_interpreter_is_a_runner_error(self, tmp_path: Path) -> None:
        """Test a script whose interpreter does not exist raises a RunnerError."""
        script = write_executable(
            tmp_path / "lost.py", "#!/algorithm-playground/no/such/interpreter\n"
        )
        implementation = Implementation(name="lost", command=(str(script),))

        with pytest.raises(RunnerError, match="command not found"):
            Runner(SortingProblem(), implementation).run([1])

    def test_an_embedded_null_character_is_a_runner_error(self) -> None:
        """Test a command with a null character raises a RunnerError naming the implementation."""
        implementation = Implementation(name="nul", command=("sort\0er",))

        with pytest.raises(RunnerError, match="'nul': invalid command"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_build_command_that_cannot_start_is_a_build_error(self) -> None:
        """Test a build command with a null character raises a BuildError."""
        implementation = Implementation(name="nul", command=("true",), build_command=("make\0",))

        with pytest.raises(BuildError, match="invalid command"):
            build_implementation(implementation)

    @pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
    def test_the_timeout_must_be_a_finite_positive_number(self, timeout: float) -> None:
        """Test a runner rejects a timeout that is not a finite positive number."""
        implementation = Implementation(name="any", command=("true",))

        with pytest.raises(ValueError, match="finite positive"):
            Runner(SortingProblem(), implementation, timeout_seconds=timeout)


class TestCheckCanStart:
    """The check that runs once before the cases, without running anything."""

    def test_an_executable_file_can_be_started(self, tmp_path: Path) -> None:
        """Test an executable file has no reason why it cannot start."""
        script = write_executable(tmp_path / "ok.py", "#!/usr/bin/env python3\n")

        reason = check_can_start(Implementation(name="ok", command=(str(script),)))

        assert reason is None

    def test_a_program_on_the_path_can_be_started(self) -> None:
        """Test a program found on the search path has no reason why it cannot start."""
        reason = check_can_start(Implementation(name="ok", command=("sh", "-c", "true")))

        assert reason is None

    def test_the_program_is_not_run(self, tmp_path: Path) -> None:
        """Test checking a command does not run it."""
        marker = tmp_path / "ran"
        script = write_executable(tmp_path / "touch.sh", f"#!/bin/sh\ntouch {marker}\n")

        reason = check_can_start(Implementation(name="touch", command=(str(script),)))

        assert reason is None
        assert not marker.exists()

    def test_a_missing_file_is_not_found(self, tmp_path: Path) -> None:
        """Test a path that does not exist is reported as not found."""
        implementation = Implementation(name="ghost", command=(str(tmp_path / "ghost"),))

        reason = check_can_start(implementation)

        assert reason == f"command not found: {tmp_path / 'ghost'}"

    def test_a_file_without_the_executable_bit_is_permission_denied(self, tmp_path: Path) -> None:
        """Test a file that is not executable is reported with a hint to make it executable."""
        script = tmp_path / "plain.py"
        script.write_text("#!/usr/bin/env python3\n")

        reason = check_can_start(Implementation(name="plain", command=(str(script),)))

        assert reason is not None
        assert reason.startswith(f"command is not runnable (permission denied): {script}")
        assert "chmod +x" in reason

    def test_a_directory_is_not_a_command(self, tmp_path: Path) -> None:
        """Test a directory is reported as not a file."""
        reason = check_can_start(Implementation(name="dir", command=(str(tmp_path),)))

        assert reason == f"command is not a file: {tmp_path}"

    def test_a_name_that_is_not_on_the_path_is_not_found(self) -> None:
        """Test a bare name that is not on the search path is reported as not found."""
        implementation = Implementation(
            name="ghost", command=("algorithm-playground-no-such-tool",)
        )

        reason = check_can_start(implementation)

        assert reason is not None
        assert reason.startswith("command not found: algorithm-playground-no-such-tool")

    def test_a_relative_path_is_looked_up_in_the_working_directory(self, tmp_path: Path) -> None:
        """Test a relative command is found below the working directory."""
        (tmp_path / "bin").mkdir()
        write_executable(tmp_path / "bin" / "tool", "#!/bin/sh\n")
        implementation = Implementation(
            name="tool", command=("./bin/tool",), working_directory=tmp_path
        )

        reason = check_can_start(implementation)

        assert reason is None

    def test_a_relative_path_is_not_found_from_another_working_directory(
        self, tmp_path: Path
    ) -> None:
        """Test a relative command is not found when the working directory does not hold it."""
        (tmp_path / "bin").mkdir()
        write_executable(tmp_path / "bin" / "tool", "#!/bin/sh\n")
        elsewhere = Implementation(
            name="tool", command=("./bin/tool",), working_directory=tmp_path / "bin"
        )

        reason = check_can_start(elsewhere)

        assert reason == "command not found: ./bin/tool"

    def test_a_missing_working_directory_is_named(self, tmp_path: Path) -> None:
        """Test a working directory that does not exist is named in the reason."""
        implementation = Implementation(
            name="tool", command=("sh",), working_directory=tmp_path / "missing"
        )

        reason = check_can_start(implementation)

        assert reason == f"working directory not found: {tmp_path / 'missing'}"

    def test_a_bare_name_is_looked_up_on_the_path_of_the_environment_the_run_uses(
        self, tmp_path: Path
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
        self, tmp_path: Path
    ) -> None:
        """Test a tool outside the default search path is not found without the PATH setting."""
        write_executable(tmp_path / "special-tool", "#!/bin/sh\n")
        implementation = Implementation(name="tool", command=("special-tool",))

        reason = check_can_start(implementation)

        assert reason is not None


class TestOutputFailures:
    def test_an_output_path_that_is_a_directory_is_a_runner_error(self) -> None:
        """Test an output path that is a directory raises a RunnerError."""
        implementation = Implementation(name="mkdir", command=("sh", "-c", 'mkdir "$2"', "x"))

        with pytest.raises(RunnerError, match="not a regular file"):
            Runner(SortingProblem(), implementation).run([1])

    def test_an_absurd_count_header_is_a_malformed_output_not_a_crash(self) -> None:
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

    def test_a_trace_path_that_is_a_directory_is_reported_not_raised(self) -> None:
        """Test a trace path that is a directory gives a result without a trace."""
        implementation = Implementation(
            name="sorter",
            command=("sh", "-c", 'cp "$1" "$2"; [ -n "$3" ] && mkdir "$3"', "x"),
        )

        result = Runner(SortingProblem(), implementation).run_with_trace([])

        assert result.output == []
        assert result.trace is None
        assert result.trace_error is None

    def test_an_unreadable_output_file_is_a_runner_error(self) -> None:
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


class TestStandardError:
    def test_a_failed_run_reports_standard_error_under_a_label(
        self, crashing_executable: Path
    ) -> None:
        """Test the error of a failed run holds the standard error under a label."""
        runner = Runner(SortingProblem(), Implementation.from_executable(crashing_executable))

        with pytest.raises(RunnerError, match="exited with code 3") as raised:
            runner.run([1])

        assert "exited with code 3.\nstandard error:\nkaboom" in str(raised.value)

    def test_a_timeout_reports_the_standard_error_written_so_far(self) -> None:
        """Test the timeout error holds what the implementation wrote to standard error."""
        implementation = Implementation(
            name="slow", command=("sh", "-c", "echo partial progress >&2; exec sleep 30", "x")
        )
        runner = Runner(SortingProblem(), implementation, timeout_seconds=0.5)

        with pytest.raises(RunnerError, match=r"timed out after 0\.500s\nstandard error:\npartial"):
            runner.run([1])

    def test_a_missing_output_file_reports_standard_error(self) -> None:
        """Test the error for a missing output file holds the standard error."""
        implementation = Implementation(name="silent", command=("sh", "-c", "echo oops >&2", "x"))

        with pytest.raises(
            RunnerError, match=r"did not produce an output file.*\nstandard error:\noops"
        ):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_malformed_output_file_reports_standard_error(self) -> None:
        """Test the error for a malformed output file holds the standard error."""
        implementation = build_python_code_implementation(
            """\
            import struct, sys
            print("warning: unsure", file=sys.stderr)
            with open(sys.argv[2], "wb") as stream:
                stream.write(struct.pack("<Q", 5))
            """
        )

        with pytest.raises(RunnerError, match=r"malformed output file.*\nstandard error:\nwarning"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_signal_death_names_the_signal(self) -> None:
        """Test an implementation killed by a signal raises a RunnerError naming the signal."""
        implementation = Implementation(name="killed", command=("sh", "-c", "kill -9 $$", "x"))

        with pytest.raises(RunnerError, match="terminated by signal SIGKILL"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_long_message_keeps_only_the_end_of_the_output(self) -> None:
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

    def test_output_larger_than_a_pipe_buffer_does_not_block_the_child(self) -> None:
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


class TestStandardInput:
    def test_the_child_reads_from_the_null_device(self) -> None:
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


@requires_process_groups
class TestProcessGroups:
    def test_a_timeout_kills_everything_the_child_started(self, tmp_path: Path) -> None:
        """Test a timeout also kills the background process the implementation started."""
        identifier_file = tmp_path / "identifier"
        runner = Runner(
            SortingProblem(), build_spawner_implementation(identifier_file), timeout_seconds=0.5
        )

        with pytest.raises(RunnerError, match="timed out"):
            runner.run([1])

        assert wait_until_process_exits(read_process_identifier(identifier_file))

    def test_a_build_timeout_kills_everything_the_build_started(self, tmp_path: Path) -> None:
        """Test a build timeout also kills the background process the build started."""
        identifier_file = tmp_path / "identifier"
        implementation = Implementation(
            name="slow-build",
            command=("true",),
            build_command=("sh", "-c", 'sleep 30 & echo $! > "$0"; wait', str(identifier_file)),
        )

        with pytest.raises(BuildError, match="timed out"):
            build_implementation(implementation, timeout_seconds=0.5)

        assert wait_until_process_exits(read_process_identifier(identifier_file))

    def test_an_interrupt_kills_everything_the_child_started(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test a keyboard interrupt also kills the background process the implementation started."""
        identifier_file = tmp_path / "identifier"
        original_wait = subprocess.Popen.wait

        def interrupting_wait(self: subprocess.Popen, timeout: float | None = None) -> int:
            if timeout is None:
                return original_wait(self)
            deadline = time.monotonic() + 10
            while not (identifier_file.exists() and identifier_file.read_text().strip()):
                assert time.monotonic() < deadline, "the child never started its helper"
                time.sleep(0.01)
            raise KeyboardInterrupt("interrupted by the test")

        monkeypatch.setattr(subprocess.Popen, "wait", interrupting_wait)
        runner = Runner(
            SortingProblem(), build_spawner_implementation(identifier_file), timeout_seconds=30.0
        )

        with pytest.raises(KeyboardInterrupt, match="interrupted by the test"):
            runner.run([1])

        assert wait_until_process_exits(read_process_identifier(identifier_file))

    @pytest.fixture
    def background_sorter(self, tmp_path: Path, python_sort_executable: Path) -> Implementation:
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

    def test_a_background_process_does_not_delay_a_successful_run(
        self, background_sorter: Implementation
    ) -> None:
        """Test a successful run returns without waiting for its background process."""
        started = time.monotonic()

        result = Runner(SortingProblem(), background_sorter, timeout_seconds=20.0).run([2, 1])

        assert result.output == [1, 2]
        assert result.wall_seconds < 10.0
        assert time.monotonic() - started < 10.0

    def test_a_background_process_is_killed_after_a_successful_run(
        self, tmp_path: Path, background_sorter: Implementation
    ) -> None:
        """Test the background process of a successful run is gone once the run returns."""
        Runner(SortingProblem(), background_sorter, timeout_seconds=20.0).run([2, 1])

        assert wait_until_process_exits(read_process_identifier(tmp_path / "identifier"))


class TestWithoutProcessGroups:
    @pytest.fixture
    def without_process_groups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make the runner behave as on a platform without process groups."""
        monkeypatch.setattr(runner_module, "_SUPPORTS_PROCESS_GROUPS", False)

    def test_a_run_succeeds(
        self, without_process_groups: None, python_sort_executable: Path
    ) -> None:
        """Test a run still returns the sorted values without process groups."""
        implementation = Implementation.from_executable(python_sort_executable)

        result = Runner(SortingProblem(), implementation).run([2, 1])

        assert result.output == [1, 2]

    def test_a_timeout_kills_the_child(self, without_process_groups: None, tmp_path: Path) -> None:
        """Test a timeout still kills the implementation without process groups."""
        identifier_file = tmp_path / "identifier"
        implementation = Implementation(
            name="sleeper",
            command=("sh", "-c", 'echo $$ > "$0"; exec sleep 30', str(identifier_file)),
        )

        with pytest.raises(RunnerError, match="timed out"):
            Runner(SortingProblem(), implementation, timeout_seconds=0.5).run([1])

        assert wait_until_process_exits(read_process_identifier(identifier_file))


class TestTemporaryFiles:
    def test_the_scratch_directory_is_removed_after_a_timeout(self, scratch_root: Path) -> None:
        """Test no scratch directory remains after a run that timed out."""
        implementation = Implementation(name="slow", command=("sh", "-c", "exec sleep 30", "x"))

        with pytest.raises(RunnerError, match="timed out"):
            Runner(SortingProblem(), implementation, timeout_seconds=0.3).run([1])

        assert list(scratch_root.iterdir()) == []

    def test_the_scratch_directory_is_removed_after_a_success(
        self, scratch_root: Path, python_sort_executable: Path
    ) -> None:
        """Test no scratch directory remains after a successful run."""
        implementation = Implementation.from_executable(python_sort_executable)

        result = Runner(SortingProblem(), implementation).run([2, 1])

        assert result.temporary_directory is None
        assert list(scratch_root.iterdir()) == []

    def test_a_kept_directory_is_in_the_result(
        self, scratch_root: Path, python_sort_executable: Path
    ) -> None:
        """Test a run that keeps its files names the directory in the result."""
        implementation = Implementation.from_executable(python_sort_executable)
        runner = Runner(SortingProblem(), implementation, temporary_files=TemporaryFilePolicy.KEEP)

        result = runner.run([2, 1])

        assert result.temporary_directory is not None
        assert list(scratch_root.iterdir()) == [result.temporary_directory]
        assert (result.temporary_directory / "input.bin").is_file()

    def test_a_kept_directory_is_in_the_error(
        self, scratch_root: Path, crashing_executable: Path
    ) -> None:
        """Test a failed run that keeps its files names the directory in the error."""
        implementation = Implementation.from_executable(crashing_executable)
        runner = Runner(SortingProblem(), implementation, temporary_files=TemporaryFilePolicy.KEEP)

        with pytest.raises(RunnerError, match="exited with code 3") as raised:
            runner.run([1])

        directory = raised.value.temporary_directory
        assert directory is not None
        assert list(scratch_root.iterdir()) == [directory]
        assert f"Temporary files were kept in {directory}" in str(raised.value)

    def test_an_error_does_not_mention_a_deleted_directory(
        self, scratch_root: Path, crashing_executable: Path
    ) -> None:
        """Test the error of a failed run that deleted its files mentions no directory."""
        runner = Runner(SortingProblem(), Implementation.from_executable(crashing_executable))

        with pytest.raises(RunnerError, match="exited with code 3") as raised:
            runner.run([1])

        assert raised.value.temporary_directory is None
        assert "Temporary files" not in str(raised.value)


class TestBuildOutput:
    def test_a_failed_build_labels_both_streams(self) -> None:
        """Test a failed build reports standard output and standard error under labels."""
        implementation = Implementation(
            name="broken",
            command=("true",),
            build_command=("sh", "-c", "echo to-out; echo to-err >&2; exit 2"),
        )

        with pytest.raises(BuildError, match="exited with code 2") as raised:
            build_implementation(implementation)

        assert "exited with code 2.\nstandard output:\nto-out\nstandard error:\nto-err" in str(
            raised.value
        )

    def test_a_build_timeout_includes_the_output_so_far(self) -> None:
        """Test a build timeout reports the output the build wrote before it was stopped."""
        implementation = Implementation(
            name="slow",
            command=("true",),
            build_command=("sh", "-c", "echo compiling; echo trouble >&2; exec sleep 30"),
        )

        with pytest.raises(
            BuildError, match=r"timed out.*\nstandard output:\ncompiling\nstandard error:\ntrouble"
        ):
            build_implementation(implementation, timeout_seconds=0.5)


class TestExtraEnvironment:
    ECHO_CODE = """\
        import os, shutil, sys
        shutil.copyfile(sys.argv[1], sys.argv[2])
        print(os.environ.get("EXTRA_VARIABLE", "unset"), file=sys.stderr)
        print(os.environ.get("PATH", "no path"), file=sys.stderr)
        """

    def test_the_variables_of_an_implementation_are_set_on_top_of_the_minimal_environment(
        self,
    ) -> None:
        """Test the variables of an implementation are visible to its run."""
        implementation = build_python_code_implementation(
            self.ECHO_CODE, environment={"EXTRA_VARIABLE": "from-config"}
        )

        result = Runner(SortingProblem(), implementation).run([1, 2])

        assert result.standard_error.splitlines()[0] == "from-config"

    def test_they_override_the_inherited_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test a variable of the implementation replaces the same variable of the host."""
        monkeypatch.setenv("EXTRA_VARIABLE", "from-host")
        implementation = build_python_code_implementation(
            self.ECHO_CODE, inherit_environment=True, environment={"EXTRA_VARIABLE": "from-config"}
        )

        result = Runner(SortingProblem(), implementation).run([1, 2])

        assert result.standard_error.splitlines()[0] == "from-config"

    def test_they_can_replace_the_path(self) -> None:
        """Test an implementation can set its own PATH."""
        implementation = build_python_code_implementation(
            self.ECHO_CODE, environment={"PATH": "/custom/bin"}
        )

        result = Runner(SortingProblem(), implementation).run([1, 2])

        assert result.standard_error.splitlines()[1] == "/custom/bin"

    def test_a_build_sees_them_too(self, tmp_path: Path) -> None:
        """Test the build command sees the variables of the implementation."""
        marker = tmp_path / "marker"
        implementation = Implementation(
            name="built",
            command=("true",),
            build_command=("sh", "-c", f'printf %s "$EXTRA_VARIABLE" > {shlex.quote(str(marker))}'),
            environment={"EXTRA_VARIABLE": "visible to the build"},
        )

        build_implementation(implementation)

        assert marker.read_text() == "visible to the build"


class TestTimeouts:
    SLEEPING = "import time; time.sleep(5)"

    def test_the_timeout_of_an_implementation_replaces_the_one_of_the_runner(self) -> None:
        """Test the timeout of an implementation stops its run before the timeout of the runner."""
        implementation = build_python_code_implementation(self.SLEEPING, timeout_seconds=0.2)
        runner = Runner(SortingProblem(), implementation, timeout_seconds=100.0)
        started = time.monotonic()

        with pytest.raises(RunnerError, match=r"timed out after 0\.200s"):
            runner.run([1])

        assert time.monotonic() - started < 4

    def test_a_single_run_can_be_given_a_shorter_timeout(self) -> None:
        """Test the timeout given to one run replaces the timeout of the runner."""
        runner = Runner(
            SortingProblem(),
            build_python_code_implementation(self.SLEEPING),
            timeout_seconds=100.0,
        )

        with pytest.raises(RunnerError, match=r"timed out after 0\.150s"):
            runner.run([1], timeout_seconds=0.15)

    @pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
    def test_the_timeout_of_a_single_run_must_be_a_finite_positive_number(
        self, timeout: float
    ) -> None:
        """Test a run rejects a timeout that is not a finite positive number."""
        runner = Runner(
            SortingProblem(), build_python_code_implementation("import sys; sys.exit(0)")
        )

        with pytest.raises(ValueError, match="finite positive"):
            runner.run([1], timeout_seconds=timeout)


class TestFailureCategories:
    @pytest.mark.parametrize(
        ("code", "message", "category"),
        [
            ("import sys; sys.exit(7)", "exited with code 7", "exit code 7"),
            (
                "import os, signal; os.kill(os.getpid(), signal.SIGKILL)",
                "terminated by signal SIGKILL",
                "signal SIGKILL",
            ),
            ("import sys; sys.exit(0)", "did not produce an output file", "missing output"),
            ("import time; time.sleep(5)", "timed out", "timeout"),
        ],
        ids=["exit code", "signal", "no output", "timeout"],
    )
    def test_a_failure_names_its_kind(self, code: str, message: str, category: str) -> None:
        """Test the error of a failed run carries the category of the failure."""
        runner = Runner(
            SortingProblem(), build_python_code_implementation(code), timeout_seconds=0.3
        )

        with pytest.raises(RunnerError, match=message) as raised:
            runner.run([1])

        assert raised.value.category == category

    def test_a_malformed_output_has_its_own_kind(self, truncated_output_executable: Path) -> None:
        """Test a malformed output file has the category "malformed output"."""
        runner = Runner(
            SortingProblem(), Implementation.from_executable(truncated_output_executable)
        )

        with pytest.raises(RunnerError, match="malformed output file") as raised:
            runner.run([3, 1, 2])

        assert raised.value.category == "malformed output"

    def test_a_command_that_cannot_start_has_its_own_kind(self) -> None:
        """Test a command that cannot be started has the category "cannot start"."""
        runner = Runner(
            SortingProblem(), Implementation(name="ghost", command=("no-such-command",))
        )

        with pytest.raises(RunnerError, match="command not found") as raised:
            runner.run([1])

        assert raised.value.category == "cannot start"

    def test_a_plain_runner_error_has_a_generic_kind(self) -> None:
        """Test a RunnerError built from a message alone has the category "error"."""
        error = RunnerError("something")

        assert error.category == "error"


class TestProblemHooksThatRaise:
    def test_serialize_input_raising_is_a_runner_error_naming_the_hook(self) -> None:
        """Test an input hook that raises gives a RunnerError that names the hook and the cause."""
        runner = Runner(
            UnwritableInputProblem(),
            build_python_code_implementation("import sys; sys.exit(0)", name="sorter"),
        )

        with pytest.raises(
            RunnerError, match="serialize_input hook could not write the input for 'sorter'"
        ) as raised:
            runner.run([1])

        assert "RuntimeError: disk on fire" in str(raised.value)
        assert raised.value.category == "serialization"

    def test_deserialize_trace_raising_is_a_trace_error_not_a_crash(self) -> None:
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
            result.trace_error == "the problem's deserialize_trace hook raised KeyError: 'section'"
        )

    def test_deserialize_output_raising_something_unexpected_is_a_malformed_output(self) -> None:
        """Test an output hook that raises an unexpected error gives a malformed output error."""
        implementation = build_python_code_implementation(
            "open(__import__('sys').argv[2], 'wb').write(b'x')"
        )

        with pytest.raises(RunnerError, match="deserialize_output hook could not read") as raised:
            Runner(UnreadableOutputProblem(), implementation).run([1])

        assert "IndexError: list index out of range" in str(raised.value)
        assert raised.value.category == "malformed output"
