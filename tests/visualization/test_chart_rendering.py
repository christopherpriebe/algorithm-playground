"""Tests for rendering bar and line charts."""

import re
import subprocess
import sys
from typing import Any

import plotext
import pytest

from algorithm_playground import visualization
from algorithm_playground.visualization import (
    AxisScale,
    BarHighlight,
    ChartSeries,
    render_bar_chart,
    render_line_chart,
    render_side_by_side_bar_charts,
)


def strip_ansi_codes(text: str) -> str:
    """Remove the color escape sequences from some text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_rejects_mismatched_lengths() -> None:
    """Test a series with different numbers of x and y values is rejected."""
    with pytest.raises(ValueError, match="2 x values but 1 y values"):
        ChartSeries(name="broken", x_values=(1, 2), y_values=(1.0,))


@pytest.fixture
def drawn_output(capsys: pytest.CaptureFixture[str]) -> str:
    """The text printed by a line chart of two series with a title."""
    render_line_chart(
        [
            ChartSeries("fast-sort", (10, 100, 1000), (0.001, 0.002, 0.004)),
            ChartSeries("slow-sort", (10, 100, 1000), (0.01, 0.02, 0.04)),
        ],
        title="comparison",
        x_label="size",
        y_label="seconds",
        x_scale=AxisScale.LOGARITHMIC,
        y_scale=AxisScale.LOGARITHMIC,
    )
    return capsys.readouterr().out


def test_draws_a_legend_naming_every_series(drawn_output: str) -> None:
    """Test the chart names every series in its legend."""
    assert "fast-sort" in drawn_output
    assert "slow-sort" in drawn_output


def test_draws_the_title(drawn_output: str) -> None:
    """Test the chart shows its title."""
    assert "comparison" in drawn_output


BAR_VALUES: list[int] = [5, -3, 8, 1, 9, 2]


def test_returns_the_chart_as_text_instead_of_printing_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test the chart is returned as text and nothing is printed."""
    text = render_bar_chart(BAR_VALUES, title="my array")

    assert "my array" in strip_ansi_codes(text)
    assert capsys.readouterr().out == ""


def test_a_highlight_adds_a_legend_entry_and_its_own_color() -> None:
    """Test a highlight adds a legend entry and changes the picture."""
    plain_chart = render_bar_chart(BAR_VALUES, title="t")

    marked = render_bar_chart(
        BAR_VALUES, title="t", highlights=[BarHighlight((1, 4), "red", "swapped")]
    )

    assert "swapped" in strip_ansi_codes(marked)
    assert "swapped" not in strip_ansi_codes(plain_chart)
    assert marked != plain_chart


def test_a_highlight_without_bars_leaves_no_legend_entry() -> None:
    """Test a highlight that names no bar adds no legend entry."""
    text = render_bar_chart(
        BAR_VALUES, title="t", highlights=[BarHighlight((), "red", "none")]
    )

    assert "none" not in strip_ansi_codes(text)


def test_a_bar_named_twice_keeps_the_first_highlight() -> None:
    """Test a bar named by two highlights keeps only the first."""
    text = render_bar_chart(
        BAR_VALUES,
        title="t",
        highlights=[
            BarHighlight((2,), "red", "first"),
            BarHighlight((2,), "green", "second"),
        ],
    )

    assert "first" in strip_ansi_codes(text)
    assert "second" not in strip_ansi_codes(text)


def test_the_height_limits_the_number_of_lines() -> None:
    """Test the chart is no taller than the height requested."""
    text = render_bar_chart(BAR_VALUES, title="t", height=12)

    assert len(text.splitlines()) <= 12


def test_a_highlight_draws_only_its_own_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the bars of a highlight are drawn as their own series without the other bars."""
    drawn: list[tuple[list[int], list[float], str | None]] = []
    real_bar = plotext.bar

    def record_and_draw_bar(
        positions: list[int],
        heights: list[float],
        **options: Any,  # noqa: ANN401  forwarded unchanged to plotext
    ) -> None:
        drawn.append((list(positions), list(heights), options.get("color")))
        real_bar(positions, heights, **options)

    monkeypatch.setattr(plotext, "bar", record_and_draw_bar)

    render_bar_chart(
        [5, 3, 8, 1, 9, 2],
        title="t",
        highlights=[BarHighlight((1, 4), "red", "compared")],
    )

    assert drawn == [
        ([0, 2, 3, 5], [5, 8, 1, 2], "blue"),
        ([1, 4], [3, 9], "red"),
    ]


def test_a_highlight_leaves_the_picture_of_the_plain_bars_as_it_was() -> None:
    """Test a highlight changes only the legend row and not the other rows of the picture."""
    # The red bars share the bottom line of the plot with the blue ones. A highlight that
    # drew a full-width series of zeros would have overwritten the base of every plain bar.
    values = [5, 1, 5, 1, 5, 1, 5, 1]
    marked = strip_ansi_codes(
        render_bar_chart(
            values,
            title="t",
            highlights=[BarHighlight((1, 3), "red", "x")],
            height=12,
        )
    )
    unmarked = strip_ansi_codes(render_bar_chart(values, title="t", height=12))

    # The legend entry sits in the first row of the plot; every other row is unchanged.
    assert marked.splitlines()[3:] == unmarked.splitlines()[3:]
    assert "x" in marked.splitlines()[2]
    assert "x" not in unmarked


def test_indices_outside_the_values_are_ignored() -> None:
    """Test a highlight naming indices outside the values adds no legend entry."""
    text = render_bar_chart(
        [1, 2], title="t", highlights=[BarHighlight((7, -1), "red", "far")]
    )

    assert "far" not in strip_ansi_codes(text)


def test_an_empty_array_can_be_drawn() -> None:
    """Test a chart of an empty array is drawn with its title."""
    text = render_bar_chart([], title="empty", height=6)

    assert "empty" in strip_ansi_codes(text)


def test_a_single_bar_can_be_drawn() -> None:
    """Test a chart of one value draws a bar."""
    text = render_bar_chart([3], title="one", height=6)

    assert "█" in strip_ansi_codes(text)


def test_the_chart_labels_the_bars() -> None:
    """Test the axis of the chart numbers the bars from zero."""
    text = strip_ansi_codes(render_bar_chart(list(range(1, 11)), title="t", height=8))

    axis = text.splitlines()[-1]

    assert [int(number) for number in axis.split()] == list(range(10))


def test_the_helpers_that_print_are_gone() -> None:
    """Test the bar chart helpers that print are no longer part of the package."""
    assert not hasattr(visualization, "bar_chart")
    assert not hasattr(visualization, "side_by_side_bar_charts")
    assert "bar_chart" not in visualization.__all__


def test_side_by_side_charts_carry_both_titles() -> None:
    """Test side by side charts show the title of each chart."""
    text = render_side_by_side_bar_charts(
        [3, 1], [1, 3], left_title="left", right_title="right"
    )

    assert "left" in strip_ansi_codes(text)
    assert "right" in strip_ansi_codes(text)


@pytest.mark.parametrize("height", [20, 8])
def test_side_by_side_charts_take_a_height(height: int) -> None:
    """Test side by side charts are as tall as requested."""
    text = render_side_by_side_bar_charts(
        [3, 1], [1, 3], left_title="l", right_title="r", height=height
    )

    assert len(strip_ansi_codes(text).splitlines()) == height


def test_side_by_side_charts_highlight_both_sides() -> None:
    """Test a highlight applies to both charts of a side by side pair."""
    text = strip_ansi_codes(
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


def test_the_stepper_is_not_loaded_with_the_charts() -> None:
    """Test importing the charts does not import the stepper and its keys."""
    # A problem draws charts; only the debug command needs the stepper and its keys.
    program = (
        "import sys, algorithm_playground.visualization, algorithm_playground.authoring\n"
        "loaded = [name for name in sys.modules if name.startswith("
        "'algorithm_playground.visualization.')]\n"
        "print(sorted(loaded))"
    )

    result = subprocess.run(  # noqa: S603  runs the current interpreter on a fixed program
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "['algorithm_playground.visualization._charts']"
