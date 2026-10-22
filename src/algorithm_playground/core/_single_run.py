"""Run one input through one implementation and judge the output.

:func:`run_single` is the step the test engine repeats for every case and
every shrink candidate, and :func:`run_single_with_trace` the one ``debug``
performs once; they differ only in whether the run asks for a trace. Neither raises
for a failing run: a runner error, a problem hook that raises, and a wrong
answer all come back as a :class:`SingleRun` with a :class:`CaseStatus` and a
message.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Self

from algorithm_playground.core._description import describe_error
from algorithm_playground.core._problem import AnyProblem
from algorithm_playground.core._runner import (
    SERIALIZATION_CATEGORY,
    RunnerError,
    RunnerLike,
    RunResult,
)

__all__ = [
    "PROBLEM_HOOK_CATEGORIES",
    "VERIFICATION_ERROR_CATEGORY",
    "WRONG_OUTPUT_CATEGORY",
    "CaseStatus",
    "SingleRun",
    "run_single",
    "run_single_with_trace",
]

WRONG_OUTPUT_CATEGORY = "wrong output"
VERIFICATION_ERROR_CATEGORY = "verification error"
#: Failures that a hook of the problem causes, whatever the implementation does.
PROBLEM_HOOK_CATEGORIES = frozenset(
    {SERIALIZATION_CATEGORY, VERIFICATION_ERROR_CATEGORY}
)


def _judge(
    problem: AnyProblem,
    input_data: object,
    run: Callable[[], RunResult[object, object]],
) -> "SingleRun":
    """Call ``run`` and verify the output of the run with ``problem``.

    Returns:
        The outcome of the run.
    """
    try:
        result = run()
    except RunnerError as error:
        return SingleRun(
            status=CaseStatus.ERROR, message=str(error), category=error.category
        )
    try:
        verification = problem.verify(input_data, result.output)
    except Exception as error:  # noqa: BLE001  the verify hook is problem code
        return SingleRun(
            status=CaseStatus.ERROR,
            message=f"Verification raised {describe_error(error)}",
            category=VERIFICATION_ERROR_CATEGORY,
            result=result,
        )
    if verification.passed:
        return SingleRun(status=CaseStatus.PASSED, message="", result=result)
    message = verification.message
    if result.temporary_directory is not None:
        message += f"\nTemporary files were kept in {result.temporary_directory}"
    return SingleRun(
        status=CaseStatus.FAILED,
        message=message,
        category=verification.category or WRONG_OUTPUT_CATEGORY,
        result=result,
        focus=verification.focus,
    )


class CaseStatus(Enum):
    """How one implementation fared on one input."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


@dataclass(frozen=True, slots=True, kw_only=True)
class SingleRun:
    """The judged outcome of running one input.

    ``FAILED`` means the run completed but verification rejected the output;
    ``ERROR`` means the run or the verification itself failed. ``category``
    says what kind of failure it was (for example ``timeout`` or ``exit code
    3``), so two failures can be told apart; it is empty for a pass.
    :data:`PROBLEM_HOOK_CATEGORIES` lists the categories of failures that the
    problem's own hooks cause.
    ``message`` is empty for a pass. ``focus`` is the position in the output
    where the problem's ``verify`` found the first problem, when it said (see
    :class:`~algorithm_playground.core.VerificationResult`). ``result``
    is ``None`` when the run produced no output.
    """

    status: CaseStatus
    message: str
    category: str = ""
    result: RunResult[object, object] | None = None
    focus: int | None = None

    @property
    def has_output(self) -> bool:
        """Whether the implementation produced an output to describe."""
        return self.result is not None

    @property
    def output(self) -> object:
        """The output of the run, or ``None`` when there is none."""
        return None if self.result is None else self.result.output

    def is_same_failure_as(self, other: Self) -> bool:
        """Tell whether this run failed in the same way as another run.

        Args:
            other: The run to compare with.

        Returns:
            ``True`` when this run did not pass and has the same status and
            category as ``other``.
        """
        return (
            self.status is not CaseStatus.PASSED
            and self.status is other.status
            and self.category == other.category
        )


def run_single(
    problem: AnyProblem,
    runner: RunnerLike,
    input_data: object,
    *,
    timeout_seconds: float | None = None,
) -> SingleRun:
    """Run ``input_data`` through ``runner`` and verify the output with ``problem``.

    Args:
        problem: The problem that verifies the output.
        runner: The runner of the implementation under test.
        input_data: The input to run.
        timeout_seconds: A timeout that replaces the runner's own for this run.

    Returns:
        The judged outcome; a failing run is reported through it, not raised.
    """
    return _judge(
        problem,
        input_data,
        lambda: runner.run(input_data, timeout_seconds=timeout_seconds),
    )


def run_single_with_trace(
    problem: AnyProblem,
    runner: RunnerLike,
    input_data: object,
    *,
    timeout_seconds: float | None = None,
) -> SingleRun:
    """Run ``input_data`` like :func:`run_single`, asking the implementation to write a trace.

    Args:
        problem: The problem that verifies the output.
        runner: The runner of the implementation under test.
        input_data: The input to run.
        timeout_seconds: A timeout that replaces the runner's own for this run.

    Returns:
        The judged outcome. The trace, when the implementation wrote a usable
        one, is in its ``result``.
    """
    return _judge(
        problem,
        input_data,
        lambda: runner.run_with_trace(input_data, timeout_seconds=timeout_seconds),
    )
