"""The collaborators the commands call, gathered so a caller can replace them.

The command line uses the defaults. Code that drives the commands in-process,
such as a test, hands its own through Click's context object::

    CliRunner().invoke(app, arguments, obj=CommandDependencies(run_tests=...))

Every command reads the object with ``ensure_object``, so a run without one
gets the defaults.
"""

from collections.abc import Callable
from dataclasses import dataclass

from algorithm_playground.core._benchmarking import BenchmarkReport, run_benchmark
from algorithm_playground.core._cases import DEFAULT_RANDOM_CASE_COUNT
from algorithm_playground.core._implementation import Implementation
from algorithm_playground.core._runner import check_can_start
from algorithm_playground.core._testing import TestReport, run_tests
from algorithm_playground.visualization._charts import render_line_chart
from algorithm_playground.visualization._stepper import step_through

__all__ = ["CommandDependencies"]


@dataclass(frozen=True, slots=True)
class CommandDependencies:
    """The engines, checks and drawing functions that the commands call.

    Attributes:
        run_tests: Runs the cases of the ``test`` command, called like
            :func:`~algorithm_playground.core.run_tests`.
        run_benchmark: Measures the implementations of the ``benchmark`` command,
            called like :func:`~algorithm_playground.core.run_benchmark`.
        check_can_start: Says why an implementation cannot be started, or returns
            ``None``, like :func:`~algorithm_playground.core.check_can_start`.
        step_through: Shows the frames of the ``debug`` command, called like
            :func:`~algorithm_playground.visualization.step_through`.
        render_line_chart: Draws the plot of the ``benchmark`` command, called like
            :func:`~algorithm_playground.visualization.render_line_chart`.
        default_random_case_count: How many generated cases ``test`` runs when
            ``--random-cases`` is not given.
    """

    run_tests: Callable[..., TestReport] = run_tests
    run_benchmark: Callable[..., BenchmarkReport] = run_benchmark
    check_can_start: Callable[[Implementation], str | None] = check_can_start
    step_through: Callable[..., None] = step_through
    render_line_chart: Callable[..., None] = render_line_chart
    default_random_case_count: int = DEFAULT_RANDOM_CASE_COUNT
