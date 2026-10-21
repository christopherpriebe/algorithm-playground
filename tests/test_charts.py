"""Tests for the terminal chart helpers."""

from __future__ import annotations

import re
import subprocess
import sys
from typing import Any, ClassVar

import plotext
import pytest

import algorithm_playground.visualization as visualization
from algorithm_playground.visualization import (
    BarHighlight,
    ChartSeries,
    line_chart,
    render_bar_chart,
    render_side_by_side_bar_charts,
)


class TestChartSeries:
    def test_rejects_mismatched_lengths(self) -> None:
        with pytest.raises(ValueError, match="2 x values but 1 y values"):
            ChartSeries(name="broken", x_values=(1, 2), y_values=(1.0,))


class TestLineChart:
    def test_draws_a_legend_naming_every_series(self, capsys: pytest.CaptureFixture[str]) -> None:
        line_chart(
            [
                ChartSeries("fast-sort", (10, 100, 1000), (0.001, 0.002, 0.004)),
                ChartSeries("slow-sort", (10, 100, 1000), (0.01, 0.02, 0.04)),
            ],
            title="comparison",
            x_label="size",
            y_label="seconds",
            logarithmic_x=True,
            logarithmic_y=True,
        )
        output = capsys.readouterr().out
        assert "fast-sort" in output
        assert "slow-sort" in output
        assert "comparison" in output


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestRenderBarChart:
    values: ClassVar[list[int]] = [5, -3, 8, 1, 9, 2]

    def test_returns_the_chart_as_text_instead_of_printing_it(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = render_bar_chart(self.values, title="my array")
        assert "my array" in plain(text)
        assert capsys.readouterr().out == ""

    def test_a_highlight_adds_a_legend_entry_and_its_own_color(self) -> None:
        plain_chart = render_bar_chart(self.values, title="t")
        marked = render_bar_chart(
            self.values, title="t", highlights=[BarHighlight((1, 4), "red", "swapped")]
        )
        assert "swapped" in plain(marked)
        assert "swapped" not in plain(plain_chart)
        assert marked != plain_chart

    def test_a_highlight_without_bars_leaves_no_legend_entry(self) -> None:
        text = render_bar_chart(
            self.values, title="t", highlights=[BarHighlight((), "red", "none")]
        )
        assert "none" not in plain(text)

    def test_a_bar_named_twice_keeps_the_first_highlight(self) -> None:
        text = render_bar_chart(
            self.values,
            title="t",
            highlights=[
                BarHighlight((2,), "red", "first"),
                BarHighlight((2,), "green", "second"),
            ],
        )
        assert "first" in plain(text)
        assert "second" not in plain(text)

    def test_the_height_limits_the_number_of_lines(self) -> None:
        text = render_bar_chart(self.values, title="t", height=12)
        assert len(text.splitlines()) <= 12

    def test_a_highlight_draws_only_its_own_bars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        drawn: list[tuple[list[int], list[float], str | None]] = []
        real_bar = plotext.bar

        def spy(positions: list[int], heights: list[float], **options: Any) -> None:
            drawn.append((list(positions), list(heights), options.get("color")))
            real_bar(positions, heights, **options)

        monkeypatch.setattr(plotext, "bar", spy)
        render_bar_chart(
            [5, 3, 8, 1, 9, 2], title="t", highlights=[BarHighlight((1, 4), "red", "compared")]
        )
        assert drawn == [
            ([0, 2, 3, 5], [5, 8, 1, 2], "blue"),
            ([1, 4], [3, 9], "red"),
        ]

    def test_a_highlight_leaves_the_picture_of_the_plain_bars_as_it_was(self) -> None:
        # The red bars share the bottom line of the plot with the blue ones. A highlight that
        # drew a full-width series of zeros would have overwritten the base of every plain bar.
        values = [5, 1, 5, 1, 5, 1, 5, 1]
        marked = plain(
            render_bar_chart(
                values, title="t", highlights=[BarHighlight((1, 3), "red", "x")], height=12
            )
        )
        unmarked = plain(render_bar_chart(values, title="t", height=12))
        # The legend entry sits in the first row of the plot; every other row is unchanged.
        assert marked.splitlines()[3:] == unmarked.splitlines()[3:]
        assert "x" in marked.splitlines()[2] and "x" not in unmarked

    def test_indices_outside_the_values_are_ignored(self) -> None:
        text = render_bar_chart([1, 2], title="t", highlights=[BarHighlight((7, -1), "red", "far")])
        assert "far" not in plain(text)

    def test_an_empty_array_and_a_single_bar_can_be_drawn(self) -> None:
        assert "empty" in plain(render_bar_chart([], title="empty", height=6))
        assert "█" in plain(render_bar_chart([3], title="one", height=6))

    def test_the_chart_labels_the_bars(self) -> None:
        text = plain(render_bar_chart(list(range(1, 11)), title="t", height=8))
        axis = text.splitlines()[-1]
        assert [int(number) for number in axis.split()] == list(range(10))

    def test_the_helpers_that_print_are_gone(self) -> None:
        assert not hasattr(visualization, "bar_chart")
        assert not hasattr(visualization, "side_by_side_bar_charts")
        assert "bar_chart" not in visualization.__all__

    def test_side_by_side_charts_carry_both_titles(self) -> None:
        text = render_side_by_side_bar_charts(
            [3, 1], [1, 3], left_title="left", right_title="right"
        )
        assert "left" in plain(text)
        assert "right" in plain(text)

    def test_side_by_side_charts_take_a_height(self) -> None:
        tall = render_side_by_side_bar_charts(
            [3, 1], [1, 3], left_title="l", right_title="r", height=20
        )
        short = render_side_by_side_bar_charts(
            [3, 1], [1, 3], left_title="l", right_title="r", height=8
        )
        assert len(plain(tall).splitlines()) == 20
        assert len(plain(short).splitlines()) == 8

    def test_side_by_side_charts_highlight_both_sides(self) -> None:
        text = plain(
            render_side_by_side_bar_charts(
                [5, 3, 8],
                [3, 5, 8],
                left_title="l",
                right_title="r",
                height=10,
                highlights=[BarHighlight((0,), "red", "first difference")],
            )
        )
        assert text.count("first difference") == 2

    def test_the_stepper_is_not_loaded_with_the_charts(self) -> None:
        # A problem draws charts; only the debug command needs the stepper and its keys.
        program = (
            "import sys, algorithm_playground.visualization, algorithm_playground.authoring\n"
            "loaded = [name for name in sys.modules if name.startswith("
            "'algorithm_playground.visualization.')]\n"
            "print(sorted(loaded))"
        )
        result = subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "['algorithm_playground.visualization.charts']"
