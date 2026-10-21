"""Tests for the checks on implementations that core/_support.py shares inside the core package.

The module is private, so the checks are exercised through the public functions that call them:
``run_tests`` and ``run_benchmark``.
"""

from collections.abc import Callable, Sequence

import pytest
from helpers.fakes import FakeRunners, build_named_implementations, sort_correctly

from algorithm_playground.core.benchmarking import BenchmarkSettings, run_benchmark
from algorithm_playground.core.cases import resolve_case
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.testing import run_tests
from algorithm_playground.problems.sorting import SortingProblem

Engine = Callable[[Sequence[Implementation]], list[str]]


def run_tests_on(implementations: Sequence[Implementation]) -> list[str]:
    """Run the empty fixture on fake runners and return the names of the implementations tested."""
    problem = SortingProblem()
    report = run_tests(
        problem,
        implementations,
        [resolve_case(problem, "fixture:empty")],
        runner_factory=FakeRunners({item.name: sort_correctly for item in implementations}),
    )
    return list(report.implementation_names)


def run_benchmark_on(implementations: Sequence[Implementation]) -> list[str]:
    """Benchmark on fake runners and return the names of the implementations measured."""
    settings = BenchmarkSettings(
        seed=1,
        sizes=(3,),
        repetitions=1,
        warmup=0,
        timeout_seconds=30.0,
        verify_outputs=True,
        subtract_startup_time=False,
    )
    report = run_benchmark(
        SortingProblem(),
        implementations,
        settings,
        runner_factory=FakeRunners({item.name: sort_correctly for item in implementations}),
    )
    return [benchmark.implementation.name for benchmark in report.implementations]


@pytest.fixture(params=[run_tests_on, run_benchmark_on], ids=["run_tests", "run_benchmark"])
def engine(request: pytest.FixtureRequest) -> Engine:
    """An engine that takes implementations and returns the names it ran."""
    return request.param


class TestImplementationValidation:
    def test_engine_accepts_implementations_with_unique_names(self, engine: Engine) -> None:
        """Test an engine runs every implementation when their names are unique."""
        implementations = build_named_implementations("first", "second")

        names = engine(implementations)

        assert names == ["first", "second"]

    def test_engine_rejects_an_empty_sequence_of_implementations(self, engine: Engine) -> None:
        """Test an engine refuses to run without implementations."""
        with pytest.raises(ValueError, match="At least one implementation"):
            engine([])

    def test_engine_rejects_duplicate_implementation_names(self, engine: Engine) -> None:
        """Test an engine names the implementation that appears twice."""
        implementations = build_named_implementations("a", "a")

        with pytest.raises(ValueError, match="Duplicate implementation name: 'a'"):
            engine(implementations)
