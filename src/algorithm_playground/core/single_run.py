"""Run one input through one implementation and judge the output.

:func:`run_single` is the step the test engine repeats for every case and
every shrink candidate, and the one ``debug`` performs once. It never raises
for a failing run: a runner error, a problem hook that raises, and a wrong
answer all come back as a :class:`SingleRun` with a :class:`CaseStatus` and a
message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from algorithm_playground.core._support import describe_error
from algorithm_playground.core.problem import Problem
from algorithm_playground.core.runner import (
    SERIALIZATION_CATEGORY,
    RunnerError,
    RunnerLike,
    RunResult,
)

WRONG_OUTPUT_CATEGORY = "wrong output"
VERIFICATION_ERROR_CATEGORY = "verification error"
# Failures that a hook of the problem causes, whatever the implementation does.
PROBLEM_HOOK_CATEGORIES = frozenset({SERIALIZATION_CATEGORY, VERIFICATION_ERROR_CATEGORY})


class CaseStatus(Enum):
    """How one implementation fared on one input."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


@dataclass(frozen=True)
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
    :class:`~algorithm_playground.core.problem.VerificationResult`). ``result``
    is ``None`` when the run produced no output.
    """

    status: CaseStatus
    message: str
    category: str = ""
    result: RunResult[Any, Any] | None = None
    focus: int | None = None

    @property
    def has_output(self) -> bool:
        """Whether the implementation produced an output to describe."""
        return self.result is not None

    @property
    def output(self) -> Any:
        """The output of the run, or ``None`` when there is none."""
        return None if self.result is None else self.result.output

    def fails_like(self, other: SingleRun) -> bool:
        """Whether this run failed in the same way as ``other`` (same status, same category)."""
        return (
            self.status is not CaseStatus.PASSED
            and self.status is other.status
            and self.category == other.category
        )


def run_single(
    problem: Problem[Any, Any, Any],
    runner: RunnerLike,
    input_data: Any,
    *,
    collect_trace: bool = False,
    timeout_seconds: float | None = None,
) -> SingleRun:
    """Run ``input_data`` through ``runner`` and verify the output with ``problem``.

    ``timeout_seconds`` replaces the runner's timeout for this run.
    """
    try:
        if timeout_seconds is None:
            result = runner.run(input_data, collect_trace=collect_trace)
        else:
            result = runner.run(
                input_data, collect_trace=collect_trace, timeout_seconds=timeout_seconds
            )
    except RunnerError as error:
        return SingleRun(CaseStatus.ERROR, str(error), category=error.category)
    try:
        verification = problem.verify(input_data, result.output)
    except Exception as error:
        return SingleRun(
            CaseStatus.ERROR,
            f"Verification raised {describe_error(error)}",
            category=VERIFICATION_ERROR_CATEGORY,
            result=result,
        )
    if verification.passed:
        return SingleRun(CaseStatus.PASSED, "", result=result)
    message = verification.message
    if result.temporary_directory is not None:
        message += f"\nTemporary files were kept in {result.temporary_directory}"
    return SingleRun(
        CaseStatus.FAILED,
        message,
        category=verification.category or WRONG_OUTPUT_CATEGORY,
        result=result,
        focus=verification.focus,
    )
