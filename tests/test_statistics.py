"""Tests for benchmark timing statistics and duration formatting."""

from __future__ import annotations

import pytest

from algorithm_playground.core.statistics import (
    format_duration,
    subtract_baseline,
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


class TestSubtractBaseline:
    def test_removes_baseline_from_every_sample(self) -> None:
        assert subtract_baseline([0.5, 0.75], 0.25) == [0.25, 0.5]

    def test_does_not_clamp_samples_below_the_baseline(self) -> None:
        assert subtract_baseline([0.25], 0.5) == [-0.25]


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
