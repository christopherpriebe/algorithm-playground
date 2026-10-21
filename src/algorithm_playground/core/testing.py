"""Test engine: run a list of cases against several implementations and explain failures.

For every case and every implementation the engine runs the implementation,
verifies the output with the problem, and records a :class:`CaseOutcome`. A
failing outcome carries a :class:`FailureDetail` (the input, the expected
output when the problem knows it, and the actual output, described through
the problem's hooks). When a *generated* case fails the engine also shrinks
it: it asks the problem for smaller variants of the input
(:meth:`~algorithm_playground.core.problem.Problem.shrink`), runs them
against the same implementation, and keeps any that fail *the same way* (the
same status and, for an error, the same kind of error), within a cap on
candidates and a time budget per implementation. The smallest failing input
found is attached as a :class:`ShrunkFailure`. A candidate that the problem's
``check_input`` rejects is skipped, and when shrinking ends because its budget
ran out, the outcome says so in ``shrink_note``. A failure that the problem's
own hooks cause (a ``serialize_input`` or a ``verify`` that raises) is not
shrunk, and neither is a timeout when the time left for shrinking is shorter
than the timeout; the note says so.

The engine returns plain result objects and never prints, so the CLI (or any
other front end) decides how to render them. Runs go through a runner
factory, which tests replace with an in-process fake.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, ClassVar

from algorithm_playground.core._support import describe_error, validate_implementations
from algorithm_playground.core.cases import Case, GeneratedOrigin, ShrunkOrigin
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.problem import Problem
from algorithm_playground.core.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_CATEGORY,
    RunnerFactory,
    RunnerLike,
    subprocess_runner_factory,
)
from algorithm_playground.core.single_run import (
    PROBLEM_HOOK_CATEGORIES,
    CaseStatus,
    SingleRun,
    run_single,
)

DEFAULT_MAXIMUM_SHRUNK_CASES = 3
DEFAULT_MAXIMUM_SHRINK_RUNS = 200
DEFAULT_SHRINK_TIME_BUDGET_SECONDS = 30.0
DEFAULT_DESCRIPTION_LIMIT = 300


class CasePhase(Enum):
    """What the engine is doing for one implementation and case."""

    RUNNING = "running"
    SHRINKING = "shrinking"
    COMPLETED = "completed"


@dataclass(frozen=True)
class CaseProgress:
    """A progress event: the engine started, is shrinking, or completed one case.

    ``outcome`` is set when ``phase`` is ``COMPLETED``; it is final and
    includes the shrunk failure when shrinking found one.
    """

    implementation_name: str
    case_identifier: str
    phase: CasePhase
    outcome: CaseOutcome | None = None


@dataclass(frozen=True)
class FailureDetail:
    """A failing run described for people: the input, the expected output, the actual output.

    ``expected_text`` is ``None`` when the problem knows no expected output,
    and ``actual_text`` is ``None`` when the run produced no output.
    """

    input_text: str
    expected_text: str | None
    actual_text: str | None


@dataclass(frozen=True)
class ShrunkFailure:
    """The smallest failing input that shrinking found, and how it failed."""

    case: Case[Any]
    message: str
    detail: FailureDetail


@dataclass(frozen=True)
class CaseOutcome:
    """The result of one implementation on one case.

    ``FAILED`` means the run completed but verification rejected the output;
    ``ERROR`` means the run or the verification itself failed. ``message`` is
    empty on success and names the kept scratch directory when the engine was
    asked to keep temporary files. ``detail`` is set for every non-passing
    outcome, and ``shrunk`` when shrinking found a smaller failing input.
    ``shrink_note`` says why shrinking did not do its job or did not finish,
    for example that the problem's ``shrink`` hook raised or that its budget
    ran out; it is ``None`` otherwise. ``category`` says what kind of failure it
    was (see :class:`~algorithm_playground.core.single_run.SingleRun`).
    """

    case: Case[Any]
    implementation_name: str
    status: CaseStatus
    message: str
    detail: FailureDetail | None = None
    shrunk: ShrunkFailure | None = None
    shrink_note: str | None = None
    category: str = ""

    @property
    def case_identifier(self) -> str:
        return self.case.identifier


@dataclass(frozen=True)
class TestSettings:
    """The limits a test run worked within, recorded in its report."""

    __test__: ClassVar[bool] = False  # Tell pytest not to collect this as a test class.

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    shrink: bool = True
    maximum_shrunk_cases: int = DEFAULT_MAXIMUM_SHRUNK_CASES
    maximum_shrink_runs: int = DEFAULT_MAXIMUM_SHRINK_RUNS
    shrink_time_budget_seconds: float = DEFAULT_SHRINK_TIME_BUDGET_SECONDS


@dataclass(frozen=True)
class TestReport:
    """All outcomes of a test run, one per case and implementation."""

    __test__: ClassVar[bool] = False  # Tell pytest not to collect this as a test class.

    problem_name: str
    implementation_names: tuple[str, ...]
    cases: tuple[Case[Any], ...]
    outcomes: tuple[CaseOutcome, ...]
    settings: TestSettings = field(default_factory=TestSettings)
    _index: dict[tuple[str, str], CaseOutcome] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        self._index.update(
            ((outcome.case_identifier, outcome.implementation_name), outcome)
            for outcome in self.outcomes
        )

    @property
    def case_identifiers(self) -> tuple[str, ...]:
        """The identifiers of the cases, in run order."""
        return tuple(case.identifier for case in self.cases)

    def outcome(self, case_identifier: str, implementation_name: str) -> CaseOutcome:
        """Return the outcome for one case and implementation."""
        try:
            return self._index[(case_identifier, implementation_name)]
        except KeyError:
            raise KeyError(
                f"No outcome for case '{case_identifier}' and "
                f"implementation '{implementation_name}'"
            ) from None

    def outcomes_for(self, implementation_name: str) -> tuple[CaseOutcome, ...]:
        """Return the outcomes of one implementation, in case order."""
        return tuple(
            outcome
            for outcome in self.outcomes
            if outcome.implementation_name == implementation_name
        )

    def failures(self) -> tuple[CaseOutcome, ...]:
        """Return every outcome that is not a pass."""
        return tuple(
            outcome for outcome in self.outcomes if outcome.status is not CaseStatus.PASSED
        )

    @property
    def passed(self) -> bool:
        """Whether every implementation passed every case."""
        return not self.failures()


@dataclass
class _ImplementationState:
    """What the engine tracks for one implementation while it runs the cases."""

    runner: RunnerLike
    timeout_seconds: float
    shrink_seconds_left: float
    shrink_seconds_total: float
    shrunk_count: int = 0


class _ShrinkBudget:
    """The candidates and the time that one shrink may still spend.

    ``exhausted`` says which of the two ran out, once one did.
    """

    def __init__(self, maximum_candidates: int, time_budget_seconds: float) -> None:
        self.maximum_candidates = maximum_candidates
        self._candidates_left = maximum_candidates
        self._deadline = time.monotonic() + time_budget_seconds
        self.exhausted: str | None = None

    def take_candidate(self) -> bool:
        """Spend one candidate; return ``False`` when the cap or the time is used up.

        Every candidate counts, including one that equals its input or is
        rejected by ``check_input`` and is skipped, so a hook that never stops
        yielding cannot keep a shrink going.
        """
        if self._candidates_left <= 0:
            self.exhausted = "candidates"
            return False
        if self.remaining_seconds() <= 0:
            self.exhausted = "time"
            return False
        self._candidates_left -= 1
        return True

    def remaining_seconds(self) -> float:
        return self._deadline - time.monotonic()


def run_tests(
    problem: Problem[Any, Any, Any],
    implementations: Sequence[Implementation],
    cases: Sequence[Case[Any]],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    keep_temporary_files: bool = False,
    shrink: bool = True,
    maximum_shrunk_cases: int = DEFAULT_MAXIMUM_SHRUNK_CASES,
    maximum_shrink_runs: int = DEFAULT_MAXIMUM_SHRINK_RUNS,
    shrink_time_budget_seconds: float = DEFAULT_SHRINK_TIME_BUDGET_SECONDS,
    description_limit: int = DEFAULT_DESCRIPTION_LIMIT,
    runner_factory: RunnerFactory | None = None,
    on_progress: Callable[[CaseProgress], None] | None = None,
) -> TestReport:
    """Run every case of ``cases`` against each implementation.

    Outcomes are produced case by case, and for each case in the order of
    ``implementations``. ``on_progress`` receives an event when a run starts,
    when shrinking starts, and when an outcome is complete.

    With ``shrink`` set, failing generated cases are shrunk against the
    implementation that failed them, in case order (which is by growing size
    for planned cases), for at most ``maximum_shrunk_cases`` cases per
    implementation; later failures are reported unshrunk. One shrink performs
    at most ``maximum_shrink_runs`` runs, and each implementation has
    ``shrink_time_budget_seconds`` of shrinking in total. Descriptions are
    shortened to about ``description_limit`` characters. ``runner_factory``
    replaces the process-spawning runner (it receives the problem and the
    implementation).
    """
    validate_implementations(implementations)
    _validate_cases(cases)
    factory = runner_factory or subprocess_runner_factory(
        timeout_seconds=timeout_seconds, keep_temporary_files=keep_temporary_files
    )
    states = {
        implementation.name: _ImplementationState(
            factory(problem, implementation),
            (
                implementation.timeout_seconds
                if implementation.timeout_seconds is not None
                else timeout_seconds
            ),
            shrink_time_budget_seconds,
            shrink_time_budget_seconds,
        )
        for implementation in implementations
    }

    def report(event: CaseProgress) -> None:
        if on_progress is not None:
            on_progress(event)

    outcomes: list[CaseOutcome] = []
    for case in cases:
        for name, state in states.items():
            report(CaseProgress(name, case.identifier, CasePhase.RUNNING))
            attempt = run_single(problem, state.runner, case.input_data)
            outcome = CaseOutcome(
                case,
                name,
                attempt.status,
                attempt.message,
                detail=(
                    None
                    if attempt.status is CaseStatus.PASSED
                    else describe_failure(problem, case.input_data, attempt, description_limit)
                ),
                category=attempt.category,
            )
            if shrink and attempt.status is not CaseStatus.PASSED:
                outcome = _shrunk_outcome(
                    problem,
                    state,
                    case,
                    attempt,
                    outcome,
                    maximum_shrunk_cases=maximum_shrunk_cases,
                    maximum_candidates=maximum_shrink_runs,
                    description_limit=description_limit,
                    on_shrinking=lambda name=name, case=case: report(
                        CaseProgress(name, case.identifier, CasePhase.SHRINKING)
                    ),
                )
            outcomes.append(outcome)
            report(CaseProgress(name, case.identifier, CasePhase.COMPLETED, outcome))

    return TestReport(
        problem_name=problem.name,
        implementation_names=tuple(states),
        cases=tuple(cases),
        outcomes=tuple(outcomes),
        settings=TestSettings(
            timeout_seconds=timeout_seconds,
            shrink=shrink,
            maximum_shrunk_cases=maximum_shrunk_cases,
            maximum_shrink_runs=maximum_shrink_runs,
            shrink_time_budget_seconds=shrink_time_budget_seconds,
        ),
    )


def _validate_cases(cases: Sequence[Case[Any]]) -> None:
    """Require at least one case and unique identifiers."""
    if not cases:
        raise ValueError("At least one case is required")
    counts = Counter(case.identifier for case in cases)
    repeated = sorted(identifier for identifier, count in counts.items() if count > 1)
    if repeated:
        raise ValueError(f"Case identifiers must be unique, but these were repeated: {repeated}")


def describe_failure(
    problem: Problem[Any, Any, Any], input_data: Any, attempt: SingleRun, limit: int
) -> FailureDetail:
    """Describe a failing attempt through the problem's hooks, each in at most about ``limit`` characters.

    A hook that raises does not take the description down; its text says that it
    could not describe. The position ``verify`` named as the focus is passed to
    ``describe_output``, for the expected output as well as for the actual one.
    """
    return FailureDetail(
        input_text=_describe_safely(lambda: problem.describe_input(input_data, limit=limit)),
        expected_text=_describe_expected_output(problem, input_data, limit, attempt.focus),
        actual_text=(
            _describe_safely(
                lambda: _describe_output(problem, attempt.output, limit, attempt.focus)
            )
            if attempt.has_output
            else None
        ),
    )


def _describe_output(
    problem: Problem[Any, Any, Any], output: Any, limit: int, focus: int | None
) -> str:
    if focus is None:
        return problem.describe_output(output, limit=limit)
    return problem.describe_output(output, limit=limit, focus=focus)


def _describe_expected_output(
    problem: Problem[Any, Any, Any], input_data: Any, limit: int, focus: int | None
) -> str | None:
    try:
        expected = problem.expected_output(input_data)
    except Exception as error:
        return _could_not_describe(error)
    if expected is None:
        return None
    return _describe_safely(lambda: _describe_output(problem, expected, limit, focus))


def _describe_safely(describe: Callable[[], str]) -> str:
    """Run a describe hook; a hook that raises must not take the whole report down."""
    try:
        return describe()
    except Exception as error:
        return _could_not_describe(error)


def _could_not_describe(error: Exception) -> str:
    return f"(could not describe: {describe_error(error)})"


def _shrunk_outcome(
    problem: Problem[Any, Any, Any],
    state: _ImplementationState,
    case: Case[Any],
    attempt: SingleRun,
    outcome: CaseOutcome,
    *,
    maximum_shrunk_cases: int,
    maximum_candidates: int,
    description_limit: int,
    on_shrinking: Callable[[], None],
) -> CaseOutcome:
    """Add the shrunk failure, or the reason there is none, to the outcome of a failing case.

    Only generated cases are shrunk, and not a failure that the problem's own
    hooks cause or a timeout longer than the shrink budget that is left. One that
    cannot be shrunk for one of these reasons, or because the budget of this
    implementation is used up, gets a note saying so.
    """
    if not isinstance(case.origin, GeneratedOrigin):
        return outcome
    if attempt.category in PROBLEM_HOOK_CATEGORIES:
        note = (
            f"not shrunk: the {attempt.category} failure comes from the problem's own hooks, "
            "not from the implementation"
        )
        return replace(outcome, shrink_note=note)
    if state.shrunk_count >= maximum_shrunk_cases:
        note = f"not shrunk: the limit of {maximum_shrunk_cases} shrunk cases per implementation was reached"
        return replace(outcome, shrink_note=note)
    if state.shrink_seconds_left <= 0:
        note = (
            "not shrunk: the time budget for shrinking "
            f"({state.shrink_seconds_total:g} seconds per implementation) was used up"
        )
        return replace(outcome, shrink_note=note)
    if attempt.category == TIMEOUT_CATEGORY and state.shrink_seconds_left < state.timeout_seconds:
        note = "not shrunk: the timeout is longer than the shrink budget"
        return replace(outcome, shrink_note=note)
    on_shrinking()
    shrunk, note = _shrink_within_budget(
        problem,
        state,
        case,
        attempt,
        maximum_candidates=maximum_candidates,
        description_limit=description_limit,
    )
    return replace(outcome, shrunk=shrunk, shrink_note=note)


def _shrink_within_budget(
    problem: Problem[Any, Any, Any],
    state: _ImplementationState,
    case: Case[Any],
    original: SingleRun,
    *,
    maximum_candidates: int,
    description_limit: int,
) -> tuple[ShrunkFailure | None, str | None]:
    """Shrink ``case`` against one implementation and charge the time to its budget.

    Return the shrunk failure, if one was found, and a note when shrinking did
    not finish: the problem's ``shrink`` or ``check_input`` hook raised, or the
    budget ran out.
    """
    started = time.monotonic()
    budget = _ShrinkBudget(maximum_candidates, state.shrink_seconds_left)
    shrinker = _Shrinker(
        problem, state.runner, original, budget, state.timeout_seconds, description_limit
    )
    shrunk = shrinker.shrink(case)
    state.shrink_seconds_left -= time.monotonic() - started
    if shrunk is not None:
        state.shrunk_count += 1
    note = shrinker.note
    if note is None and budget.exhausted == "candidates":
        note = (
            f"shrinking stopped after {budget.maximum_candidates} candidates, its limit; "
            "a smaller failing input may exist"
        )
    elif note is None and budget.exhausted == "time":
        note = (
            "shrinking stopped when its time budget "
            f"({state.shrink_seconds_total:g} seconds per implementation) ran out; "
            "a smaller failing input may exist"
        )
    return shrunk, note


class _Shrinker:
    """Find a smaller input that fails the same way as the original one.

    Candidates are tried in the order the problem yields them. One that equals
    the current input or that the problem's ``check_input`` rejects is skipped.
    The first that fails like ``original`` (the same status and category)
    becomes the new input and the search restarts from its candidates, until a
    full pass finds none or the budget runs out. A candidate that cannot be run
    at all is skipped, and a shrink or ``check_input`` hook that raises ends the
    search and leaves a note in ``note``. Each candidate runs with the smaller
    of the implementation's timeout and the time the budget has left, and a
    candidate that times out under the shortened limit is inconclusive, not a
    failure.
    """

    def __init__(
        self,
        problem: Problem[Any, Any, Any],
        runner: RunnerLike,
        original: SingleRun,
        budget: _ShrinkBudget,
        timeout_seconds: float,
        description_limit: int,
    ) -> None:
        self._problem = problem
        self._runner = runner
        self._original = original
        self._budget = budget
        self._timeout_seconds = timeout_seconds
        self._description_limit = description_limit
        self.note: str | None = None

    def shrink(self, case: Case[Any]) -> ShrunkFailure | None:
        """Return the smallest failing input found, or ``None`` when no candidate failed."""
        current = case.input_data
        best: SingleRun | None = None
        while (found := self._first_failing_candidate(current)) is not None:
            current, best = found
        if best is None:
            return None
        return ShrunkFailure(
            case=Case(ShrunkOrigin(case.identifier), current),
            message=best.message,
            detail=describe_failure(self._problem, current, best, self._description_limit),
        )

    def _first_failing_candidate(self, current: Any) -> tuple[Any, SingleRun] | None:
        try:
            for candidate in self._problem.shrink(current):
                if not self._budget.take_candidate():
                    return None
                if candidate == current or self._is_rejected(candidate):
                    continue
                attempt = self._try(candidate)
                if attempt is not None and attempt.fails_like(self._original):
                    return candidate, attempt
        except _HookError as error:
            self.note = str(error)
        except Exception as error:
            self.note = f"the problem's shrink hook raised {describe_error(error)}"
        return None

    def _is_rejected(self, candidate: Any) -> bool:
        """Whether the problem's ``check_input`` says ``candidate`` is not a valid input."""
        try:
            return self._problem.check_input(candidate) is not None
        except Exception as error:
            raise _HookError(
                f"the problem's check_input hook raised {describe_error(error)}"
            ) from error

    def _try(self, candidate: Any) -> SingleRun | None:
        """Run a candidate; ``None`` when it could not be run or the result is inconclusive."""
        timeout = min(self._timeout_seconds, self._budget.remaining_seconds())
        try:
            attempt = run_single(self._problem, self._runner, candidate, timeout_seconds=timeout)
        except Exception:
            return None
        if timeout < self._timeout_seconds and attempt.category == TIMEOUT_CATEGORY:
            return None
        return attempt


class _HookError(Exception):
    """A hook other than ``shrink`` raised while shrinking; the message is the note."""
