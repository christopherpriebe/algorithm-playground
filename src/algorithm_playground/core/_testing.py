"""Test engine: run a list of cases against several implementations and explain failures.

For every case and every implementation the engine runs the implementation,
verifies the output with the problem, and records a :class:`CaseOutcome`. A
failing outcome carries a :class:`FailureDetail` (the input, the expected
output when the problem knows it, and the actual output, described through
the problem's hooks). When a *generated* case fails the engine also shrinks
it: it asks the problem for smaller variants of the input
(:meth:`~algorithm_playground.core.Problem.shrink`), runs them
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

import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar

from algorithm_playground.core._cases import (
    AnyCase,
    Case,
    GeneratedOrigin,
    ShrunkOrigin,
)
from algorithm_playground.core._description import describe_error
from algorithm_playground.core._dimensions import Dimension
from algorithm_playground.core._errors import AlgorithmPlaygroundError
from algorithm_playground.core._implementation import Implementation
from algorithm_playground.core._problem import AnyProblem
from algorithm_playground.core._runner import (
    DEFAULT_TIMEOUT_SECONDS,
    TIMEOUT_CATEGORY,
    RunnerFactory,
    RunnerLike,
    TemporaryFilePolicy,
    build_subprocess_runner_factory,
)
from algorithm_playground.core._single_run import (
    PROBLEM_HOOK_CATEGORIES,
    CaseStatus,
    SingleRun,
    run_single,
)
from algorithm_playground.core._support import validate_implementations

__all__ = [
    "DEFAULT_DESCRIPTION_LIMIT",
    "DEFAULT_MAXIMUM_SHRINK_RUNS",
    "DEFAULT_MAXIMUM_SHRUNK_CASES",
    "DEFAULT_SHRINK_TIME_BUDGET_SECONDS",
    "CaseOutcome",
    "CasePhase",
    "CaseProgress",
    "FailureDetail",
    "ShrinkOptions",
    "ShrunkFailure",
    "TestReport",
    "TestRunOptions",
    "TestSettings",
    "describe_failure",
    "run_tests",
]

DEFAULT_MAXIMUM_SHRUNK_CASES = 3
DEFAULT_MAXIMUM_SHRINK_RUNS = 200
DEFAULT_SHRINK_TIME_BUDGET_SECONDS = 30.0
DEFAULT_DESCRIPTION_LIMIT = 300


def _validate_cases(cases: Sequence[AnyCase]) -> None:
    """Require at least one case and unique identifiers.

    Raises:
        ValueError: If there is no case or two share an identifier.
    """
    if not cases:
        message = "At least one case is required"
        raise ValueError(message)
    counts = Counter(case.identifier for case in cases)
    repeated = sorted(identifier for identifier, count in counts.items() if count > 1)
    if repeated:
        message = (
            f"Case identifiers must be unique, but these were repeated: {repeated}"
        )
        raise ValueError(message)


def _could_not_describe(error: Exception) -> str:
    return f"(could not describe: {describe_error(error)})"


def _describe_safely(describe: Callable[[], str]) -> str:
    """Run a describe hook; a hook that raises must not take the whole report down.

    Returns:
        The text of the hook, or a note that it could not describe.
    """
    try:
        return describe()
    except Exception as error:  # noqa: BLE001  describe hooks are problem code
        return _could_not_describe(error)


def _describe_output(
    problem: AnyProblem, output: object, *, limit: int, focus: object | None
) -> str:
    if focus is None:
        return problem.describe_output(output, limit=limit)
    return problem.describe_output(output, limit=limit, focus=focus)


def _describe_expected_output(
    problem: AnyProblem, input_data: object, *, limit: int, focus: object | None
) -> str | None:
    try:
        expected = problem.expected_output(input_data)
    except Exception as error:  # noqa: BLE001  expected_output is problem code
        return _could_not_describe(error)
    if expected is None:
        return None
    return _describe_safely(
        lambda: _describe_output(problem, expected, limit=limit, focus=focus)
    )


class CasePhase(Enum):
    """What the engine is doing for one implementation and case."""

    RUNNING = "running"
    SHRINKING = "shrinking"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True, kw_only=True)
class FailureDetail:
    """A failing run described for people: the input, the expected output, the actual output.

    ``expected_text`` is ``None`` when the problem knows no expected output,
    and ``actual_text`` is ``None`` when the run produced no output.
    """

    input_text: str
    expected_text: str | None
    actual_text: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ShrunkFailure:
    """The smallest failing input that shrinking found, and how it failed."""

    case: AnyCase
    message: str
    detail: FailureDetail


@dataclass(frozen=True, slots=True, kw_only=True)
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
    was (see :class:`~algorithm_playground.core.SingleRun`). ``score`` is the
    score that ``verify`` gave the output, or ``None``.
    """

    case: AnyCase
    implementation_name: str
    status: CaseStatus
    message: str
    detail: FailureDetail | None = None
    shrunk: ShrunkFailure | None = None
    shrink_note: str | None = None
    category: str = ""
    score: float | None = None

    @property
    def case_identifier(self) -> str:
        """The identifier of the case."""
        return self.case.identifier


@dataclass(frozen=True, slots=True, kw_only=True)
class CaseProgress:
    """A progress event: the engine started, is shrinking, or completed one case.

    ``outcome`` is set when ``phase`` is ``COMPLETED``; it is final and
    includes the shrunk failure when shrinking found one.
    """

    implementation_name: str
    case_identifier: str
    phase: CasePhase
    outcome: CaseOutcome | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ShrinkOptions:
    """The limits within which failing generated cases are shrunk.

    At most ``maximum_shrunk_cases`` cases are shrunk per implementation, one
    shrink performs at most ``maximum_runs`` runs, and each implementation has
    ``time_budget_seconds`` of shrinking in total. ``clock`` returns the current
    time in seconds and measures that budget; replace it to control time in tests.
    """

    maximum_shrunk_cases: int = DEFAULT_MAXIMUM_SHRUNK_CASES
    maximum_runs: int = DEFAULT_MAXIMUM_SHRINK_RUNS
    time_budget_seconds: float = DEFAULT_SHRINK_TIME_BUDGET_SECONDS
    clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True, slots=True, kw_only=True)
class TestRunOptions:
    """How :func:`run_tests` runs the cases.

    ``shrinking`` holds the limits for shrinking failing generated cases, and
    ``None`` turns shrinking off. ``temporary_files`` says whether the scratch
    directory of each run is kept, and descriptions are shortened to about
    ``description_limit`` characters.
    """

    __test__: ClassVar[bool] = False  # Tell pytest not to collect this as a test class.

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    temporary_files: TemporaryFilePolicy = TemporaryFilePolicy.DELETE
    shrinking: ShrinkOptions | None = field(default_factory=ShrinkOptions)
    description_limit: int = DEFAULT_DESCRIPTION_LIMIT


@dataclass(frozen=True, slots=True, kw_only=True)
class TestSettings:
    """The limits a test run worked within, recorded in its report."""

    __test__: ClassVar[bool] = False  # Tell pytest not to collect this as a test class.

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    shrink: bool = True
    maximum_shrunk_cases: int = DEFAULT_MAXIMUM_SHRUNK_CASES
    maximum_shrink_runs: int = DEFAULT_MAXIMUM_SHRINK_RUNS
    shrink_time_budget_seconds: float = DEFAULT_SHRINK_TIME_BUDGET_SECONDS


@dataclass(frozen=True, slots=True, kw_only=True)
class TestReport:
    """All outcomes of a test run, one per case and implementation.

    ``score_name`` is what the problem's ``verify`` scores, or ``None``.
    """

    __test__: ClassVar[bool] = False  # Tell pytest not to collect this as a test class.

    problem_name: str
    implementation_names: tuple[str, ...]
    cases: tuple[AnyCase, ...]
    outcomes: tuple[CaseOutcome, ...]
    settings: TestSettings = field(default_factory=TestSettings)
    dimensions: tuple[Dimension, ...] = (Dimension("size"),)
    score_name: str | None = None
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
        """Look up the outcome for one case and implementation.

        Args:
            case_identifier: The identifier of the case.
            implementation_name: The name of the implementation.

        Returns:
            The outcome.

        Raises:
            KeyError: If the run has no such outcome.
        """
        try:
            return self._index[(case_identifier, implementation_name)]
        except KeyError:
            message = (
                f"No outcome for case '{case_identifier}' and "
                f"implementation '{implementation_name}'"
            )
            raise KeyError(message) from None

    def outcomes_for(self, implementation_name: str) -> tuple[CaseOutcome, ...]:
        """Select the outcomes of one implementation.

        Args:
            implementation_name: The name of the implementation.

        Returns:
            Its outcomes, in case order.
        """
        return tuple(
            outcome
            for outcome in self.outcomes
            if outcome.implementation_name == implementation_name
        )

    def failures(self) -> tuple[CaseOutcome, ...]:
        """Select the outcomes that are not a pass.

        Returns:
            Every failed or errored outcome, in run order.
        """
        return tuple(
            outcome
            for outcome in self.outcomes
            if outcome.status is not CaseStatus.PASSED
        )

    @property
    def has_passed(self) -> bool:
        """Whether every implementation passed every case."""
        return not self.failures()


@dataclass(slots=True)
class _ImplementationState:
    """What the engine tracks for one implementation while it runs the cases."""

    name: str
    runner: RunnerLike
    timeout_seconds: float
    shrink_seconds_left: float
    shrink_seconds_total: float
    shrunk_count: int = 0

    def reason_not_to_shrink(
        self, attempt: SingleRun, shrinking: ShrinkOptions
    ) -> str | None:
        """Say why a failure is not shrunk.

        Args:
            attempt: The failing attempt.
            shrinking: The limits of shrinking.

        Returns:
            The note for the outcome, or ``None`` when the failure can be shrunk.
        """
        if attempt.category in PROBLEM_HOOK_CATEGORIES:
            return (
                f"not shrunk: the {attempt.category} failure comes from the problem's own hooks, "
                "not from the implementation"
            )
        if self.shrunk_count >= shrinking.maximum_shrunk_cases:
            return (
                f"not shrunk: the limit of {shrinking.maximum_shrunk_cases} shrunk cases "
                "per implementation was reached"
            )
        if self.shrink_seconds_left <= 0:
            return (
                "not shrunk: the time budget for shrinking "
                f"({self.shrink_seconds_total:g} seconds per implementation) was used up"
            )
        if (
            attempt.category == TIMEOUT_CATEGORY
            and self.shrink_seconds_left < self.timeout_seconds
        ):
            return "not shrunk: the timeout is longer than the shrink budget"
        return None


class _ShrinkBudget:
    """The candidates and the time that one shrink may still spend.

    ``exhausted`` says which of the two ran out, once :meth:`record_exhaustion`
    was called.
    """

    def __init__(
        self,
        maximum_candidates: int,
        time_budget_seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self.maximum_candidates = maximum_candidates
        self._candidates_left = maximum_candidates
        self._clock = clock
        self._deadline = clock() + time_budget_seconds
        self.exhausted: str | None = None

    def has_candidates_remaining(self) -> bool:
        """Say whether another candidate is allowed.

        Returns:
            ``True`` while the cap on candidates and the time budget both allow
            another candidate.
        """
        return self._candidates_left > 0 and self.remaining_seconds() > 0

    def take_candidate(self) -> None:
        """Spend one candidate.

        Every candidate counts, including one that equals its input or is
        rejected by ``check_input`` and is skipped, so a hook that never stops
        yielding cannot keep a shrink going.
        """
        self._candidates_left -= 1

    def record_exhaustion(self) -> None:
        """Remember which limit ran out: the cap on candidates, else the time."""
        self.exhausted = "candidates" if self._candidates_left <= 0 else "time"

    def remaining_seconds(self) -> float:
        """Return the seconds of the time budget that are left."""
        return self._deadline - self._clock()


class _HookError(AlgorithmPlaygroundError):
    """A hook other than ``shrink`` raised while shrinking; the message is the note."""


class _Shrinker:
    """Find a smaller input that fails the same way as the original one.

    Candidates are tried in the order the problem yields them. One that equals
    the current input or that the problem's ``check_input`` rejects is skipped.
    The first that fails like ``original`` (the same status and category)
    becomes the new input and the search restarts from its candidates, until a
    full pass finds none or the budget runs out. A candidate that cannot be run
    at all is skipped, and a shrink or ``check_input`` hook that raises, or an
    input type whose equality comparison raises, ends the search and leaves a
    note in ``note``. Each candidate runs with the smaller
    of the implementation's timeout and the time the budget has left, and a
    candidate that times out under the shortened limit is inconclusive, not a
    failure.
    """

    def __init__(  # noqa: PLR0913  six distinct collaborators and limits, all keyword-only after the first three
        self,
        problem: AnyProblem,
        runner: RunnerLike,
        original: SingleRun,
        *,
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

    def shrink(self, case: AnyCase) -> ShrunkFailure | None:
        """Search for the smallest input that still fails like the original one.

        Args:
            case: The failing generated case to shrink.

        Returns:
            The smallest failing input found, or ``None`` when no candidate failed.
        """
        current = case.input_data
        best: SingleRun | None = None
        while (found := self._first_failing_candidate(current)) is not None:
            current, best = found
        if best is None:
            return None
        return ShrunkFailure(
            case=Case(ShrunkOrigin(case.identifier), current),
            message=best.message,
            detail=describe_failure(
                self._problem, current, best, self._description_limit
            ),
        )

    def _first_failing_candidate(
        self, current: object
    ) -> tuple[object, SingleRun] | None:
        try:
            for candidate in self._problem.shrink(current):
                if not self._budget.has_candidates_remaining():
                    self._budget.record_exhaustion()
                    return None
                self._budget.take_candidate()
                if self._is_unchanged(candidate, current) or self._is_rejected(
                    candidate
                ):
                    continue
                attempt = self._try(candidate)
                if attempt is not None and attempt.is_same_failure_as(self._original):
                    return candidate, attempt
        except _HookError as error:
            self.note = str(error)
        except Exception as error:  # noqa: BLE001  the shrink hook is problem code
            self.note = f"the problem's shrink hook raised {describe_error(error)}"
        return None

    def _is_unchanged(self, candidate: object, current: object) -> bool:
        """Say whether ``candidate`` equals ``current``.

        Returns:
            ``True`` if the two compare equal.

        Raises:
            _HookError: If the comparison raises.
        """
        try:
            return bool(candidate == current)
        except Exception as error:
            message = (
                "comparing a shrink candidate with its input raised "
                f"{describe_error(error)}"
            )
            raise _HookError(message) from error

    def _is_rejected(self, candidate: object) -> bool:
        """Say whether the problem's ``check_input`` rejects ``candidate``.

        Returns:
            ``True`` if ``check_input`` says ``candidate`` is not a valid input.

        Raises:
            _HookError: If the ``check_input`` hook raises.
        """
        try:
            return self._problem.check_input(candidate) is not None
        except Exception as error:
            message = f"the problem's check_input hook raised {describe_error(error)}"
            raise _HookError(message) from error

    def _try(self, candidate: object) -> SingleRun | None:
        """Run a candidate.

        Returns:
            The result, or ``None`` when it could not be run or is inconclusive.
        """
        timeout = min(self._timeout_seconds, self._budget.remaining_seconds())
        try:
            attempt = run_single(
                self._problem, self._runner, candidate, timeout_seconds=timeout
            )
        except Exception:  # noqa: BLE001  any failure to start a run makes the candidate unusable
            # A candidate that cannot be run at all (for example because no time is left for a
            # valid timeout) says nothing about the failure, so the search skips it.
            return None
        if timeout < self._timeout_seconds and attempt.category == TIMEOUT_CATEGORY:
            return None
        return attempt


class _TestRun:
    """The state of one :func:`run_tests` call: a runner and a shrink budget per implementation."""

    def __init__(
        self,
        problem: AnyProblem,
        implementations: Sequence[Implementation],
        *,
        factory: RunnerFactory,
        options: TestRunOptions,
        on_progress: Callable[[CaseProgress], None] | None,
    ) -> None:
        self._problem = problem
        self._options = options
        self._on_progress = on_progress
        shrink_seconds = (
            0.0 if options.shrinking is None else options.shrinking.time_budget_seconds
        )
        self._states = [
            _ImplementationState(
                implementation.name,
                factory(problem, implementation),
                (
                    implementation.timeout_seconds
                    if implementation.timeout_seconds is not None
                    else options.timeout_seconds
                ),
                shrink_seconds,
                shrink_seconds,
            )
            for implementation in implementations
        ]

    @property
    def implementation_names(self) -> tuple[str, ...]:
        """The names of the implementations, in run order."""
        return tuple(state.name for state in self._states)

    @property
    def settings(self) -> TestSettings:
        """The options the run worked within, the way a report records them."""
        options = self._options
        shrinking = options.shrinking
        if shrinking is None:
            return TestSettings(timeout_seconds=options.timeout_seconds, shrink=False)
        return TestSettings(
            timeout_seconds=options.timeout_seconds,
            shrink=True,
            maximum_shrunk_cases=shrinking.maximum_shrunk_cases,
            maximum_shrink_runs=shrinking.maximum_runs,
            shrink_time_budget_seconds=shrinking.time_budget_seconds,
        )

    def run(self, cases: Sequence[AnyCase]) -> tuple[CaseOutcome, ...]:
        """Run every case against each implementation, case by case.

        Args:
            cases: The cases to run.

        Returns:
            The outcomes in run order: for each case, one per implementation.
        """
        return tuple(
            self._run_case(state, case) for case in cases for state in self._states
        )

    def _report(self, event: CaseProgress) -> None:
        if self._on_progress is not None:
            self._on_progress(event)

    def _run_case(self, state: _ImplementationState, case: AnyCase) -> CaseOutcome:
        self._report(
            CaseProgress(
                implementation_name=state.name,
                case_identifier=case.identifier,
                phase=CasePhase.RUNNING,
            )
        )
        attempt = run_single(self._problem, state.runner, case.input_data)
        detail = None
        if attempt.status is not CaseStatus.PASSED:
            detail = describe_failure(
                self._problem, case.input_data, attempt, self._options.description_limit
            )
        shrunk, shrink_note = self._shrink_failure(state, case, attempt)
        outcome = CaseOutcome(
            case=case,
            implementation_name=state.name,
            status=attempt.status,
            message=attempt.message,
            detail=detail,
            shrunk=shrunk,
            shrink_note=shrink_note,
            category=attempt.category,
            score=attempt.score,
        )
        if self._on_progress is not None:
            self._on_progress(
                CaseProgress(
                    implementation_name=state.name,
                    case_identifier=case.identifier,
                    phase=CasePhase.COMPLETED,
                    outcome=outcome,
                )
            )
        return outcome

    def _shrink_failure(
        self, state: _ImplementationState, case: AnyCase, attempt: SingleRun
    ) -> tuple[ShrunkFailure | None, str | None]:
        """Shrink a failing generated case, or say why it was not shrunk.

        Only generated cases are shrunk, and not a failure that the problem's own
        hooks cause or a timeout longer than the shrink budget that is left. One that
        cannot be shrunk for one of these reasons, or because the budget of this
        implementation is used up, gets a note saying so.

        Returns:
            The shrunk failure, if one was found, and the note.
        """
        shrinking = self._options.shrinking
        if shrinking is None or attempt.status is CaseStatus.PASSED:
            return None, None
        if not isinstance(case.origin, GeneratedOrigin):
            return None, None
        note = state.reason_not_to_shrink(attempt, shrinking)
        if note is not None:
            return None, note
        self._report(
            CaseProgress(
                implementation_name=state.name,
                case_identifier=case.identifier,
                phase=CasePhase.SHRINKING,
            )
        )
        return self._shrink_within_budget(state, case, attempt, shrinking=shrinking)

    def _shrink_within_budget(
        self,
        state: _ImplementationState,
        case: AnyCase,
        original: SingleRun,
        *,
        shrinking: ShrinkOptions,
    ) -> tuple[ShrunkFailure | None, str | None]:
        """Shrink ``case`` against one implementation and charge the time to its budget.

        Returns:
            The shrunk failure, if one was found, and a note when shrinking did
            not finish: the problem's ``shrink`` or ``check_input`` hook raised,
            or the budget ran out.
        """
        started = shrinking.clock()
        budget = _ShrinkBudget(
            shrinking.maximum_runs, state.shrink_seconds_left, shrinking.clock
        )
        shrinker = _Shrinker(
            self._problem,
            state.runner,
            original,
            budget=budget,
            timeout_seconds=state.timeout_seconds,
            description_limit=self._options.description_limit,
        )
        shrunk = shrinker.shrink(case)
        state.shrink_seconds_left -= shrinking.clock() - started
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


def describe_failure(
    problem: AnyProblem, input_data: object, attempt: SingleRun, limit: int
) -> FailureDetail:
    """Describe a failing attempt through the problem's hooks.

    A hook that raises does not take the description down; its text says that it
    could not describe. The focus ``verify`` named is passed to
    ``describe_output``, for the expected output as well as for the actual one.

    Args:
        problem: The problem whose hooks describe the input and the outputs.
        input_data: The input of the attempt.
        attempt: The failing attempt.
        limit: The approximate maximum number of characters of each description.

    Returns:
        The input, the expected output and the actual output as text.
    """
    return FailureDetail(
        input_text=_describe_safely(
            lambda: problem.describe_input(input_data, limit=limit)
        ),
        expected_text=_describe_expected_output(
            problem, input_data, limit=limit, focus=attempt.focus
        ),
        actual_text=(
            _describe_safely(
                lambda: _describe_output(
                    problem, attempt.output, limit=limit, focus=attempt.focus
                )
            )
            if attempt.has_output
            else None
        ),
    )


def run_tests(  # noqa: PLR0913  the problem, implementations and cases plus three keyword-only options
    problem: AnyProblem,
    implementations: Sequence[Implementation],
    cases: Sequence[AnyCase],
    *,
    options: TestRunOptions | None = None,
    runner_factory: RunnerFactory | None = None,
    on_progress: Callable[[CaseProgress], None] | None = None,
) -> TestReport:
    """Run every case of ``cases`` against each implementation.

    Outcomes are produced case by case, and for each case in the order of
    ``implementations``. With shrinking on (see :class:`TestRunOptions`), failing
    generated cases are shrunk in case order within the limits of
    :class:`ShrinkOptions`; later failures are reported unshrunk. It raises
    ``ValueError`` if there is no implementation or case, or names or
    identifiers repeat.

    Args:
        problem: The problem that generates, runs and verifies the cases.
        implementations: The implementations to test.
        cases: The cases to run.
        options: How to run the cases; the defaults when ``None``.
        runner_factory: Replaces the process-spawning runner; it receives the
            problem and the implementation.
        on_progress: Receives an event when a run starts, when shrinking
            starts, and when an outcome is complete.

    Returns:
        The outcome of every case on every implementation.
    """
    options = options or TestRunOptions()
    validate_implementations(implementations)
    _validate_cases(cases)
    factory = runner_factory or build_subprocess_runner_factory(
        timeout_seconds=options.timeout_seconds, temporary_files=options.temporary_files
    )
    test_run = _TestRun(
        problem,
        implementations,
        factory=factory,
        options=options,
        on_progress=on_progress,
    )
    outcomes = test_run.run(cases)
    return TestReport(
        problem_name=problem.name,
        implementation_names=test_run.implementation_names,
        cases=tuple(cases),
        outcomes=outcomes,
        settings=test_run.settings,
        dimensions=tuple(problem.dimensions),
        score_name=problem.score_name,
    )
