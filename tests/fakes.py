"""In-process stand-ins for the subprocess runner, so engine logic can be tested without processes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from instrumented_sort import Recording, insertion_sort, merge_sort

from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.problem import Problem
from algorithm_playground.core.runner import RunnerError, RunnerLike, RunResult
from algorithm_playground.problems.sorting import EventLog, SortingTrace

DEFAULT_DURATION = 0.001


@dataclass(frozen=True)
class TraceFailure:
    """What a ``traces`` function returns to model a trace file that could not be decoded."""

    message: str


class FakeRunners:
    """A runner factory whose runners call Python functions instead of starting processes.

    ``behaviors`` maps an implementation name to a function from the input to
    the output; a function may raise :class:`RunnerError` to model a failed
    run. ``durations`` maps a name to the wall time its runs report, either a
    number of seconds or a function from the input to seconds (default:
    one millisecond). ``traces`` maps a name to a function from the input to the
    trace that a run with ``collect_trace`` returns (default: no trace; the function
    may raise :class:`RunnerError` to model a traced run that fails, or return
    a :class:`TraceFailure` to model a malformed trace file). ``traced_behaviors``
    replaces the behavior of a name for runs that ask for a trace. Every
    call is recorded in ``calls`` as ``(implementation name, input)``,
    ``traced_calls`` lists the names of the calls that asked for a trace, and
    ``timeouts`` the timeout each call was given (``None`` for the default).
    """

    def __init__(
        self,
        behaviors: Mapping[str, Callable[[Any], Any]],
        durations: Mapping[str, float | Callable[[Any], float]] | None = None,
        traces: Mapping[str, Callable[[Any], Any]] | None = None,
        traced_behaviors: Mapping[str, Callable[[Any], Any]] | None = None,
    ) -> None:
        self._behaviors = dict(behaviors)
        self._traced_behaviors = dict(traced_behaviors or {})
        self._durations = dict(durations or {})
        self._traces = dict(traces or {})
        self.calls: list[tuple[str, Any]] = []
        self.traced_calls: list[str] = []
        self.timeouts: list[float | None] = []

    def __call__(
        self, problem: Problem[Any, Any, Any], implementation: Implementation
    ) -> RunnerLike:
        name = implementation.name
        return _FakeRunner(
            name,
            self._behaviors[name],
            self._traced_behaviors.get(name),
            self._durations.get(name, DEFAULT_DURATION),
            self._traces.get(name),
            self,
        )

    def inputs_of(self, implementation_name: str) -> list[Any]:
        return [data for name, data in self.calls if name == implementation_name]


class _FakeRunner:
    def __init__(
        self,
        name: str,
        behavior: Callable[[Any], Any],
        traced_behavior: Callable[[Any], Any] | None,
        duration: float | Callable[[Any], float],
        tracer: Callable[[Any], Any] | None,
        owner: FakeRunners,
    ) -> None:
        self._name = name
        self._behavior = behavior
        self._traced_behavior = traced_behavior
        self._duration = duration
        self._tracer = tracer
        self._owner = owner

    def run(
        self,
        input_data: Any,
        *,
        collect_trace: bool = False,
        timeout_seconds: float | None = None,
    ) -> RunResult[Any, Any]:
        self._owner.calls.append((self._name, input_data))
        self._owner.timeouts.append(timeout_seconds)
        if collect_trace:
            self._owner.traced_calls.append(self._name)
        trace = self._tracer(input_data) if collect_trace and self._tracer is not None else None
        trace_error = None
        if isinstance(trace, TraceFailure):
            trace, trace_error = None, trace.message
        behavior = (
            self._traced_behavior if collect_trace and self._traced_behavior else self._behavior
        )
        return RunResult(
            output=behavior(input_data),
            trace=trace,
            trace_error=trace_error,
            wall_seconds=self._wall_seconds(input_data),
            cpu_user_seconds=0.0,
            cpu_system_seconds=0.0,
            standard_error="",
        )

    def _wall_seconds(self, input_data: Any) -> float:
        if isinstance(self._duration, int | float):
            return float(self._duration)
        return self._duration(input_data)


def named(*names: str) -> list[Implementation]:
    """Return implementations with the given names (their command is never run)."""
    return [Implementation(name=name, command=("fake",)) for name in names]


def sort_correctly(values: list[int]) -> list[int]:
    return sorted(values)


def drop_last_above_five(values: list[int]) -> list[int]:
    """A wrong sorter: loses the last element when the input has more than five elements."""
    result = sorted(values)
    return result[:-1] if len(values) > 5 else result


def crash(values: list[int]) -> list[int]:
    raise RunnerError("Implementation 'crash' exited with code 3.\nstandard error:\nkaboom")


def _trace_of(recording: Recording, values: list[int]) -> SortingTrace:
    records = b"".join(
        bytes([kind]) + first.to_bytes(4, "little") + second.to_bytes(4, "little")
        for kind, first, second in recording.events
    )
    return SortingTrace((), EventLog.from_records(records))


def insertion_sort_trace(values: list[int]) -> SortingTrace:
    """The event trace of an instrumented insertion sort of ``values``."""
    return _trace_of(insertion_sort(values), values)


def merge_sort_trace(values: list[int]) -> SortingTrace:
    """The event trace of an instrumented merge sort of ``values``."""
    return _trace_of(merge_sort(values), values)


def snapshot_only_trace(values: list[int]) -> SortingTrace:
    """A trace with the input and the sorted output as snapshots and no events."""
    return SortingTrace((tuple(values), tuple(sorted(values))))
