"""Tests for benchmark timing statistics and duration formatting."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from algorithm_playground.core.statistics import (
    Growth,
    estimate_growth,
    estimate_growth_exponent,
    fit_growth_class,
    format_duration,
    subtract_startup,
    summarize,
)


class TestSummarize:
    def test_computes_headline_statistics(self) -> None:
        summary = summarize([4.0, 1.0, 3.0, 2.0])
        assert summary.samples == (1.0, 2.0, 3.0, 4.0)
        assert summary.count == 4
        assert summary.minimum == 1.0
        assert summary.median == 2.5
        assert summary.mean == 2.5
        assert summary.standard_deviation == pytest.approx(1.118033988749895)

    def test_single_sample_has_zero_standard_deviation(self) -> None:
        summary = summarize([0.5])
        assert summary.minimum == summary.median == summary.mean == 0.5
        assert summary.standard_deviation == 0.0

    def test_empty_sample_list_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            summarize([])


class TestSubtractStartup:
    def test_removes_startup_from_every_sample(self) -> None:
        assert subtract_startup([0.5, 0.75], 0.25) == [0.25, 0.5]

    def test_does_not_clamp_samples_below_the_startup(self) -> None:
        assert subtract_startup([0.25], 0.5) == [-0.25]


class TestEstimateGrowthExponent:
    SIZES = (1_000, 10_000, 100_000)

    @pytest.mark.parametrize("exponent", [0.5, 1.0, 1.5, 2.0, 3.0])
    def test_recovers_the_exponent_of_a_power_law(self, exponent: float) -> None:
        values = [3e-9 * size**exponent for size in self.SIZES]
        assert estimate_growth_exponent(self.SIZES, values) == pytest.approx(exponent)

    def test_fits_a_line_through_noisy_points(self) -> None:
        sizes = (100, 200, 400, 800)
        values = (1.0, 2.2, 3.8, 8.3)
        exponent = estimate_growth_exponent(sizes, values)
        assert exponent is not None
        assert exponent == pytest.approx(0.99, abs=0.01)

    def test_a_constant_cost_has_exponent_zero(self) -> None:
        assert estimate_growth_exponent(self.SIZES, (0.5, 0.5, 0.5)) == pytest.approx(0.0)

    def test_a_decreasing_cost_has_a_negative_exponent(self) -> None:
        exponent = estimate_growth_exponent(self.SIZES, (4.0, 2.0, 1.0))
        assert exponent is not None and exponent < 0

    def test_points_with_a_non_positive_size_or_value_are_ignored(self) -> None:
        sizes = (0, 100, 200, 400, 800)
        values = (5.0, 1.0, 2.0, -3.0, 8.0)
        assert estimate_growth_exponent(sizes, values) == pytest.approx(
            estimate_growth_exponent((100, 200, 800), (1.0, 2.0, 8.0))
        )

    def test_fewer_than_three_usable_points_give_none(self) -> None:
        assert estimate_growth_exponent((), ()) is None
        assert estimate_growth_exponent((10, 100), (1.0, 10.0)) is None
        assert estimate_growth_exponent((0, 10, 100), (1.0, 1.0, 10.0)) is None
        assert estimate_growth_exponent((10, 100, 1000), (1.0, 0.0, 10.0)) is None

    def test_points_that_share_one_size_give_none(self) -> None:
        assert estimate_growth_exponent((10, 10, 10), (1.0, 2.0, 3.0)) is None

    def test_mismatched_lengths_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="3 sizes but 2 values"):
            estimate_growth_exponent((1, 2, 3), (1.0, 2.0))


class TestFormatDuration:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (2.5, "2.500 s"),
            (0.0125, "12.500 ms"),
            (0.0000125, "12.500 us"),
            (0.0000000125, "12.500 ns"),
            (0.0, "0.000 ns"),
        ],
    )
    def test_picks_unit_by_magnitude(self, seconds: float, expected: str) -> None:
        assert format_duration(seconds) == expected

    def test_negative_durations_keep_their_unit(self) -> None:
        assert format_duration(-0.0125) == "-12.500 ms"


SIZES = [1_000, 10_000, 100_000, 1_000_000]


def costs(shape: Callable[[float], float], factor: float = 1e-6) -> list[float]:
    return [factor * shape(size) for size in SIZES]


class TestFitGrowthClass:
    @pytest.mark.parametrize(
        ("name", "shape"),
        [
            ("1", lambda size: 5.0),
            ("log n", math.log2),
            ("n", lambda size: size),
            ("n log n", lambda size: size * math.log2(size)),
            ("n^2", lambda size: size**2),
            ("n^3", lambda size: size**3),
        ],
    )
    def test_the_class_that_made_the_data_wins(
        self, name: str, shape: Callable[[float], float]
    ) -> None:
        assert fit_growth_class(SIZES, costs(shape)) == name

    def test_the_constant_factor_does_not_matter(self) -> None:
        assert fit_growth_class(SIZES, costs(lambda size: size**2, factor=1e9)) == "n^2"
        assert fit_growth_class(SIZES, costs(lambda size: size**2, factor=1e-12)) == "n^2"

    def test_a_little_noise_does_not_change_the_class(self) -> None:
        noisy = [
            value * factor
            for value, factor in zip(
                costs(lambda size: size * math.log2(size)), (1.05, 0.97, 1.02, 0.99), strict=True
            )
        ]
        assert fit_growth_class(SIZES, noisy) == "n log n"

    def test_an_exponent_between_two_classes_goes_to_the_nearer(self) -> None:
        assert fit_growth_class(SIZES, costs(lambda size: size**1.9)) == "n^2"
        assert fit_growth_class(SIZES, costs(lambda size: size**1.02)) == "n"

    def test_there_is_none_with_fewer_than_three_usable_points(self) -> None:
        assert fit_growth_class([100, 200], [1.0, 2.0]) is None
        assert fit_growth_class([0, 1, 100, 200], [1.0, 2.0, 3.0, 4.0]) is None
        assert fit_growth_class([100, 200, 400], [1.0, 0.0, 3.0]) is None

    def test_sizes_below_two_do_not_take_part(self) -> None:
        assert fit_growth_class([0, 1, *SIZES], [0.0, 1.0, *costs(lambda size: size)]) == "n"

    def test_all_points_at_one_size_cannot_be_fitted(self) -> None:
        assert fit_growth_class([8, 8, 8], [1.0, 2.0, 3.0]) is None

    def test_the_lengths_must_match(self) -> None:
        with pytest.raises(ValueError, match="3 sizes but 2 values"):
            fit_growth_class([1, 2, 3], [1.0, 2.0])


class TestEstimateGrowth:
    def test_it_gives_the_exponent_and_the_class(self) -> None:
        growth = estimate_growth(SIZES, costs(lambda size: size * math.log2(size)))
        assert growth is not None
        assert growth.growth_class == "n log n"
        assert growth.exponent == pytest.approx(1.1, abs=0.1)

    def test_it_is_none_when_there_is_no_exponent(self) -> None:
        assert estimate_growth([1, 2], [1.0, 2.0]) is None

    def test_the_class_alone_can_be_missing(self) -> None:
        growth = estimate_growth([1, 1, 1, 2], [1.0, 1.0, 1.0, 2.0])
        assert growth is not None and growth.growth_class is None

    @pytest.mark.parametrize(
        ("growth", "text"),
        [
            (Growth(1.21, "n log n"), "~ n log n (n^1.21)"),
            (Growth(2.0, "n^2"), "~ n^2 (n^2.00)"),
            (Growth(0.0, "1"), "~ 1 (n^0.00)"),
            (Growth(1.049), "n^1.05"),
        ],
    )
    def test_it_is_written_for_people(self, growth: Growth, text: str) -> None:
        assert growth.describe() == text
