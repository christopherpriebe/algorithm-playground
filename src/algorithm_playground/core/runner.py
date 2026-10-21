"""Subprocess wrapper that invokes a user executable with the playground's I/O contract.

The contract is ``<executable> <input_path> <output_path> [<trace_path>]``.
The :class:`Runner` materializes the input via the problem's serializer,
spawns the executable, enforces a timeout, measures wall-clock and CPU time,
and surfaces stderr on failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generic

from algorithm_playground.core.binary_io import BinaryFormatError
from algorithm_playground.core.problem import InputT, OutputT, Problem, TraceT

DEFAULT_TIMEOUT_SECONDS = 60.0


class RunnerError(RuntimeError):
    """Raised when an executable run fails for any reason the runner can detect."""


@dataclass(frozen=True)
class RunResult(Generic[OutputT, TraceT]):
    """The artifacts and measurements produced by a single executable run."""

    output: OutputT
    trace: TraceT | None
    # Why the trace file was rejected, when it existed but could not be decoded.
    trace_error: str | None
    wall_seconds: float
    cpu_user_seconds: float
    cpu_system_seconds: float
    returncode: int
    stderr: str


class Runner(Generic[InputT, OutputT, TraceT]):
    """Drive a user executable on inputs produced by a `Problem`.

    The runner manages temporary files and ensures that the user executable
    sees a minimal, deterministic environment so that benchmark results are
    reproducible across machines.
    """

    def __init__(
        self,
        problem: Problem[InputT, OutputT, TraceT],
        executable: Path,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        keep_temporary_files: bool = False,
    ) -> None:
        self._problem = problem
        self._executable = executable.resolve()
        self._timeout_seconds = timeout_seconds
        self._keep_temporary_files = keep_temporary_files

    def run(self, input_data: InputT, *, collect_trace: bool = False) -> RunResult[OutputT, TraceT]:
        """Execute the program once and return its output and timings."""
        with self._workspace() as workspace:
            input_path = workspace / "input.bin"
            output_path = workspace / "output.bin"
            trace_path = workspace / "trace.bin" if collect_trace else None

            self._problem.serialize_input(input_data, input_path)

            command: list[str] = [str(self._executable), str(input_path), str(output_path)]
            if trace_path is not None:
                command.append(str(trace_path))

            usage_before = _children_cpu_seconds()
            wall_start = time.perf_counter()
            try:
                completed = subprocess.run(
                    command,
                    env=self._minimal_environment(),
                    capture_output=True,
                    timeout=self._timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as error:
                raise RunnerError(f"Executable not found: {self._executable}") from error
            except PermissionError as error:
                raise RunnerError(
                    f"Executable is not runnable (permission denied): {self._executable}"
                ) from error
            except subprocess.TimeoutExpired as error:
                raise RunnerError(
                    f"Executable timed out after {self._timeout_seconds:.3f}s"
                ) from error
            wall_seconds = time.perf_counter() - wall_start
            usage_after = _children_cpu_seconds()

            stderr = completed.stderr.decode("utf-8", errors="replace")
            if completed.returncode != 0:
                raise RunnerError(
                    f"Executable exited with code {completed.returncode}.\n"
                    f"stderr:\n{stderr.rstrip()}"
                )

            if not output_path.exists():
                raise RunnerError("Executable did not produce an output file at the expected path.")

            try:
                output = self._problem.deserialize_output(output_path)
            except BinaryFormatError as error:
                raise RunnerError(f"Executable wrote a malformed output file: {error}") from error

            trace: TraceT | None = None
            trace_error: str | None = None
            if trace_path is not None and trace_path.exists() and trace_path.stat().st_size > 0:
                try:
                    trace = self._problem.deserialize_trace(trace_path)
                except BinaryFormatError as error:
                    trace_error = str(error)

            return RunResult(
                output=output,
                trace=trace,
                trace_error=trace_error,
                wall_seconds=wall_seconds,
                cpu_user_seconds=usage_after[0] - usage_before[0],
                cpu_system_seconds=usage_after[1] - usage_before[1],
                returncode=completed.returncode,
                stderr=stderr,
            )

    @contextmanager
    def _workspace(self) -> Iterator[Path]:
        directory = Path(tempfile.mkdtemp(prefix="algorithm-playground-"))
        try:
            yield directory
        finally:
            if not self._keep_temporary_files:
                shutil.rmtree(directory, ignore_errors=True)

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        """Return a small, predictable environment for the child process."""
        preserved_keys = {"PATH", "LANG", "LC_ALL", "HOME", "TMPDIR"}
        environment: dict[str, str] = {
            key: value for key, value in os.environ.items() if key in preserved_keys
        }
        environment.setdefault("PATH", "/usr/bin:/bin")
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
