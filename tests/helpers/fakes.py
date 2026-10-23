"""In-process stand-ins for the subprocess runner, so engine logic can be tested without processes."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from algorithm_playground.core import (
    Implementation,
    Problem,
    RunnerError,
    RunnerLike,
    RunResult,
)
from algorithm_playground.problems.sorting import EventLog, SortingTrace
from helpers.instrumented_sort import Recording, insertion_sort, merge_sort

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
    trace that a run with a trace (``run_with_trace``) returns (default: no trace; the function
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
        self,
        problem: Problem[Any, Any, Any],  # noqa: ARG002  signature fixed by the factory contract
        implementation: Implementation,
    ) -> RunnerLike:
        name = implementation.name
        return _FakeRunner(
            name,
            self._behaviors[name],
            traced_behavior=self._traced_behaviors.get(name),
            duration=self._durations.get(name, DEFAULT_DURATION),
            tracer=self._traces.get(name),
            owner=self,
        )

    def collect_inputs_of(self, implementation_name: str) -> list[Any]:
        """Return the inputs the named implementation received, in call order."""
        return [data for name, data in self.calls if name == implementation_name]


class _FakeRunner:
    """A runner that answers from the behaviors of its :class:`FakeRunners` owner."""

    def __init__(  # noqa: PLR0913  one value per behavior the owner configures
        self,
        name: str,
        behavior: Callable[[Any], Any],
        *,
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
        self, input_data: object, *, timeout_seconds: float | None = None
    ) -> RunResult[object, object]:
        self._record_call(input_data, timeout_seconds)
        return self._result(input_data, self._behavior, trace=None, trace_error=None)

    def run_with_trace(
        self, input_data: object, *, timeout_seconds: float | None = None
    ) -> RunResult[object, object]:
        self._record_call(input_data, timeout_seconds)
        self._owner.traced_calls.append(self._name)
        trace = self._tracer(input_data) if self._tracer is not None else None
        trace_error = None
        if isinstance(trace, TraceFailure):
            trace, trace_error = None, trace.message
        behavior = self._traced_behavior or self._behavior
        return self._result(input_data, behavior, trace=trace, trace_error=trace_error)

    def _record_call(self, input_data: object, timeout_seconds: float | None) -> None:
        self._owner.calls.append((self._name, input_data))
        self._owner.timeouts.append(timeout_seconds)

    def _result(
        self,
        input_data: object,
        behavior: Callable[[Any], Any],
        *,
        trace: object,
        trace_error: str | None,
    ) -> RunResult[object, object]:
        return RunResult(
            output=behavior(input_data),
            trace=trace,
            trace_error=trace_error,
            wall_seconds=self._wall_seconds(input_data),
            cpu_user_seconds=0.0,
            cpu_system_seconds=0.0,
            standard_error="",
        )

    def _wall_seconds(self, input_data: object) -> float:
        if isinstance(self._duration, int | float):
            return float(self._duration)
        return self._duration(input_data)


def build_named_implementations(*names: str) -> list[Implementation]:
    """Build implementations with the given names (their command is never run)."""
    return [Implementation(name=name, command=("fake",)) for name in names]


def sort_correctly(values: list[int]) -> list[int]:
    """Sort the values, as a correct implementation does."""
    return sorted(values)


def drop_last_above_five(values: list[int]) -> list[int]:
    """Sort the values but lose the last one when there are more than five."""
    result = sorted(values)
    return result[:-1] if len(values) > 5 else result


def crash(values: list[int]) -> list[int]:  # noqa: ARG001  signature fixed by the behavior contract
    """Fail the way a runner reports an implementation that exited with an error."""
    message = "Implementation 'crash' exited with code 3.\nstandard error:\nkaboom"
    raise RunnerError(message)


def _build_trace(recording: Recording) -> SortingTrace:
    """Encode the events of a recording the way a trace file holds them."""
    records = b"".join(
        bytes([kind]) + first.to_bytes(4, "little") + second.to_bytes(4, "little")
        for kind, first, second in recording.events
    )
    return SortingTrace((), events=EventLog.from_records(records))


def build_insertion_sort_trace(values: list[int]) -> SortingTrace:
    """Build the event trace of an instrumented insertion sort of ``values``."""
    return _build_trace(insertion_sort(values))


def build_merge_sort_trace(values: list[int]) -> SortingTrace:
    """Build the event trace of an instrumented merge sort of ``values``."""
    return _build_trace(merge_sort(values))


def build_snapshot_only_trace(values: list[int]) -> SortingTrace:
    """Build a trace with the input and the sorted output as snapshots and no events."""
    return SortingTrace((tuple(values), tuple(sorted(values))))
