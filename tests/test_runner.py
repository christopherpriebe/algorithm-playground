"""Tests for the subprocess Runner.

We drive a real Python sorting executable rather than a mocked subprocess so
that the input/output/trace round-trip is exercised end-to-end. Specialized
failure-mode fixtures are written into the test's tmp_path on demand.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest
from support import WriteExecutable

from algorithm_playground.core import runner as runner_module
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.runner import (
    BuildError,
    Runner,
    RunnerError,
    build_implementation,
    build_implementations,
    check_can_start,
)
from algorithm_playground.problems.sorting import SortingProblem, SortingTrace

requires_process_groups = pytest.mark.skipif(
    not hasattr(os, "killpg"), reason="process groups are not available on this platform"
)

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


def python_code(code: str, *, name: str = "inline", **options: Any) -> Implementation:
    """An implementation that runs ``code`` with ``python -c``.

    The harness appends the input, output and trace paths, which the code reads
    from ``sys.argv[1:]`` just as a script file would. Unlike a script, it needs
    no file, and the operating system does not scan a new file on its first run.
    """
    return Implementation(
        name=name, command=(sys.executable, "-c", textwrap.dedent(code)), **options
    )


def is_running(pid: int) -> bool:
    """Whether ``pid`` is a live process (a zombie awaiting its parent counts as gone)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")


def wait_until_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not is_running(pid):
            return True
        time.sleep(0.02)
    return False


def read_pid(path: Path) -> int:
    return int(path.read_text().strip())


def spawner(pid_file: Path) -> Implementation:
    """An implementation that starts a long sleep in the background, records its pid, and waits."""
    return Implementation(
        name="spawner",
        command=("sh", "-c", 'sleep 30 & echo $! > "$0"; wait', str(pid_file)),
    )


class TestSuccessfulRun:
    def test_runner_returns_sorted_output(self, python_sort_executable: Path) -> None:
        runner = Runner(SortingProblem(), Implementation.from_executable(python_sort_executable))
        result = runner.run([3, 1, 2], collect_trace=False)
        assert result.output == [1, 2, 3]
        assert result.trace is None
        assert result.wall_seconds > 0.0
        assert result.cpu_user_seconds + result.cpu_system_seconds > 0.0
        assert result.temporary_directory is None

    def test_runner_returns_trace_when_requested(self, python_sort_executable: Path) -> None:
        runner = Runner(SortingProblem(), Implementation.from_executable(python_sort_executable))
        result = runner.run([4, 2, 3, 1], collect_trace=True)
        assert result.output == [1, 2, 3, 4]
        assert isinstance(result.trace, SortingTrace)
        assert result.trace.snapshots == ((4, 2, 3, 1), (1, 2, 3, 4))


class TestEventTraces:
    script = Path(__file__).parent / "instrumented_sort.py"

    def implementation(self, *flags: str) -> Implementation:
        return Implementation(
            name="instrumented", command=(sys.executable, str(self.script), *flags, "insertion")
        )

    def test_events_are_decoded_without_snapshots(self) -> None:
        runner = Runner(SortingProblem(), self.implementation("--events-only"))
        result = runner.run([3, 1, 2], collect_trace=True)
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
        implementation = python_code(
            """\
            import shutil, struct, sys
            shutil.copyfile(sys.argv[1], sys.argv[2])
            with open(sys.argv[3], "wb") as stream:
                stream.write(struct.pack("<IQ", 1, 1) + struct.pack("<BII", 1, 0, 7))
            """
        )
        result = Runner(SortingProblem(), implementation).run([1, 2], collect_trace=True)
        assert result.trace is None
        assert result.trace_error is not None
        assert "event 0 names index 7, but the array has 2 elements" in result.trace_error


class TestFailureModes:
    def test_missing_executable_raises_runner_error(self, tmp_path: Path) -> None:
        runner = Runner(
            SortingProblem(), Implementation.from_executable(tmp_path / "does-not-exist")
        )
        with pytest.raises(RunnerError, match="not found"):
            runner.run([1, 2, 3])

    def test_non_zero_exit_raises_runner_error(self) -> None:
        implementation = python_code(
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
        runner = Runner(SortingProblem(), python_code("import sys; sys.exit(0)"))
        with pytest.raises(RunnerError, match="did not produce an output file"):
            runner.run([1, 2, 3])

    def test_malformed_output_raises_runner_error(self, truncated_output_executable: Path) -> None:
        runner = Runner(
            SortingProblem(), Implementation.from_executable(truncated_output_executable)
        )
        with pytest.raises(RunnerError, match="malformed output file"):
            runner.run([3, 1, 2])

    def test_malformed_trace_is_reported_not_raised(self, malformed_trace_executable: Path) -> None:
        runner = Runner(
            SortingProblem(), Implementation.from_executable(malformed_trace_executable)
        )
        result = runner.run([3, 1, 2], collect_trace=True)
        assert result.output == [1, 2, 3]
        assert result.trace is None
        assert result.trace_error is not None
        assert "end of stream" in result.trace_error

    def test_timeout_raises_runner_error(self) -> None:
        runner = Runner(
            SortingProblem(), python_code("import time; time.sleep(5)"), timeout_seconds=0.2
        )
        with pytest.raises(RunnerError, match="timed out"):
            runner.run([1, 2, 3])


class TestCommandPrefix:
    def test_runs_a_script_without_the_executable_bit_through_an_interpreter(
        self, plain_sort_script: Path
    ) -> None:
        implementation = Implementation.from_command_text(
            shlex.join([sys.executable, str(plain_sort_script)])
        )
        result = Runner(SortingProblem(), implementation).run([3, 1, 2])
        assert result.output == [1, 2, 3]

    def test_missing_command_names_the_implementation(self) -> None:
        implementation = Implementation(
            name="ghost", command=("algorithm-playground-no-such-command",)
        )
        with pytest.raises(RunnerError, match=r"'ghost'.*not found.*no-such-command"):
            Runner(SortingProblem(), implementation).run([1])

    def test_non_executable_file_reports_permission_denied(self, tmp_path: Path) -> None:
        script = tmp_path / "plain.py"
        script.write_text("print('hello')\n")
        implementation = Implementation(name="plain", command=(str(script),))
        with pytest.raises(RunnerError, match="permission denied"):
            Runner(SortingProblem(), implementation).run([1])


class TestWorkingDirectory:
    def test_command_runs_in_the_working_directory(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        implementation = python_code(INSPECTING_CODE, working_directory=work)
        result = Runner(SortingProblem(), implementation).run([1, 2])
        assert Path(result.standard_error.splitlines()[0]).resolve() == work.resolve()

    def test_relative_command_resolves_against_the_working_directory(
        self, tmp_path: Path, write_executable: WriteExecutable
    ) -> None:
        work = tmp_path / "work"
        work.mkdir()
        write_executable(work / "local.py", "#!/usr/bin/env python3\n" + INSPECTING_CODE)
        implementation = Implementation(
            name="local", command=("./local.py",), working_directory=work
        )
        result = Runner(SortingProblem(), implementation).run([1, 2])
        assert result.output == [1, 2]

    def test_missing_working_directory_raises_runner_error(self, tmp_path: Path) -> None:
        implementation = Implementation(
            name="lost", command=("true",), working_directory=tmp_path / "missing"
        )
        with pytest.raises(RunnerError, match="working directory not found"):
            Runner(SortingProblem(), implementation).run([1])


class TestEnvironment:
    @staticmethod
    def environment_keys(implementation: Implementation) -> set[str]:
        result = Runner(SortingProblem(), implementation).run([1, 2])
        return set(result.standard_error.splitlines()[1].split(","))

    def test_minimal_environment_does_not_include_random_host_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALGORITHM_PLAYGROUND_TEST_SECRET", "must-not-leak")
        keys = self.environment_keys(python_code(INSPECTING_CODE))
        assert "ALGORITHM_PLAYGROUND_TEST_SECRET" not in keys
        assert "PATH" in keys

    def test_inherit_environment_passes_the_full_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALGORITHM_PLAYGROUND_TEST_VARIABLE", "visible")
        inheriting = python_code(INSPECTING_CODE, inherit_environment=True)
        assert "ALGORITHM_PLAYGROUND_TEST_VARIABLE" in self.environment_keys(inheriting)


class TestBuildImplementation:
    def test_no_build_command_is_a_no_op(self) -> None:
        build_implementation(Implementation(name="plain", command=("true",)))

    def test_build_command_runs_in_the_working_directory(self, tmp_path: Path) -> None:
        implementation = Implementation(
            name="built",
            command=("true",),
            working_directory=tmp_path,
            build_command=(sys.executable, "-c", "open('artifact.txt', 'w').write('built')"),
        )
        build_implementation(implementation)
        assert (tmp_path / "artifact.txt").read_text() == "built"

    def test_failed_build_includes_captured_output(self, tmp_path: Path) -> None:
        program = (
            "import sys; print('compiling'); print('syntax problem', file=sys.stderr); sys.exit(4)"
        )
        implementation = Implementation(
            name="broken",
            command=("true",),
            working_directory=tmp_path,
            build_command=(sys.executable, "-c", program),
        )
        with pytest.raises(BuildError) as raised:
            build_implementation(implementation)
        message = str(raised.value)
        assert "'broken'" in message
        assert "exited with code 4" in message
        assert "compiling" in message
        assert "syntax problem" in message

    def test_build_error_is_a_runner_error(self) -> None:
        assert issubclass(BuildError, RunnerError)

    def test_missing_build_command_raises_build_error(self) -> None:
        implementation = Implementation(
            name="ghost",
            command=("true",),
            build_command=("algorithm-playground-no-such-builder",),
        )
        with pytest.raises(BuildError, match="not found"):
            build_implementation(implementation)

    def test_build_timeout_raises_build_error(self) -> None:
        implementation = Implementation(
            name="slow",
            command=("true",),
            build_command=(sys.executable, "-c", "import time; time.sleep(5)"),
        )
        with pytest.raises(BuildError, match="timed out"):
            build_implementation(implementation, timeout_seconds=0.2)

    def test_missing_working_directory_raises_build_error(self, tmp_path: Path) -> None:
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

    def test_a_failing_build_is_returned_with_its_output_and_the_others_still_build(
        self, tmp_path: Path
    ) -> None:
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
        reported: list[str] = []
        failures = build_implementations(
            [failing, later],
            on_build_failed=lambda implementation, error: reported.append(
                f"{implementation.name}: {error}"
            ),
        )
        assert list(failures) == ["broken"]
        assert isinstance(failures["broken"], BuildError)
        assert "compile exploded" in str(failures["broken"])
        assert len(reported) == 1
        assert reported[0].startswith("broken: Build of 'broken'")
        assert (tmp_path / "marker").read_text() == "built"

    def test_nothing_to_build_is_a_no_op(self) -> None:
        failures = build_implementations([Implementation(name="plain", command=("./plain",))])
        assert failures == {}


class TestStartFailures:
    def test_a_script_without_an_interpreter_line_is_a_runner_error(
        self, tmp_path: Path, write_executable: WriteExecutable
    ) -> None:
        script = write_executable(tmp_path / "no_shebang", "echo hello\n")
        implementation = Implementation(name="bare", command=(str(script),))
        with pytest.raises(RunnerError, match=r"'bare': could not start .*first line"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_missing_command_mentions_a_missing_interpreter(self, tmp_path: Path) -> None:
        implementation = Implementation(name="ghost", command=(str(tmp_path / "ghost"),))
        with pytest.raises(RunnerError, match=r"command not found.*interpreter"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_script_naming_a_missing_interpreter_is_a_runner_error(
        self, tmp_path: Path, write_executable: WriteExecutable
    ) -> None:
        script = write_executable(
            tmp_path / "lost.py", "#!/algorithm-playground/no/such/interpreter\n"
        )
        implementation = Implementation(name="lost", command=(str(script),))
        with pytest.raises(RunnerError, match="command not found"):
            Runner(SortingProblem(), implementation).run([1])

    def test_an_embedded_null_character_is_a_runner_error(self) -> None:
        implementation = Implementation(name="nul", command=("sort\0er",))
        with pytest.raises(RunnerError, match="'nul': invalid command"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_build_command_that_cannot_start_is_a_build_error(self) -> None:
        implementation = Implementation(name="nul", command=("true",), build_command=("make\0",))
        with pytest.raises(BuildError, match="invalid command"):
            build_implementation(implementation)

    @pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
    def test_the_timeout_must_be_a_finite_positive_number(self, timeout: float) -> None:
        implementation = Implementation(name="any", command=("true",))
        with pytest.raises(ValueError, match="finite positive"):
            Runner(SortingProblem(), implementation, timeout_seconds=timeout)


class TestCheckCanStart:
    """The check that runs once before the cases, without running anything."""

    def test_an_executable_file_can_be_started(
        self, tmp_path: Path, write_executable: WriteExecutable
    ) -> None:
        script = write_executable(tmp_path / "ok.py", "#!/usr/bin/env python3\n")
        assert check_can_start(Implementation(name="ok", command=(str(script),))) is None

    def test_a_program_on_the_path_can_be_started(self) -> None:
        assert check_can_start(Implementation(name="ok", command=("sh", "-c", "true"))) is None

    def test_the_program_is_not_run(
        self, tmp_path: Path, write_executable: WriteExecutable
    ) -> None:
        marker = tmp_path / "ran"
        script = write_executable(tmp_path / "touch.sh", f"#!/bin/sh\ntouch {marker}\n")
        assert check_can_start(Implementation(name="touch", command=(str(script),))) is None
        assert not marker.exists()

    def test_a_missing_file_is_not_found(self, tmp_path: Path) -> None:
        implementation = Implementation(name="ghost", command=(str(tmp_path / "ghost"),))
        assert check_can_start(implementation) == f"command not found: {tmp_path / 'ghost'}"

    def test_a_file_without_the_executable_bit_is_permission_denied(self, tmp_path: Path) -> None:
        script = tmp_path / "plain.py"
        script.write_text("#!/usr/bin/env python3\n")
        reason = check_can_start(Implementation(name="plain", command=(str(script),)))
        assert reason is not None
        assert reason.startswith(f"command is not runnable (permission denied): {script}")
        assert "chmod +x" in reason

    def test_a_directory_is_not_a_command(self, tmp_path: Path) -> None:
        reason = check_can_start(Implementation(name="dir", command=(str(tmp_path),)))
        assert reason == f"command is not a file: {tmp_path}"

    def test_a_name_that_is_not_on_the_path_is_not_found(self) -> None:
        implementation = Implementation(
            name="ghost", command=("algorithm-playground-no-such-tool",)
        )
        reason = check_can_start(implementation)
        assert reason is not None and reason.startswith(
            "command not found: algorithm-playground-no-such-tool"
        )

    def test_a_relative_path_is_looked_up_in_the_working_directory(
        self, tmp_path: Path, write_executable: WriteExecutable
    ) -> None:
        (tmp_path / "bin").mkdir()
        write_executable(tmp_path / "bin" / "tool", "#!/bin/sh\n")
        implementation = Implementation(
            name="tool", command=("./bin/tool",), working_directory=tmp_path
        )
        assert check_can_start(implementation) is None
        elsewhere = Implementation(
            name="tool", command=("./bin/tool",), working_directory=tmp_path / "bin"
        )
        assert check_can_start(elsewhere) == "command not found: ./bin/tool"

    def test_a_missing_working_directory_is_named(self, tmp_path: Path) -> None:
        implementation = Implementation(
            name="tool", command=("sh",), working_directory=tmp_path / "missing"
        )
        assert (
            check_can_start(implementation)
            == f"working directory not found: {tmp_path / 'missing'}"
        )

    def test_a_bare_name_is_looked_up_on_the_path_of_the_environment_the_run_uses(
        self, tmp_path: Path, write_executable: WriteExecutable
    ) -> None:
        write_executable(tmp_path / "special-tool", "#!/bin/sh\n")
        implementation = Implementation(
            name="tool",
            command=("special-tool",),
            environment={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        )
        assert check_can_start(implementation) is None
        assert check_can_start(Implementation(name="tool", command=("special-tool",))) is not None


class TestOutputFailures:
    def test_an_output_path_that_is_a_directory_is_a_runner_error(self) -> None:
        implementation = Implementation(name="mkdir", command=("sh", "-c", 'mkdir "$2"', "x"))
        with pytest.raises(RunnerError, match="not a regular file"):
            Runner(SortingProblem(), implementation).run([1])

    def test_an_absurd_count_header_is_a_malformed_output_not_a_crash(self) -> None:
        implementation = python_code(
            """\
            import struct, sys
            with open(sys.argv[2], "wb") as stream:
                stream.write(struct.pack("<Q", 2**64 - 1))
            """
        )
        with pytest.raises(RunnerError, match="malformed output file"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_trace_path_that_is_a_directory_is_reported_not_raised(self) -> None:
        implementation = Implementation(
            name="sorter",
            command=("sh", "-c", 'cp "$1" "$2"; [ -n "$3" ] && mkdir "$3"', "x"),
        )
        result = Runner(SortingProblem(), implementation).run([], collect_trace=True)
        assert result.output == []
        assert result.trace is None
        assert result.trace_error is None

    def test_an_unreadable_output_file_is_a_runner_error(self) -> None:
        implementation = python_code(
            """\
            import os, sys
            with open(sys.argv[2], "wb") as stream:
                stream.write(b"")
            os.chmod(sys.argv[2], 0)
            """
        )
        if os.geteuid() == 0:
            pytest.skip("the superuser can read any file")
        with pytest.raises(RunnerError, match="could not be read"):
            Runner(SortingProblem(), implementation).run([1])


class TestStandardError:
    def test_a_failed_run_reports_standard_error_under_a_label(
        self, crashing_executable: Path
    ) -> None:
        runner = Runner(SortingProblem(), Implementation.from_executable(crashing_executable))
        with pytest.raises(RunnerError) as raised:
            runner.run([1])
        assert "exited with code 3.\nstandard error:\nkaboom" in str(raised.value)

    def test_a_timeout_reports_the_standard_error_written_so_far(self) -> None:
        implementation = Implementation(
            name="slow", command=("sh", "-c", "echo partial progress >&2; exec sleep 30", "x")
        )
        runner = Runner(SortingProblem(), implementation, timeout_seconds=0.5)
        with pytest.raises(RunnerError, match=r"timed out after 0\.500s\nstandard error:\npartial"):
            runner.run([1])

    def test_a_missing_output_file_reports_standard_error(self) -> None:
        implementation = Implementation(name="silent", command=("sh", "-c", "echo oops >&2", "x"))
        with pytest.raises(
            RunnerError, match=r"did not produce an output file.*\nstandard error:\noops"
        ):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_malformed_output_file_reports_standard_error(self) -> None:
        implementation = python_code(
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
        implementation = Implementation(name="killed", command=("sh", "-c", "kill -9 $$", "x"))
        with pytest.raises(RunnerError, match="terminated by signal SIGKILL"):
            Runner(SortingProblem(), implementation).run([1])

    def test_a_long_message_keeps_only_the_end_of_the_output(self) -> None:
        implementation = Implementation(
            name="chatty",
            command=(
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('a' * 100000 + 'THE END'); sys.exit(1)",
            ),
        )
        with pytest.raises(RunnerError) as raised:
            Runner(SortingProblem(), implementation).run([1])
        message = str(raised.value)
        assert len(message) < 30000
        assert "characters omitted" in message
        assert message.rstrip().endswith("THE END")

    def test_output_larger_than_a_pipe_buffer_does_not_block_the_child(self) -> None:
        implementation = python_code(
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
        implementation = python_code(
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
        pid_file = tmp_path / "pid"
        runner = Runner(SortingProblem(), spawner(pid_file), timeout_seconds=0.5)
        with pytest.raises(RunnerError, match="timed out"):
            runner.run([1])
        assert wait_until_gone(read_pid(pid_file))

    def test_a_build_timeout_kills_everything_the_build_started(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "pid"
        implementation = Implementation(
            name="slow-build",
            command=("true",),
            build_command=("sh", "-c", 'sleep 30 & echo $! > "$0"; wait', str(pid_file)),
        )
        with pytest.raises(BuildError, match="timed out"):
            build_implementation(implementation, timeout_seconds=0.5)
        assert wait_until_gone(read_pid(pid_file))

    def test_an_interrupt_kills_everything_the_child_started(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pid_file = tmp_path / "pid"
        original_wait = subprocess.Popen.wait

        def interrupting_wait(self: subprocess.Popen, timeout: float | None = None) -> int:
            if timeout is None:
                return original_wait(self)
            deadline = time.monotonic() + 10
            while not (pid_file.exists() and pid_file.read_text().strip()):
                assert time.monotonic() < deadline, "the child never started its helper"
                time.sleep(0.01)
            raise KeyboardInterrupt

        monkeypatch.setattr(subprocess.Popen, "wait", interrupting_wait)
        with pytest.raises(KeyboardInterrupt):
            Runner(SortingProblem(), spawner(pid_file), timeout_seconds=30.0).run([1])
        assert wait_until_gone(read_pid(pid_file))

    def test_a_background_process_does_not_delay_a_successful_run(
        self, tmp_path: Path, write_executable: WriteExecutable, python_sort_executable: Path
    ) -> None:
        pid_file = tmp_path / "pid"
        script = write_executable(
            tmp_path / "background.sh",
            f"""\
            #!/bin/sh
            sleep 30 &
            echo $! > {shlex.quote(str(pid_file))}
            exec {shlex.quote(sys.executable)} {shlex.quote(str(python_sort_executable))} "$1" "$2"
            """,
        )
        started = time.monotonic()
        result = Runner(
            SortingProblem(), Implementation.from_executable(script), timeout_seconds=20.0
        ).run([2, 1])
        assert result.output == [1, 2]
        assert result.wall_seconds < 10.0
        assert time.monotonic() - started < 10.0
        assert wait_until_gone(read_pid(pid_file))


class TestWithoutProcessGroups:
    @pytest.fixture(autouse=True)
    def _no_process_groups(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runner_module, "_SUPPORTS_PROCESS_GROUPS", False)

    def test_a_run_succeeds(self, python_sort_executable: Path) -> None:
        implementation = Implementation.from_executable(python_sort_executable)
        assert Runner(SortingProblem(), implementation).run([2, 1]).output == [1, 2]

    def test_a_timeout_kills_the_child(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "pid"
        implementation = Implementation(
            name="sleeper", command=("sh", "-c", 'echo $$ > "$0"; exec sleep 30', str(pid_file))
        )
        with pytest.raises(RunnerError, match="timed out"):
            Runner(SortingProblem(), implementation, timeout_seconds=0.5).run([1])
        assert wait_until_gone(read_pid(pid_file))


class TestTemporaryFiles:
    @pytest.fixture(autouse=True)
    def _scratch_root(self, scratch_root: Path) -> Path:
        return scratch_root

    def test_the_scratch_directory_is_removed_after_a_timeout(self, _scratch_root: Path) -> None:
        implementation = Implementation(name="slow", command=("sh", "-c", "exec sleep 30", "x"))
        with pytest.raises(RunnerError, match="timed out"):
            Runner(SortingProblem(), implementation, timeout_seconds=0.3).run([1])
        assert list(_scratch_root.iterdir()) == []

    def test_the_scratch_directory_is_removed_after_a_success(
        self, _scratch_root: Path, python_sort_executable: Path
    ) -> None:
        implementation = Implementation.from_executable(python_sort_executable)
        result = Runner(SortingProblem(), implementation).run([2, 1])
        assert result.temporary_directory is None
        assert list(_scratch_root.iterdir()) == []

    def test_a_kept_directory_is_in_the_result(
        self, _scratch_root: Path, python_sort_executable: Path
    ) -> None:
        implementation = Implementation.from_executable(python_sort_executable)
        result = Runner(SortingProblem(), implementation, keep_temporary_files=True).run([2, 1])
        assert result.temporary_directory is not None
        assert list(_scratch_root.iterdir()) == [result.temporary_directory]
        assert (result.temporary_directory / "input.bin").is_file()

    def test_a_kept_directory_is_in_the_error(
        self, _scratch_root: Path, crashing_executable: Path
    ) -> None:
        implementation = Implementation.from_executable(crashing_executable)
        runner = Runner(SortingProblem(), implementation, keep_temporary_files=True)
        with pytest.raises(RunnerError) as raised:
            runner.run([1])
        directory = raised.value.temporary_directory
        assert directory is not None
        assert list(_scratch_root.iterdir()) == [directory]
        assert f"Temporary files were kept in {directory}" in str(raised.value)

    def test_an_error_does_not_mention_a_deleted_directory(self, crashing_executable: Path) -> None:
        runner = Runner(SortingProblem(), Implementation.from_executable(crashing_executable))
        with pytest.raises(RunnerError) as raised:
            runner.run([1])
        assert raised.value.temporary_directory is None
        assert "Temporary files" not in str(raised.value)


class TestBuildOutput:
    def test_a_failed_build_labels_both_streams(self, tmp_path: Path) -> None:
        implementation = Implementation(
            name="broken",
            command=("true",),
            build_command=("sh", "-c", "echo to-out; echo to-err >&2; exit 2"),
        )
        with pytest.raises(BuildError) as raised:
            build_implementation(implementation)
        assert "exited with code 2.\nstandard output:\nto-out\nstandard error:\nto-err" in str(
            raised.value
        )

    def test_a_build_timeout_includes_the_output_so_far(self) -> None:
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
        implementation = python_code(self.ECHO_CODE, environment={"EXTRA_VARIABLE": "from-config"})
        result = Runner(SortingProblem(), implementation).run([1, 2])
        assert result.standard_error.splitlines()[0] == "from-config"

    def test_they_override_the_inherited_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EXTRA_VARIABLE", "from-host")
        implementation = python_code(
            self.ECHO_CODE, inherit_environment=True, environment={"EXTRA_VARIABLE": "from-config"}
        )
        result = Runner(SortingProblem(), implementation).run([1, 2])
        assert result.standard_error.splitlines()[0] == "from-config"

    def test_they_can_replace_the_path(self) -> None:
        implementation = python_code(self.ECHO_CODE, environment={"PATH": "/custom/bin"})
        result = Runner(SortingProblem(), implementation).run([1, 2])
        assert result.standard_error.splitlines()[1] == "/custom/bin"

    def test_a_build_sees_them_too(self, tmp_path: Path) -> None:
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
        implementation = python_code(self.SLEEPING, timeout_seconds=0.2)
        runner = Runner(SortingProblem(), implementation, timeout_seconds=100.0)
        started = time.monotonic()
        with pytest.raises(RunnerError, match=r"timed out after 0\.200s"):
            runner.run([1])
        assert time.monotonic() - started < 4

    def test_a_single_run_can_be_given_a_shorter_timeout(self) -> None:
        runner = Runner(SortingProblem(), python_code(self.SLEEPING), timeout_seconds=100.0)
        with pytest.raises(RunnerError, match=r"timed out after 0\.150s"):
            runner.run([1], timeout_seconds=0.15)

    @pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
    def test_the_timeout_of_a_single_run_must_be_a_finite_positive_number(
        self, timeout: float
    ) -> None:
        runner = Runner(SortingProblem(), python_code("import sys; sys.exit(0)"))
        with pytest.raises(ValueError, match="finite positive"):
            runner.run([1], timeout_seconds=timeout)


class TestFailureCategories:
    @pytest.mark.parametrize(
        ("code", "category"),
        [
            ("import sys; sys.exit(7)", "exit code 7"),
            ("import os, signal; os.kill(os.getpid(), signal.SIGKILL)", "signal SIGKILL"),
            ("import sys; sys.exit(0)", "missing output"),
            ("import time; time.sleep(5)", "timeout"),
        ],
        ids=["exit code", "signal", "no output", "timeout"],
    )
    def test_a_failure_names_its_kind(self, code: str, category: str) -> None:
        runner = Runner(SortingProblem(), python_code(code), timeout_seconds=0.3)
        with pytest.raises(RunnerError) as raised:
            runner.run([1])
        assert raised.value.category == category

    def test_a_malformed_output_has_its_own_kind(self, truncated_output_executable: Path) -> None:
        runner = Runner(
            SortingProblem(), Implementation.from_executable(truncated_output_executable)
        )
        with pytest.raises(RunnerError) as raised:
            runner.run([3, 1, 2])
        assert raised.value.category == "malformed output"

    def test_a_command_that_cannot_start_has_its_own_kind(self) -> None:
        runner = Runner(
            SortingProblem(), Implementation(name="ghost", command=("no-such-command",))
        )
        with pytest.raises(RunnerError) as raised:
            runner.run([1])
        assert raised.value.category == "cannot start"

    def test_a_plain_runner_error_has_a_generic_kind(self) -> None:
        assert RunnerError("something").category == "error"


class TestProblemHooksThatRaise:
    def test_serialize_input_raising_is_a_runner_error_naming_the_hook(self) -> None:
        class CannotWrite(SortingProblem):
            def serialize_input(self, data: list[int], path: Path) -> None:
                raise RuntimeError("disk on fire")

        runner = Runner(CannotWrite(), python_code("import sys; sys.exit(0)", name="sorter"))
        with pytest.raises(RunnerError) as raised:
            runner.run([1])
        message = str(raised.value)
        assert "serialize_input hook could not write the input for 'sorter'" in message
        assert "RuntimeError: disk on fire" in message
        assert raised.value.category == "serialization"

    def test_deserialize_trace_raising_is_a_trace_error_not_a_crash(self) -> None:
        class BrokenTraceReader(SortingProblem):
            def deserialize_trace(self, path: Path, input_data: list[int]) -> SortingTrace:
                raise KeyError("section")

        implementation = python_code(
            """\
            import shutil, sys
            shutil.copyfile(sys.argv[1], sys.argv[2])
            open(sys.argv[3], "wb").write(b"\\x01")
            """
        )
        result = Runner(BrokenTraceReader(), implementation).run([2, 1], collect_trace=True)
        assert result.output == [2, 1]
        assert result.trace is None
        assert (
            result.trace_error == "the problem's deserialize_trace hook raised KeyError: 'section'"
        )

    def test_deserialize_output_raising_something_unexpected_is_a_malformed_output(self) -> None:
        class SloppyReader(SortingProblem):
            def deserialize_output(self, path: Path) -> list[int]:
                raise IndexError("list index out of range")

        implementation = python_code("open(__import__('sys').argv[2], 'wb').write(b'x')")
        with pytest.raises(RunnerError, match="deserialize_output hook could not read") as raised:
            Runner(SloppyReader(), implementation).run([1])
        assert "IndexError: list index out of range" in str(raised.value)
        assert raised.value.category == "malformed output"
