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

from __future__ import annotations

import contextlib
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
from pathlib import Path
from typing import IO, Any, Generic, Protocol

from algorithm_playground.core._support import describe_error
from algorithm_playground.core.binary_format import BinaryFormatError
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.problem import InputT, OutputT, Problem, TraceT

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_BUILD_TIMEOUT_SECONDS = 300.0
TIMEOUT_CATEGORY = "timeout"
SERIALIZATION_CATEGORY = "serialization"

_SUPPORTS_PROCESS_GROUPS = hasattr(os, "killpg")
# How long to wait for a pipe to close after the process group was killed.
_PIPE_DRAIN_SECONDS = 2.0
_READ_CHUNK_BYTES = 64 * 1024
_MAXIMUM_REPORTED_CHARACTERS = 20_000


class RunnerError(RuntimeError):
    """Raised when an implementation run fails for any reason the runner can detect.

    ``category`` names the kind of failure (``timeout``, ``exit code 3``,
    ``signal SIGSEGV``, ``malformed output``, and so on) so that code which
    compares failures, such as the shrinker, can tell a different failure from
    the same one. ``temporary_directory`` is set when the run's scratch
    directory was kept (``keep_temporary_files``); the message then names it.
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
    processes. ``timeout_seconds`` replaces the runner's own timeout for this
    run.
    """

    def run(
        self,
        input_data: Any,
        *,
        collect_trace: bool = False,
        timeout_seconds: float | None = None,
    ) -> RunResult[Any, Any]: ...


RunnerFactory = Callable[[Problem[Any, Any, Any], Implementation], RunnerLike]


@dataclass(frozen=True)
class _ProcessResult:
    return_code: int
    standard_output: str
    standard_error: str
    wall_seconds: float


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
        keep_temporary_files: bool = False,
    ) -> None:
        _require_valid_timeout(timeout_seconds)
        self._problem = problem
        self._implementation = implementation
        self._timeout_seconds = (
            implementation.timeout_seconds
            if implementation.timeout_seconds is not None
            else timeout_seconds
        )
        self._keep_temporary_files = keep_temporary_files

    def run(
        self,
        input_data: InputT,
        *,
        collect_trace: bool = False,
        timeout_seconds: float | None = None,
    ) -> RunResult[OutputT, TraceT]:
        """Execute the implementation once and return its output and timings.

        ``timeout_seconds`` replaces the timeout of the runner for this run
        (the engines use it to keep a shrink within its time budget). Raise
        :class:`RunnerError` when the process cannot be started, times out,
        exits unsuccessfully, or leaves an output file that is missing or
        malformed, and when the problem cannot write the input.
        """
        if timeout_seconds is not None:
            _require_valid_timeout(timeout_seconds)
        _require_working_directory(self._implementation)
        with self._workspace() as workspace:
            try:
                return self._run_in(
                    workspace,
                    input_data,
                    collect_trace=collect_trace,
                    timeout_seconds=(
                        self._timeout_seconds if timeout_seconds is None else timeout_seconds
                    ),
                )
            except RunnerError as error:
                if self._keep_temporary_files:
                    error.temporary_directory = workspace
                raise

    def _run_in(
        self,
        workspace: Path,
        input_data: InputT,
        *,
        collect_trace: bool,
        timeout_seconds: float,
    ) -> RunResult[OutputT, TraceT]:
        implementation = self._implementation
        subject = f"Implementation '{implementation.name}'"
        input_path = workspace / "input.bin"
        output_path = workspace / "output.bin"
        trace_path = workspace / "trace.bin" if collect_trace else None

        try:
            self._problem.serialize_input(input_data, input_path)
        except Exception as error:
            raise RunnerError(
                f"The problem's serialize_input hook could not write the input for "
                f"'{implementation.name}': {describe_error(error)}",
                category=SERIALIZATION_CATEGORY,
            ) from error

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

        standard_error = process.standard_error

        def failure(reason: str, category: str) -> RunnerError:
            return RunnerError(
                _with_output(f"{subject} {reason}", standard_error=standard_error),
                category=category,
            )

        if process.return_code != 0:
            raise failure(
                f"{_describe_exit(process.return_code)}.", _exit_category(process.return_code)
            )

        if not output_path.is_file():
            path_state = "is not a regular file" if output_path.exists() else "was not created"
            raise failure(
                f"did not produce an output file: the output path {path_state}.", "missing output"
            )

        try:
            output = self._problem.deserialize_output(output_path)
        except OSError as error:
            raise failure(
                f"left an output file that could not be read: {error}", "unreadable output"
            ) from error
        except (BinaryFormatError, OverflowError, MemoryError) as error:
            raise failure(f"wrote a malformed output file: {error}", "malformed output") from error
        except Exception as error:
            raise failure(
                f"wrote an output file that the problem's deserialize_output hook could not "
                f"read: {describe_error(error)}",
                "malformed output",
            ) from error

        trace: TraceT | None = None
        trace_error: str | None = None
        if trace_path is not None and trace_path.is_file() and trace_path.stat().st_size > 0:
            try:
                trace = self._problem.deserialize_trace(trace_path, input_data)
            except (BinaryFormatError, OSError, OverflowError, MemoryError) as error:
                trace_error = str(error)
            except Exception as error:
                trace_error = f"the problem's deserialize_trace hook raised {describe_error(error)}"

        return RunResult(
            output=output,
            trace=trace,
            trace_error=trace_error,
            wall_seconds=process.wall_seconds,
            cpu_user_seconds=usage_after[0] - usage_before[0],
            cpu_system_seconds=usage_after[1] - usage_before[1],
            standard_error=standard_error,
            temporary_directory=workspace if self._keep_temporary_files else None,
        )

    @contextmanager
    def _workspace(self) -> Iterator[Path]:
        directory = Path(tempfile.mkdtemp(prefix="algorithm-playground-"))
        try:
            yield directory
        finally:
            if not self._keep_temporary_files:
                shutil.rmtree(directory, ignore_errors=True)


def subprocess_runner_factory(
    *, timeout_seconds: float, keep_temporary_files: bool = False
) -> RunnerFactory:
    """Return the factory that builds the real, process-spawning :class:`Runner`.

    An implementation's own ``timeout_seconds`` takes precedence over the one
    given here.
    """

    def create(problem: Problem[Any, Any, Any], implementation: Implementation) -> RunnerLike:
        return Runner(
            problem,
            implementation,
            timeout_seconds=timeout_seconds,
            keep_temporary_files=keep_temporary_files,
        )

    return create


def build_implementation(
    implementation: Implementation,
    *,
    timeout_seconds: float = DEFAULT_BUILD_TIMEOUT_SECONDS,
) -> None:
    """Run the implementation's build command once; do nothing when it has none.

    Raise :class:`BuildError`, including the captured output, if the command
    cannot be started, times out, or exits with a non-zero status.
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
        show_standard_output=True,
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
    """Say why the command of ``implementation`` cannot be started, or return ``None``.

    The check does not run anything: it looks for the program the way the
    operating system will (a name with a slash relative to the working
    directory, a bare name on the ``PATH`` of the environment the run uses) and
    asks whether it is a file the user may execute. A script whose first line
    names a missing interpreter passes it and fails when run.
    """
    directory = implementation.working_directory
    if directory is not None and not directory.is_dir():
        return f"working directory not found: {directory}"
    command = implementation.command[0]
    if os.sep in command or (os.altsep is not None and os.altsep in command):
        path = Path(command)
        if not path.is_absolute():
            path = (directory if directory is not None else Path.cwd()) / path
        if not path.exists():
            return f"command not found: {command}"
        if not path.is_file():
            return f"command is not a file: {command}"
        if not os.access(path, os.X_OK):
            return (
                f"command is not runnable (permission denied): {command}. "
                "It needs to be executable (chmod +x), or run it through an interpreter."
            )
        return None
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

    A failing build does not stop the others. Return the failures keyed by
    implementation name, in the order of ``implementations``; the dictionary
    is empty when every build succeeded. ``on_build_started`` is called before
    each build so a front end can show which implementation is being built,
    and ``on_build_failed`` right after a build fails.
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
            pass

    def collect(self, deadline: float) -> str:
        """Wait for the pipe to close until ``deadline`` (a monotonic time); return what arrived."""
        self._thread.join(max(0.0, deadline - time.monotonic()))
        if not self._thread.is_alive():
            self._stream.close()
        return b"".join(self._chunks).decode("utf-8", errors="replace")


def _run_process(
    command: Sequence[str],
    implementation: Implementation,
    *,
    subject: str,
    timeout_seconds: float,
    error_type: type[RunnerError],
    show_standard_output: bool = False,
) -> _ProcessResult:
    """Run ``command`` in the working directory and environment of ``implementation``.

    ``subject`` names what is running in error messages. The command gets
    empty standard input and its own process group. Raise ``error_type`` when
    the command cannot be started or exceeds the timeout; the message includes
    the standard error (and the standard output when ``show_standard_output``
    is set) written so far. Any other exception, including
    :class:`KeyboardInterrupt`, kills the process group before it propagates.
    """
    start = time.perf_counter()
    try:
        process = subprocess.Popen(
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

    assert process.stdout is not None
    assert process.stderr is not None
    readers = (_PipeReader(process.stdout), _PipeReader(process.stderr))
    return_code: int | None = None
    try:
        with contextlib.suppress(subprocess.TimeoutExpired):
            return_code = process.wait(timeout=timeout_seconds)
        wall_seconds = time.perf_counter() - start
        _kill_process_group(process)
        if return_code is None:
            process.wait()
    except BaseException:
        _kill_process_group(process)
        with contextlib.suppress(Exception):
            process.wait()
        deadline = time.monotonic() + _PIPE_DRAIN_SECONDS
        for reader in readers:
            reader.collect(deadline)
        raise

    deadline = time.monotonic() + _PIPE_DRAIN_SECONDS
    standard_output = readers[0].collect(deadline)
    standard_error = readers[1].collect(deadline)
    if return_code is None:
        raise error_type(
            _with_output(
                f"{subject} timed out after {timeout_seconds:.3f}s",
                standard_error=standard_error,
                standard_output=standard_output if show_standard_output else None,
            ),
            category=TIMEOUT_CATEGORY,
        )
    return _ProcessResult(return_code, standard_output, standard_error, wall_seconds)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Kill the child and every process it started that is still in its process group."""
    with contextlib.suppress(OSError):
        if _SUPPORTS_PROCESS_GROUPS:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()


def _start_hint(error: OSError) -> str:
    if error.errno == 8:  # ENOEXEC: not a program the operating system can run
        return (
            " (a script needs a first line such as '#!/usr/bin/env python3', or run it "
            "through its interpreter, for example --command 'python3 sort.py')"
        )
    return ""


def _exit_category(return_code: int) -> str:
    if return_code >= 0:
        return f"exit code {return_code}"
    try:
        return f"signal {signal.Signals(-return_code).name}"
    except ValueError:
        return f"signal {-return_code}"


def _require_valid_timeout(timeout_seconds: float) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(f"Timeout must be a finite positive number, got {timeout_seconds}")


def _describe_exit(return_code: int) -> str:
    if return_code >= 0:
        return f"exited with code {return_code}"
    try:
        name = signal.Signals(-return_code).name
    except ValueError:
        name = str(-return_code)
    return f"was terminated by signal {name}"


def _with_output(message: str, *, standard_error: str, standard_output: str | None = None) -> str:
    """Append the non-blank captured output streams to ``message`` under labels."""
    parts = [message]
    if standard_output is not None and standard_output.strip():
        parts.append(f"standard output:\n{_tail(standard_output.rstrip())}")
    if standard_error.strip():
        parts.append(f"standard error:\n{_tail(standard_error.rstrip())}")
    return "\n".join(parts)


def _tail(text: str) -> str:
    if len(text) <= _MAXIMUM_REPORTED_CHARACTERS:
        return text
    omitted = len(text) - _MAXIMUM_REPORTED_CHARACTERS
    return f"(first {omitted} characters omitted)\n{text[omitted:]}"


def _require_working_directory(
    implementation: Implementation, *, error_type: type[RunnerError] = RunnerError
) -> None:
    directory = implementation.working_directory
    if directory is not None and not directory.is_dir():
        raise error_type(
            f"Implementation '{implementation.name}': working directory not found: {directory}"
        )


def _child_environment(implementation: Implementation) -> dict[str, str]:
    """Return the environment for a child process of ``implementation``.

    By default that is a small, predictable subset of the caller's environment;
    with ``inherit_environment`` it is all of it. The variables of the
    implementation's own ``environment`` are added on top.
    """
    if implementation.inherit_environment:
        environment = dict(os.environ)
    else:
        preserved_keys = {"PATH", "LANG", "LC_ALL", "HOME", "TMPDIR"}
        environment = {key: value for key, value in os.environ.items() if key in preserved_keys}
        environment.setdefault("PATH", "/usr/bin:/bin")
    environment.update(implementation.environment)
    return environment


def _children_cpu_seconds() -> tuple[float, float]:
    """Return cumulative (user, system) CPU seconds across all reaped children.

    Uses :mod:`resource` when available (POSIX). On platforms without the
    module, returns ``(0.0, 0.0)``. Callers should subtract a "before" sample
    from an "after" sample to get the cost of a single subprocess.
    """
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        return usage.ru_utime, usage.ru_stime
    except (ImportError, OSError):
        return 0.0, 0.0
