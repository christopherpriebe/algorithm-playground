"""Subprocess wrapper that invokes an implementation with the playground's I/O contract.

The contract is ``<command...> <input_path> <output_path> [<trace_path>]``,
where the command comes from an :class:`~algorithm_playground.core.implementation.Implementation`.
The :class:`Runner` materializes the input via the problem's serializer,
spawns the command with empty standard input, enforces a timeout, measures
wall-clock and CPU time, and includes the program's standard error in every
failure. The child runs in its own process group, and the whole group is killed
when the run times out, is interrupted, or finishes, so no process it started
outlives the run or holds its pipes open. :func:`build_implementation` runs an
implementation's optional build command once before use under the same rules.
"""

import contextlib
import functools
import math
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import IO, Generic, Protocol

from algorithm_playground.core.binary_format import BinaryFormatError
from algorithm_playground.core.description import describe_error
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.problem import AnyProblem, InputT, OutputT, Problem, TraceT

try:
    import resource
except ImportError:  # The resource module exists on POSIX only.
    resource = None  # ty: ignore[invalid-assignment]

__all__ = [
    "DEFAULT_BUILD_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "SERIALIZATION_CATEGORY",
    "TIMEOUT_CATEGORY",
    "TRACE_FILE_NAME",
    "BuildError",
    "RunResult",
    "Runner",
    "RunnerError",
    "RunnerFactory",
    "RunnerLike",
    "TemporaryFilePolicy",
    "build_implementation",
    "build_implementations",
    "check_can_start",
    "subprocess_runner_factory",
]

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_BUILD_TIMEOUT_SECONDS = 300.0
TRACE_FILE_NAME = "trace.bin"
TIMEOUT_CATEGORY = "timeout"
SERIALIZATION_CATEGORY = "serialization"

_INPUT_FILE_NAME = "input.bin"
_OUTPUT_FILE_NAME = "output.bin"
_SUPPORTS_PROCESS_GROUPS = hasattr(os, "killpg")
# How long to wait for a pipe to close after the process group was killed.
_PIPE_DRAIN_SECONDS = 2.0
_READ_CHUNK_BYTES = 64 * 1024
_MAXIMUM_REPORTED_CHARACTERS = 20_000
_PRESERVED_ENVIRONMENT_KEYS = frozenset({"PATH", "LANG", "LC_ALL", "HOME", "TMPDIR"})
_EXECUTABLE_FORMAT_ERROR = 8  # ENOEXEC: not a program the operating system can run


def _require_valid_timeout(timeout_seconds: float) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(f"Timeout must be a finite positive number, got {timeout_seconds}")


def _require_working_directory(
    implementation: Implementation, *, error_type: type["RunnerError"]
) -> None:
    directory = implementation.working_directory
    if directory is not None and not directory.is_dir():
        raise error_type(
            f"Implementation '{implementation.name}': working directory not found: {directory}"
        )


def _describe_timeout(subject: str, timeout_seconds: float) -> str:
    return f"{subject} timed out after {timeout_seconds:.3f}s"


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return str(number)


def _exit_category(return_code: int) -> str:
    if return_code >= 0:
        return f"exit code {return_code}"
    return f"signal {_signal_name(-return_code)}"


def _describe_exit(return_code: int) -> str:
    if return_code >= 0:
        return f"exited with code {return_code}"
    return f"was terminated by signal {_signal_name(-return_code)}"


def _tail(text: str) -> str:
    if len(text) <= _MAXIMUM_REPORTED_CHARACTERS:
        return text
    omitted = len(text) - _MAXIMUM_REPORTED_CHARACTERS
    return f"(first {omitted} characters omitted)\n{text[omitted:]}"


def _with_output(message: str, *, standard_error: str, standard_output: str | None = None) -> str:
    """Append the non-blank captured output streams to ``message`` under labels."""
    parts = [message]
    if standard_output is not None and standard_output.strip():
        parts.append(f"standard output:\n{_tail(standard_output.rstrip())}")
    if standard_error.strip():
        parts.append(f"standard error:\n{_tail(standard_error.rstrip())}")
    return "\n".join(parts)


def _runner_failure(
    subject: str, reason: str, *, category: str, standard_error: str
) -> "RunnerError":
    """Build the error for a run of ``subject`` that failed for ``reason``, with its standard error."""
    return RunnerError(
        _with_output(f"{subject} {reason}", standard_error=standard_error), category=category
    )


def _start_hint(error: OSError) -> str:
    if error.errno == _EXECUTABLE_FORMAT_ERROR:
        return (
            " (a script needs a first line such as '#!/usr/bin/env python3', or run it "
            "through its interpreter, for example --command 'python3 sort.py')"
        )
    return ""


def _child_environment(implementation: Implementation) -> dict[str, str]:
    """Return the environment for a child process of ``implementation``.

    By default that is a small, predictable subset of the caller's environment;
    with ``inherit_environment`` it is all of it. The variables of the
    implementation's own ``environment`` are added on top.
    """
    if implementation.inherit_environment:
        environment = dict(os.environ)
    else:
        environment = {
            key: value for key, value in os.environ.items() if key in _PRESERVED_ENVIRONMENT_KEYS
        }
        environment.setdefault("PATH", "/usr/bin:/bin")
    environment.update(implementation.environment)
    return environment


def _children_cpu_seconds() -> tuple[float, float]:
    """Return cumulative (user, system) CPU seconds across all reaped children.

    Uses :mod:`resource` when available (POSIX). On platforms without the
    module, returns ``(0.0, 0.0)``. Callers should subtract a "before" sample
    from an "after" sample to get the cost of a single subprocess.
    """
    if resource is None:
        return 0.0, 0.0
    try:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    except OSError:
        return 0.0, 0.0
    return usage.ru_utime, usage.ru_stime


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Kill the child and every process it started that is still in its process group."""
    with contextlib.suppress(OSError):
        if _SUPPORTS_PROCESS_GROUPS:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()


def _start_process(
    command: Sequence[str],
    implementation: Implementation,
    *,
    subject: str,
    error_type: type["RunnerError"],
) -> subprocess.Popen[bytes]:
    """Start ``command`` with empty standard input, piped output and its own process group.

    Raises:
        RunnerError: ``error_type``, with the category ``cannot start``, when the
            command cannot be started.
    """
    try:
        return subprocess.Popen(
            command,
            cwd=implementation.working_directory,
            env=_child_environment(implementation),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=_SUPPORTS_PROCESS_GROUPS,
        )
    except FileNotFoundError as error:
        raise error_type(
            f"{subject}: command not found: {command[0]} (a script whose first line names a "
            "missing interpreter is reported the same way)",
            category="cannot start",
        ) from error
    except PermissionError as error:
        raise error_type(
            f"{subject}: command is not runnable (permission denied): {command[0]}",
            category="cannot start",
        ) from error
    except OSError as error:
        raise error_type(
            f"{subject}: could not start {command[0]}: {error.strerror or error}"
            f"{_start_hint(error)}",
            category="cannot start",
        ) from error
    except ValueError as error:
        raise error_type(f"{subject}: invalid command: {error}", category="cannot start") from error


def _read_pipes(process: subprocess.Popen[bytes]) -> tuple["_PipeReader", "_PipeReader"]:
    """Start collecting the standard output and the standard error of ``process``."""
    assert process.stdout is not None
    assert process.stderr is not None
    return _PipeReader(process.stdout), _PipeReader(process.stderr)


def _wait_and_stop(
    process: subprocess.Popen[bytes], start: float, timeout_seconds: float
) -> tuple[int, float, bool]:
    """Wait for ``process`` to exit, kill its process group, and say how it ended.

    Return the return code, the wall seconds from ``start`` (a ``perf_counter``
    time) until the process exited or the timeout hit, and whether the process
    was killed at the timeout.
    """
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        wall_seconds = time.perf_counter() - start
        _kill_process_group(process)
        return process.wait(), wall_seconds, True
    wall_seconds = time.perf_counter() - start
    _kill_process_group(process)
    return return_code, wall_seconds, False


def _abandon_process(process: subprocess.Popen[bytes], readers: Sequence["_PipeReader"]) -> None:
    """Kill the process group, reap the child and release the pipes after an interruption."""
    _kill_process_group(process)
    with contextlib.suppress(Exception):
        process.wait()
    deadline = time.monotonic() + _PIPE_DRAIN_SECONDS
    for reader in readers:
        reader.collect(deadline)


def _run_process(
    command: Sequence[str],
    implementation: Implementation,
    *,
    subject: str,
    timeout_seconds: float,
    error_type: type["RunnerError"],
) -> "_ProcessResult":
    """Run ``command`` in the working directory and environment of ``implementation``.

    ``subject`` names what is running in error messages. The command gets
    empty standard input and its own process group. Raise ``error_type`` when
    the command cannot be started. A command that exceeds the timeout is killed
    and reported through ``timed_out`` in the result, with the output written so
    far. Any other exception, including :class:`KeyboardInterrupt`, kills the
    process group before it propagates.
    """
    start = time.perf_counter()
    process = _start_process(command, implementation, subject=subject, error_type=error_type)
    standard_output_reader, standard_error_reader = _read_pipes(process)
    try:
        return_code, wall_seconds, timed_out = _wait_and_stop(process, start, timeout_seconds)
    except BaseException:  # Kill the child on any interruption, then let it propagate.
        _abandon_process(process, (standard_output_reader, standard_error_reader))
        raise
    deadline = time.monotonic() + _PIPE_DRAIN_SECONDS
    return _ProcessResult(
        return_code,
        standard_output_reader.collect(deadline),
        standard_error_reader.collect(deadline),
        wall_seconds,
        timed_out,
    )


def _require_normal_exit(
    process: "_ProcessResult", *, subject: str, timeout_seconds: float
) -> None:
    """Raise a :class:`RunnerError` unless ``process`` exited with code 0 before the timeout."""
    if process.timed_out:
        raise RunnerError(
            _with_output(
                _describe_timeout(subject, timeout_seconds),
                standard_error=process.standard_error,
            ),
            category=TIMEOUT_CATEGORY,
        )
    if process.return_code != 0:
        raise _runner_failure(
            subject,
            f"{_describe_exit(process.return_code)}.",
            category=_exit_category(process.return_code),
            standard_error=process.standard_error,
        )


def _require_output_file(output_path: Path, *, subject: str, standard_error: str) -> None:
    if output_path.is_file():
        return
    path_state = "is not a regular file" if output_path.exists() else "was not created"
    raise _runner_failure(
        subject,
        f"did not produce an output file: the output path {path_state}.",
        category="missing output",
        standard_error=standard_error,
    )


def _has_path_separator(command: str) -> bool:
    return os.sep in command or (os.altsep is not None and os.altsep in command)


def _explain_unrunnable_path(path: Path, command: str) -> str | None:
    """Say why the file at ``path`` cannot be run as ``command``, or return ``None``."""
    if not path.exists():
        return f"command not found: {command}"
    elif not path.is_file():
        return f"command is not a file: {command}"
    elif not os.access(path, os.X_OK):
        return (
            f"command is not runnable (permission denied): {command}. "
            "It needs to be executable (chmod +x), or run it through an interpreter."
        )
    else:
        return None


def _create_runner(
    problem: AnyProblem,
    implementation: Implementation,
    *,
    timeout_seconds: float,
    temporary_files: "TemporaryFilePolicy",
) -> "RunnerLike":
    return Runner(
        problem,
        implementation,
        timeout_seconds=timeout_seconds,
        temporary_files=temporary_files,
    )


class TemporaryFilePolicy(Enum):
    """What a runner does with the scratch directory of a run once the run is over."""

    DELETE = "delete"
    KEEP = "keep"


class RunnerError(RuntimeError):
    """Raised when an implementation run fails for any reason the runner can detect.

    ``category`` names the kind of failure (``timeout``, ``exit code 3``,
    ``signal SIGSEGV``, ``malformed output``, and so on) so that code which
    compares failures, such as the shrinker, can tell a different failure from
    the same one. ``temporary_directory`` is set when the run's scratch
    directory was kept (``TemporaryFilePolicy.KEEP``); the message then names it.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "error",
        temporary_directory: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.temporary_directory = temporary_directory

    def __str__(self) -> str:
        message = super().__str__()
        if self.temporary_directory is not None:
            message += f"\nTemporary files were kept in {self.temporary_directory}"
        return message


class BuildError(RunnerError):
    """Raised when an implementation's build command fails."""


@dataclass(frozen=True)
class RunResult(Generic[OutputT, TraceT]):
    """The artifacts and measurements produced by a single implementation run.

    ``wall_seconds`` runs from just before the process is started until the
    process itself exits. ``temporary_directory`` is the kept scratch
    directory, or ``None`` when it was deleted.
    """

    output: OutputT
    trace: TraceT | None
    # Why the trace file was rejected, when it existed but could not be decoded.
    trace_error: str | None
    wall_seconds: float
    cpu_user_seconds: float
    cpu_system_seconds: float
    standard_error: str
    temporary_directory: Path | None = None


class RunnerLike(Protocol):
    """What the engines need from a runner: run one input and return the result.

    :class:`Runner` is the real one. Engines accept a factory for other
    implementations so that their logic can be tested without starting
    processes.
    """

    def run(
        self, input_data: object, *, timeout_seconds: float | None = None
    ) -> RunResult[object, object]:
        """Run one input without asking for a trace.

        Args:
            input_data: The input to run.
            timeout_seconds: A timeout that replaces the runner's own for this run.

        Returns:
            The output and the measurements of the run.
        """
        ...

    def run_with_trace(
        self, input_data: object, *, timeout_seconds: float | None = None
    ) -> RunResult[object, object]:
        """Run one input and ask the implementation to write a trace.

        Args:
            input_data: The input to run.
            timeout_seconds: A timeout that replaces the runner's own for this run.

        Returns:
            The output and the measurements of the run, with the trace.
        """
        ...


RunnerFactory = Callable[[AnyProblem, Implementation], RunnerLike]


@dataclass(frozen=True)
class _ProcessResult:
    """What a command wrote and how it ended; ``timed_out`` means it was killed at the timeout."""

    return_code: int
    standard_output: str
    standard_error: str
    wall_seconds: float
    timed_out: bool


class _PipeReader:
    """Collect everything a child writes to one pipe on a background thread."""

    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream
        self._chunks: list[bytes] = []
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        try:
            while chunk := self._stream.read(_READ_CHUNK_BYTES):
                self._chunks.append(chunk)
        except (OSError, ValueError):
            # The pipe broke or was closed under the reader; keep what arrived before that.
            pass

    def collect(self, deadline: float) -> str:
        """Wait for the pipe to close and return what arrived.

        Args:
            deadline: The monotonic time until which to wait.

        Returns:
            Everything read so far, decoded as UTF-8 with undecodable bytes replaced.
        """
        self._thread.join(max(0.0, deadline - time.monotonic()))
        if not self._thread.is_alive():
            self._stream.close()
        return b"".join(self._chunks).decode("utf-8", errors="replace")


class Runner(Generic[InputT, OutputT, TraceT]):
    """Drive an implementation on inputs produced by a `Problem`.

    The runner manages temporary files and, unless the implementation asks to
    inherit the environment, ensures that the child process sees a minimal,
    deterministic environment so that benchmark results are reproducible
    across machines. The child's standard input is empty.
    """

    def __init__(
        self,
        problem: Problem[InputT, OutputT, TraceT],
        implementation: Implementation,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        temporary_files: TemporaryFilePolicy = TemporaryFilePolicy.DELETE,
    ) -> None:
        _require_valid_timeout(timeout_seconds)
        self._problem = problem
        self._implementation = implementation
        self._timeout_seconds = (
            implementation.timeout_seconds
            if implementation.timeout_seconds is not None
            else timeout_seconds
        )
        self._keeps_temporary_files = temporary_files is TemporaryFilePolicy.KEEP

    def run(
        self, input_data: InputT, *, timeout_seconds: float | None = None
    ) -> RunResult[OutputT, TraceT]:
        """Execute the implementation once and return its output and timings.

        Args:
            input_data: The input to run.
            timeout_seconds: A timeout that replaces the timeout of the runner
                for this run (the engines use it to keep a shrink within its
                time budget).

        Returns:
            The output and the measurements of the run.

        Raises:
            RunnerError: If the process cannot be started, times out, exits
                unsuccessfully, or leaves an output file that is missing or
                malformed, or if the problem cannot write the input.
            ValueError: If ``timeout_seconds`` is not a finite positive number.
        """
        with self._prepared_run(timeout_seconds) as (workspace, effective_timeout_seconds):
            return self._run_in(
                workspace,
                input_data,
                trace_path=None,
                timeout_seconds=effective_timeout_seconds,
            )

    def run_with_trace(
        self, input_data: InputT, *, timeout_seconds: float | None = None
    ) -> RunResult[OutputT, TraceT]:
        """Execute the implementation once with a trace path as its third argument.

        Behave like :meth:`run`, and also read the trace file the implementation
        wrote. A missing or empty trace file gives a result without a trace; a
        file that cannot be decoded gives a result whose ``trace_error`` says why.

        Args:
            input_data: The input to run.
            timeout_seconds: A timeout that replaces the timeout of the runner
                for this run.

        Returns:
            The output, the measurements and the trace of the run.

        Raises:
            RunnerError: As :meth:`run`.
            ValueError: If ``timeout_seconds`` is not a finite positive number.
        """
        with self._prepared_run(timeout_seconds) as (workspace, effective_timeout_seconds):
            return self._run_in(
                workspace,
                input_data,
                trace_path=workspace / TRACE_FILE_NAME,
                timeout_seconds=effective_timeout_seconds,
            )

    @contextmanager
    def _prepared_run(self, timeout_seconds: float | None) -> Iterator[tuple[Path, float]]:
        """Validate the run, create its scratch directory, and yield it with the timeout to use.

        A :class:`RunnerError` raised inside names the scratch directory when it is kept.
        """
        if timeout_seconds is not None:
            _require_valid_timeout(timeout_seconds)
        _require_working_directory(self._implementation, error_type=RunnerError)
        effective_timeout_seconds = (
            self._timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        with self._workspace() as workspace:
            try:
                yield workspace, effective_timeout_seconds
            except RunnerError as error:
                if self._keeps_temporary_files:
                    error.temporary_directory = workspace
                raise

    @contextmanager
    def _workspace(self) -> Iterator[Path]:
        directory = Path(tempfile.mkdtemp(prefix="algorithm-playground-"))
        try:
            yield directory
        finally:
            if not self._keeps_temporary_files:
                shutil.rmtree(directory, ignore_errors=True)

    def _run_in(
        self,
        workspace: Path,
        input_data: InputT,
        *,
        trace_path: Path | None,
        timeout_seconds: float,
    ) -> RunResult[OutputT, TraceT]:
        implementation = self._implementation
        subject = f"Implementation '{implementation.name}'"
        input_path = workspace / _INPUT_FILE_NAME
        output_path = workspace / _OUTPUT_FILE_NAME
        self._write_input(input_data, input_path)

        command = [*implementation.command, str(input_path), str(output_path)]
        if trace_path is not None:
            command.append(str(trace_path))
        usage_before = _children_cpu_seconds()
        process = _run_process(
            command,
            implementation,
            subject=subject,
            timeout_seconds=timeout_seconds,
            error_type=RunnerError,
        )
        usage_after = _children_cpu_seconds()
        _require_normal_exit(process, subject=subject, timeout_seconds=timeout_seconds)

        output = self._read_output(
            output_path, subject=subject, standard_error=process.standard_error
        )
        trace, trace_error = self._read_trace(trace_path, input_data)
        return RunResult(
            output=output,
            trace=trace,
            trace_error=trace_error,
            wall_seconds=process.wall_seconds,
            cpu_user_seconds=usage_after[0] - usage_before[0],
            cpu_system_seconds=usage_after[1] - usage_before[1],
            standard_error=process.standard_error,
            temporary_directory=workspace if self._keeps_temporary_files else None,
        )

    def _write_input(self, input_data: InputT, input_path: Path) -> None:
        try:
            self._problem.serialize_input(input_data, input_path)
        except Exception as error:  # The serialize_input hook is problem code.
            raise RunnerError(
                f"The problem's serialize_input hook could not write the input for "
                f"'{self._implementation.name}': {describe_error(error)}",
                category=SERIALIZATION_CATEGORY,
            ) from error

    def _read_output(self, output_path: Path, *, subject: str, standard_error: str) -> OutputT:
        _require_output_file(output_path, subject=subject, standard_error=standard_error)
        try:
            return self._problem.deserialize_output(output_path)
        except OSError as error:
            raise _runner_failure(
                subject,
                f"left an output file that could not be read: {error}",
                category="unreadable output",
                standard_error=standard_error,
            ) from error
        except (BinaryFormatError, OverflowError, MemoryError) as error:
            raise _runner_failure(
                subject,
                f"wrote a malformed output file: {error}",
                category="malformed output",
                standard_error=standard_error,
            ) from error
        except Exception as error:  # The deserialize_output hook is problem code.
            raise _runner_failure(
                subject,
                "wrote an output file that the problem's deserialize_output hook could not "
                f"read: {describe_error(error)}",
                category="malformed output",
                standard_error=standard_error,
            ) from error

    def _read_trace(
        self, trace_path: Path | None, input_data: InputT
    ) -> tuple[TraceT | None, str | None]:
        """Read the trace file; return the trace, or the reason it could not be decoded."""
        if trace_path is None or not trace_path.is_file() or trace_path.stat().st_size == 0:
            return None, None
        try:
            return self._problem.deserialize_trace(trace_path, input_data), None
        except (BinaryFormatError, OSError, OverflowError, MemoryError) as error:
            return None, str(error)
        except Exception as error:  # The deserialize_trace hook is problem code.
            return None, f"the problem's deserialize_trace hook raised {describe_error(error)}"


def subprocess_runner_factory(
    *,
    timeout_seconds: float,
    temporary_files: TemporaryFilePolicy = TemporaryFilePolicy.DELETE,
) -> RunnerFactory:
    """Build the factory of the real, process-spawning :class:`Runner`.

    An implementation's own ``timeout_seconds`` takes precedence over the one
    given here.

    Args:
        timeout_seconds: The timeout of every run.
        temporary_files: What each runner does with the scratch directory of a run.

    Returns:
        A factory that receives the problem and the implementation.
    """
    return functools.partial(
        _create_runner, timeout_seconds=timeout_seconds, temporary_files=temporary_files
    )


def build_implementation(
    implementation: Implementation,
    *,
    timeout_seconds: float = DEFAULT_BUILD_TIMEOUT_SECONDS,
) -> None:
    """Run the implementation's build command once; do nothing when it has none.

    Args:
        implementation: The implementation to build.
        timeout_seconds: How long the build may take.

    Raises:
        BuildError: If the command cannot be started, times out, or exits with
            a non-zero status. The message includes the captured output.
    """
    build_command = implementation.build_command
    if build_command is None:
        return
    _require_working_directory(implementation, error_type=BuildError)
    subject = f"Build of '{implementation.name}'"
    process = _run_process(
        build_command,
        implementation,
        subject=subject,
        timeout_seconds=timeout_seconds,
        error_type=BuildError,
    )
    if process.timed_out:
        raise BuildError(
            _with_output(
                _describe_timeout(subject, timeout_seconds),
                standard_error=process.standard_error,
                standard_output=process.standard_output,
            ),
            category=TIMEOUT_CATEGORY,
        )
    if process.return_code != 0:
        raise BuildError(
            _with_output(
                f"{subject} {_describe_exit(process.return_code)}.",
                standard_error=process.standard_error,
                standard_output=process.standard_output,
            )
        )


def check_can_start(implementation: Implementation) -> str | None:
    """Say why the command of ``implementation`` cannot be started.

    The check does not run anything: it looks for the program the way the
    operating system will (a name with a slash relative to the working
    directory, a bare name on the ``PATH`` of the environment the run uses) and
    asks whether it is a file the user may execute. A script whose first line
    names a missing interpreter passes it and fails when run.

    Args:
        implementation: The implementation whose command to check.

    Returns:
        The reason, or ``None`` when the command can be started.
    """
    directory = implementation.working_directory
    if directory is not None and not directory.is_dir():
        return f"working directory not found: {directory}"
    command = implementation.command[0]
    if _has_path_separator(command):
        path = Path(command)
        if not path.is_absolute():
            path = (directory if directory is not None else Path.cwd()) / path
        return _explain_unrunnable_path(path, command)
    path_variable = _child_environment(implementation).get("PATH")
    if shutil.which(command, path=path_variable) is None:
        return f"command not found: {command} (looked on the PATH, and it must be executable)"
    return None


def build_implementations(
    implementations: Sequence[Implementation],
    *,
    on_build_started: Callable[[Implementation], None] | None = None,
    on_build_failed: Callable[[Implementation, BuildError], None] | None = None,
) -> dict[str, BuildError]:
    """Build every implementation that has a build command, once each.

    A failing build does not stop the others.

    Args:
        implementations: The implementations to build.
        on_build_started: Called before each build, so a front end can show
            which implementation is being built.
        on_build_failed: Called right after a build fails.

    Returns:
        The failures keyed by implementation name, in the order of
        ``implementations``; empty when every build succeeded.
    """
    failures: dict[str, BuildError] = {}
    for implementation in implementations:
        if implementation.build_command is None:
            continue
        if on_build_started is not None:
            on_build_started(implementation)
        try:
            build_implementation(implementation)
        except BuildError as error:
            failures[implementation.name] = error
            if on_build_failed is not None:
                on_build_failed(implementation, error)
    return failures
