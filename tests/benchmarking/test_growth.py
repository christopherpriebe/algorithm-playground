"""Tests for the growth that the benchmark engine fits and when it trusts it."""

from collections.abc import Callable
from typing import Any

import pytest

from algorithm_playground.core import (
    BenchmarkProgress,
    BenchmarkReport,
    BenchmarkSettings,
    ImplementationBenchmark,
    Problem,
    SizeMeasurement,
    run_benchmark,
    summarize,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    crash,
    sort_correctly,
)


def build_settings(**overrides: object) -> BenchmarkSettings:
    """Build benchmark settings of two small sizes, with the given fields replaced."""
    values: dict[str, Any] = {
        "seed": 1,
        "sizes": (5, 10),
        "repetitions": 1,
        "warmup": 0,
        "timeout_seconds": 30.0,
        "verify_outputs": True,
        "subtract_startup_time": False,
    }
    values.update(overrides)
    return BenchmarkSettings(**values)


def run_fake_benchmark(
    behaviors: dict[str, Callable[[Any], Any]],
    durations: dict[str, float | Callable[[Any], float]] | None = None,
    *,
    problem: Problem[Any, Any, Any] | None = None,
    **overrides: object,
) -> tuple[BenchmarkReport, FakeRunners, list[BenchmarkProgress]]:
    """Benchmark fake implementations and return the report, the runners and the progress events."""
    runners = FakeRunners(behaviors, durations)
    events: list[BenchmarkProgress] = []
    report = run_benchmark(
        SortingProblem() if problem is None else problem,
        build_named_implementations(*behaviors),
        build_settings(**overrides),
        runner_factory=runners,
        on_progress=events.append,
    )
    return report, runners, events


def compute_quadratic_seconds(values: list[int]) -> float:
    """Compute a duration of a startup cost plus a part that grows with the square of the length."""
    return 0.01 + 1e-7 * len(values) ** 2


SIZES = (100, 200, 400, 800)


def test_it_follows_the_work_when_the_startup_is_subtracted() -> None:
    """Test the growth of a quadratic cost is n squared when the startup is subtracted."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        durations={"a": compute_quadratic_seconds},
        sizes=SIZES,
        subtract_startup_time=True,
    )

    growth = report.implementations[0].growth("uniform")

    assert growth is not None
    assert growth.exponent == pytest.approx(2.0)
    assert growth.growth_class == "n^2"


def test_the_startup_is_excluded_even_when_it_is_not_subtracted() -> None:
    """Test the growth still follows the work when the startup is not subtracted."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        durations={"a": compute_quadratic_seconds},
        sizes=SIZES,
    )

    growth = report.implementations[0].growth("uniform")

    assert growth is not None
    assert growth.exponent == pytest.approx(2.0, abs=0.05)
    assert growth.growth_class == "n^2"


def test_it_is_estimated_for_each_distribution_separately() -> None:
    """Test each distribution gets the growth of its own costs."""

    def compute_duration(values: list[int]) -> float:
        return 1e-6 * len(values) * (len(set(values)) if len(values) > 1 else 1)

    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        durations={"a": compute_duration},
        sizes=SIZES,
        distributions=("all_equal", "sorted"),
    )
    item = report.implementations[0]

    all_equal = item.growth("all_equal")
    sorted_growth = item.growth("sorted")

    assert all_equal is not None
    assert sorted_growth is not None
    assert all_equal.exponent == pytest.approx(1.0)
    assert all_equal.growth_class == "n"
    assert sorted_growth.exponent == pytest.approx(2.0, abs=0.01)
    assert sorted_growth.growth_class == "n^2"


def test_the_startup_median_is_subtracted_not_the_mean() -> None:
    """Test the median of the startup, not its mean, is taken off before fitting the growth."""
    startup = summarize([0.01, 0.01, 0.01, 0.01, 0.21])
    measurements = tuple(
        SizeMeasurement(
            distribution="uniform",
            size=size,
            case_identifier=f"generated:uniform:size={size}:seed=0",
            raw_samples=(0.01 + 1e-5 * size,) * 3,
            summary=summarize([0.01 + 1e-5 * size] * 3),
        )
        for size in SIZES
    )
    item = ImplementationBenchmark(
        implementation=build_named_implementations("a")[0],
        startup=startup,
        measurements=measurements,
    )

    growth = item.growth("uniform")

    assert startup.median == pytest.approx(0.01)
    assert startup.mean == pytest.approx(0.05)
    assert growth is not None
    assert growth.exponent == pytest.approx(1.0)
    assert growth.growth_class == "n"


def test_there_is_none_with_fewer_than_three_sizes() -> None:
    """Test no growth is estimated from fewer than three sizes."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        durations={"a": compute_quadratic_seconds},
        sizes=(100, 200),
    )

    growth = report.implementations[0].growth("uniform")

    assert growth is None


def test_there_is_none_for_a_distribution_that_was_not_measured() -> None:
    """Test no growth is estimated for a distribution that was not measured."""
    report, _, _ = run_fake_benchmark({"a": sort_correctly}, sizes=SIZES)

    growth = report.implementations[0].growth("sorted")

    assert growth is None


def test_work_well_above_the_startup_is_reliable() -> None:
    """Test growth fitted to costs far above the startup is reliable."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        durations={"a": compute_quadratic_seconds},
        sizes=(1000, 2000, 4000, 8000),
        repetitions=3,
    )

    assert report.implementations[0].is_growth_reliable("uniform")


def test_medians_within_the_noise_of_the_startup_are_not() -> None:
    """Test growth fitted to costs that are close to the startup is not reliable."""
    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly},
        durations={"a": lambda values: 0.01 + 1e-9 * len(values)},
        sizes=SIZES,
    )
    item = report.implementations[0]

    assert item.growth("uniform") is not None
    assert not item.is_growth_reliable("uniform")


def test_only_sizes_clearly_above_the_startup_count() -> None:
    """Test growth is not reliable when most sizes are close to the startup."""

    def compute_duration(values: list[int]) -> float:
        return 0.01 if len(values) < 400 else 0.05

    report, _, _ = run_fake_benchmark(
        {"a": sort_correctly}, durations={"a": compute_duration}, sizes=SIZES
    )

    assert not report.implementations[0].is_growth_reliable("uniform")


def test_without_a_startup_measurement_there_is_nothing_to_doubt() -> None:
    """Test growth is reliable when there is no startup to compare with."""
    report, _, _ = run_fake_benchmark({"a": crash})

    assert report.implementations[0].is_growth_reliable("uniform")
