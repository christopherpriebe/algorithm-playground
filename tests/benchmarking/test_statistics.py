"""Tests for summarizing timings and estimating how they grow."""

import inspect
import math
import statistics
from collections.abc import Callable

import pytest
from hypothesis import given, strategies

from algorithm_playground.core import (
    Growth,
    TimingSummary,
    estimate_growth,
    estimate_growth_exponent,
    fit_growth_class,
    format_duration,
    subtract_startup,
    summarize,
)

SIZES = (1_000, 10_000, 100_000)


GROWTH_SIZES = [1_000, 10_000, 100_000, 1_000_000]


def build_costs(shape: Callable[[float], float], factor: float = 1e-6) -> list[float]:
    """Build the cost of every growth size for a cost shape, scaled by a constant factor."""
    return [factor * shape(size) for size in GROWTH_SIZES]


def test_computes_headline_statistics() -> None:
    """Test the summary holds the sorted samples, count, minimum, median, mean and spread."""
    summary = summarize([4.0, 1.0, 3.0, 2.0])

    assert summary.samples == (1.0, 2.0, 3.0, 4.0)
    assert summary.count == 4
    assert summary.minimum == 1.0
    assert summary.median == 2.5
    assert summary.mean == 2.5
    assert summary.standard_deviation == pytest.approx(1.118033988749895)


def test_a_timing_summary_sorts_its_samples_and_derives_the_statistics() -> None:
    """Test a summary built from samples alone computes everything else from them."""
    summary = TimingSummary((3.0, 1.0, 2.0))

    assert summary.samples == (1.0, 2.0, 3.0)
    assert (summary.minimum, summary.median, summary.mean) == (1.0, 2.0, 2.0)
    assert summary.standard_deviation == pytest.approx(statistics.pstdev([1, 2, 3]))


def test_a_timing_summary_takes_only_the_samples() -> None:
    """Test the derived statistics cannot be given, so they cannot disagree with the samples."""
    assert list(inspect.signature(TimingSummary).parameters) == ["samples"]


def test_a_timing_summary_rejects_no_samples() -> None:
    """Test an empty summary is rejected, since it has no minimum or median."""
    with pytest.raises(ValueError, match="empty"):
        TimingSummary(())


@given(
    strategies.lists(
        strategies.floats(min_value=-1e100, max_value=1e100, allow_nan=False),
        min_size=1,
    )
)
def test_a_timing_summary_is_consistent_with_its_samples(samples: list[float]) -> None:
    """Test the derived statistics always agree with the samples they come from."""
    summary = TimingSummary(tuple(samples))

    assert summary.samples == tuple(sorted(samples))
    assert summary.minimum == min(samples)
    assert summary.minimum <= summary.median <= max(samples)
    assert summary.standard_deviation >= 0


def test_single_sample_has_zero_standard_deviation() -> None:
    """Test a single sample is its own minimum, median and mean with no spread."""
    summary = summarize([0.5])

    assert summary.minimum == summary.median == summary.mean == 0.5
    assert summary.standard_deviation == 0.0


def test_empty_sample_list_is_rejected() -> None:
    """Test summarizing no samples raises a ValueError."""
    with pytest.raises(ValueError, match="empty"):
        summarize([])


def test_removes_startup_from_every_sample() -> None:
    """Test the startup time is taken off every sample."""
    samples = subtract_startup([0.5, 0.75], 0.25)

    assert samples == [0.25, 0.5]


def test_does_not_clamp_samples_below_the_startup() -> None:
    """Test a sample shorter than the startup becomes negative instead of zero."""
    samples = subtract_startup([0.25], 0.5)

    assert samples == [-0.25]


@pytest.mark.parametrize("exponent", [0.5, 1.0, 1.5, 2.0, 3.0])
def test_recovers_the_exponent_of_a_power_law(exponent: float) -> None:
    """Test the estimated exponent matches the power law that produced the values."""
    values = [3e-9 * size**exponent for size in SIZES]

    estimate = estimate_growth_exponent(SIZES, values)

    assert estimate == pytest.approx(exponent)


def test_fits_a_line_through_noisy_points() -> None:
    """Test noisy points near a straight line give an exponent close to one."""
    sizes = (100, 200, 400, 800)
    values = (1.0, 2.2, 3.8, 8.3)

    exponent = estimate_growth_exponent(sizes, values)

    assert exponent is not None
    assert exponent == pytest.approx(0.99, abs=0.01)


def test_a_constant_cost_has_exponent_zero() -> None:
    """Test a cost that does not change with the size has exponent zero."""
    exponent = estimate_growth_exponent(SIZES, (0.5, 0.5, 0.5))

    assert exponent == pytest.approx(0.0)


def test_a_decreasing_cost_has_a_negative_exponent() -> None:
    """Test a cost that falls with the size has a negative exponent."""
    exponent = estimate_growth_exponent(SIZES, (4.0, 2.0, 1.0))

    assert exponent is not None
    assert exponent < 0


def test_points_with_a_non_positive_size_or_value_are_ignored() -> None:
    """Test points whose size or value is not positive do not change the estimate."""
    sizes = (0, 100, 200, 400, 800)
    values = (5.0, 1.0, 2.0, -3.0, 8.0)

    exponent = estimate_growth_exponent(sizes, values)

    assert exponent == pytest.approx(
        estimate_growth_exponent((100, 200, 800), (1.0, 2.0, 8.0))
    )


@pytest.mark.parametrize(
    ("sizes", "values"),
    [
        ((), ()),
        ((10, 100), (1.0, 10.0)),
        ((0, 10, 100), (1.0, 1.0, 10.0)),
        ((10, 100, 1000), (1.0, 0.0, 10.0)),
    ],
    ids=["no-points", "two-points", "zero-size", "zero-value"],
)
def test_fewer_than_three_usable_points_give_none(
    sizes: tuple[int, ...], values: tuple[float, ...]
) -> None:
    """Test no exponent is estimated from fewer than three usable points."""
    exponent = estimate_growth_exponent(sizes, values)

    assert exponent is None


def test_points_that_share_one_size_give_none() -> None:
    """Test no exponent is estimated when every point has the same size."""
    exponent = estimate_growth_exponent((10, 10, 10), (1.0, 2.0, 3.0))

    assert exponent is None


def test_mismatched_lengths_are_rejected() -> None:
    """Test a different number of sizes and values raises a ValueError."""
    with pytest.raises(ValueError, match="3 sizes but 2 values"):
        estimate_growth_exponent((1, 2, 3), (1.0, 2.0))


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (2.5, "2.500 s"),
        (0.0125, "12.500 ms"),
        (0.0000125, "12.500 us"),
        (0.0000000125, "12.500 ns"),
        (0.0, "0.000 ns"),
    ],
    ids=["seconds", "milliseconds", "microseconds", "nanoseconds", "zero"],
)
def test_picks_unit_by_magnitude(seconds: float, expected: str) -> None:
    """Test the unit follows the magnitude of the duration."""
    text = format_duration(seconds)

    assert text == expected


def test_negative_durations_keep_their_unit() -> None:
    """Test a negative duration is written with its sign and the unit of its magnitude."""
    text = format_duration(-0.0125)

    assert text == "-12.500 ms"


@pytest.mark.parametrize(
    ("name", "shape"),
    [
        ("1", lambda _: 5.0),
        ("log n", math.log2),
        ("n", lambda size: size),
        ("n log n", lambda size: size * math.log2(size)),
        ("n^2", lambda size: size**2),
        ("n^3", lambda size: size**3),
    ],
    ids=["constant", "logarithmic", "linear", "linearithmic", "quadratic", "cubic"],
)
def test_the_class_that_made_the_data_wins(
    name: str, shape: Callable[[float], float]
) -> None:
    """Test the growth class that produced the costs is the class that is fitted."""
    growth_class = fit_growth_class(GROWTH_SIZES, build_costs(shape))

    assert growth_class == name


@pytest.mark.parametrize("factor", [1e9, 1e-12], ids=["large-factor", "small-factor"])
def test_the_constant_factor_does_not_matter(factor: float) -> None:
    """Test scaling the costs by a constant leaves the fitted class unchanged."""
    costs = build_costs(lambda size: size**2, factor=factor)

    growth_class = fit_growth_class(GROWTH_SIZES, costs)

    assert growth_class == "n^2"


def test_a_little_noise_does_not_change_the_class() -> None:
    """Test costs that deviate a few percent from n log n still fit n log n."""
    noisy = [
        value * factor
        for value, factor in zip(
            build_costs(lambda size: size * math.log2(size)),
            (1.05, 0.97, 1.02, 0.99),
            strict=True,
        )
    ]

    growth_class = fit_growth_class(GROWTH_SIZES, noisy)

    assert growth_class == "n log n"


@pytest.mark.parametrize(
    ("exponent", "expected"),
    [(1.9, "n^2"), (1.02, "n")],
    ids=["near-quadratic", "near-linear"],
)
def test_an_exponent_between_two_classes_goes_to_the_nearer(
    exponent: float, expected: str
) -> None:
    """Test an exponent between two classes is assigned to the nearer class."""
    costs = build_costs(lambda size: size**exponent)

    growth_class = fit_growth_class(GROWTH_SIZES, costs)

    assert growth_class == expected


@pytest.mark.parametrize(
    ("sizes", "costs"),
    [
        ([100, 200], [1.0, 2.0]),
        ([0, 1, 100, 200], [1.0, 2.0, 3.0, 4.0]),
        ([100, 200, 400], [1.0, 0.0, 3.0]),
    ],
    ids=["two-points", "sizes-below-two", "zero-cost"],
)
def test_there_is_none_with_fewer_than_three_usable_points(
    sizes: list[int], costs: list[float]
) -> None:
    """Test no class is fitted from fewer than three usable points."""
    growth_class = fit_growth_class(sizes, costs)

    assert growth_class is None


def test_sizes_below_two_do_not_take_part() -> None:
    """Test points with a size below two are left out of the fit."""
    sizes = [0, 1, *GROWTH_SIZES]
    costs = [0.0, 1.0, *build_costs(lambda size: size)]

    growth_class = fit_growth_class(sizes, costs)

    assert growth_class == "n"


def test_all_points_at_one_size_cannot_be_fitted() -> None:
    """Test no class is fitted when every point has the same size."""
    growth_class = fit_growth_class([8, 8, 8], [1.0, 2.0, 3.0])

    assert growth_class is None


def test_the_lengths_must_match() -> None:
    """Test a different number of sizes and costs raises a ValueError."""
    with pytest.raises(ValueError, match="3 sizes but 2 values"):
        fit_growth_class([1, 2, 3], [1.0, 2.0])


def test_it_gives_the_exponent_and_the_class() -> None:
    """Test the growth of n log n costs has the class n log n and an exponent just above one."""
    costs = build_costs(lambda size: size * math.log2(size))

    growth = estimate_growth(GROWTH_SIZES, costs)

    assert growth is not None
    assert growth.growth_class == "n log n"
    assert growth.exponent == pytest.approx(1.1, abs=0.1)


def test_it_is_none_when_there_is_no_exponent() -> None:
    """Test there is no growth when the exponent cannot be estimated."""
    growth = estimate_growth([1, 2], [1.0, 2.0])

    assert growth is None


def test_the_class_alone_can_be_missing() -> None:
    """Test the growth keeps its exponent when no class can be fitted."""
    growth = estimate_growth([1, 1, 1, 2], [1.0, 1.0, 1.0, 2.0])

    assert growth is not None
    assert growth.growth_class is None


@pytest.mark.parametrize(
    ("growth", "text"),
    [
        (Growth(exponent=1.21, growth_class="n log n"), "~ n log n (n^1.21)"),
        (Growth(exponent=2.0, growth_class="n^2"), "~ n^2 (n^2.00)"),
        (Growth(exponent=0.0, growth_class="1"), "~ 1 (n^0.00)"),
        (Growth(exponent=1.049), "n^1.05"),
    ],
    ids=["linearithmic", "quadratic", "constant", "without-class"],
)
def test_it_is_written_for_people(growth: Growth, text: str) -> None:
    """Test the description names the class and the rounded exponent."""
    description = growth.describe()

    assert description == text
