"""Tests for distributions, growth rows, the report, and the plot of the benchmark command."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import Result

from algorithm_playground.visualization import ChartSeries
from helpers.fakes import FakeRunners, crash, sort_correctly
from helpers.support import (
    assert_exits_with,
    find_table_header,
    invoke_cli,
    parse_table_rows,
    replace_command_dependencies,
)

pytestmark = pytest.mark.integration


UseFakeRunners = Callable[..., FakeRunners]


FAST_SECONDS = 0.010


SLOW_SECONDS = 0.050


def compute_quadratic_seconds(values: list[int]) -> float:
    """Return a duration that grows with the square of the input size, above a startup time."""
    return 0.010 + 1e-6 * len(values) ** 2


def compute_linear_seconds(values: list[int]) -> float:
    """Return a duration that grows linearly with the input size, above a startup time."""
    return 0.010 + 1e-4 * len(values)


def compute_mostly_startup_seconds(values: list[int]) -> float:
    """Return a duration dominated by the startup time, growing only slightly with the size."""
    return 0.010 + 1e-9 * len(values) ** 2


def invoke_benchmark(*arguments: str, sizes: str = "4,8") -> Result:
    """Benchmark the implementations with one repetition per size and no plot."""
    return invoke_cli(
        "benchmark",
        "sorting",
        *arguments,
        "--sizes",
        sizes,
        "--repetitions",
        "1",
        "--warmup",
        "0",
        "--no-plot",
    )


def invoke_benchmark_with_plot(*arguments: str) -> Result:
    """Benchmark the implementations on three sizes, leaving the plot enabled."""
    return invoke_cli(
        "benchmark",
        "sorting",
        *arguments,
        "--sizes",
        "10,100,1000",
        "--repetitions",
        "1",
        "--warmup",
        "0",
    )


def test_the_default_generator_alone_is_measured_and_named_in_the_title(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test without the option the default distribution is named in the title only."""
    use_fake_runners({"first": sort_correctly, "second": sort_correctly})

    result = invoke_benchmark("--command", "first", "--command", "second")

    assert result.exit_code == 0, result.stdout
    assert "median in ms, ratio to first" in result.stdout
    assert "distribution: uniform" in result.stdout
    assert "distribution " not in find_table_header(result.stdout)


def test_an_unknown_distribution_is_a_usage_error_before_anything_runs(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test an unknown distribution lists the known ones and runs nothing."""
    runners = use_fake_runners({"sorter": sort_correctly})

    result = invoke_benchmark("--command", "sorter", "--distribution", "nope")

    assert_exits_with(result, 2)
    assert "Unknown distribution 'nope'" in result.stderr
    assert "median_of_three_killer" in result.stderr
    assert result.stdout == ""
    assert runners.calls == []


def test_several_distributions_share_one_table_with_a_header_row_each(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test measuring several distributions gives one table with a section per distribution."""
    use_fake_runners(
        {"fast": sort_correctly, "slow": sort_correctly},
        {"fast": FAST_SECONDS, "slow": SLOW_SECONDS},
    )

    result = invoke_benchmark(
        "--command",
        "fast",
        "--command",
        "slow",
        "--distribution",
        "sorted",
        "--distribution",
        "few_unique",
    )

    assert result.exit_code == 0, result.stdout
    assert "distribution" not in find_table_header(result.stdout)
    assert "median in ms, ratio to fast" in result.stdout
    assert "distribution:" not in result.stdout
    assert parse_table_rows(result.stdout) == [
        ["startup", "10.000 (1.00x)", "50.000 (5.00x)"],
        ["sorted", "", ""],
        ["4", "10.000 (1.00x)", "50.000 (5.00x)"],
        ["8", "10.000 (1.00x)", "50.000 (5.00x)"],
        ["few_unique", "", ""],
        ["4", "10.000 (1.00x)", "50.000 (5.00x)"],
        ["8", "10.000 (1.00x)", "50.000 (5.00x)"],
    ]


def test_a_repeated_distribution_is_measured_once(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a distribution named twice is measured once."""
    runners = use_fake_runners({"sorter": sort_correctly})

    result = invoke_benchmark(
        "--command",
        "sorter",
        "--distribution",
        "sorted",
        "--distribution",
        "sorted",
    )

    assert result.exit_code == 0, result.stdout
    assert [row[0] for row in parse_table_rows(result.stdout)] == [
        "startup",
        "4",
        "8",
    ]
    assert len(runners.calls) == 1 + 2  # the startup, and one run per size


def test_the_adversary_is_selectable_by_name(use_fake_runners: UseFakeRunners) -> None:
    """Test the median-of-three adversary can be chosen as the distribution."""
    runners = use_fake_runners({"sorter": sort_correctly})

    result = invoke_benchmark(
        "--command", "sorter", "--distribution", "median_of_three_killer"
    )

    assert result.exit_code == 0, result.stdout
    _, small, large = runners.collect_inputs_of("sorter")
    assert len(small) == 4
    assert [sorted(large).index(value) + 1 for value in large] == [
        1,
        5,
        3,
        7,
        2,
        4,
        6,
        8,
    ]


def test_a_failure_in_one_distribution_is_reported_with_its_name(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a failed size names its distribution and the other distribution still runs."""

    def fail_on_sorted_input(values: list[int]) -> list[int]:
        return (
            crash(values)
            if values == sorted(values) and len(values) > 3
            else sorted(values)
        )

    use_fake_runners({"picky": fail_on_sorted_input, "steady": sort_correctly})

    result = invoke_benchmark(
        "--command",
        "picky",
        "--command",
        "steady",
        "--distribution",
        "sorted",
        "--distribution",
        "uniform",
    )

    assert_exits_with(result, 1)
    assert "picky failed:" in result.stdout
    assert "size 4 (sorted)" in result.stdout
    picky_cells: dict[tuple[str, str], str] = {}
    section = ""
    for row in parse_table_rows(result.stdout):
        if row[0] in ("sorted", "uniform"):
            section = row[0]
        elif section:
            picky_cells[(section, row[0])] = row[1].split(" ")[0]
    # The failing size is failed, the rest of that distribution is skipped, and the
    # distribution after it still ran.
    assert picky_cells == {
        ("sorted", "4"): "failed",
        ("sorted", "8"): "skipped",
        ("uniform", "4"): "1.000",
        ("uniform", "8"): "1.000",
    }
    steady_cells = [row[2] for row in parse_table_rows(result.stdout)[1:]]
    assert "failed" not in steady_cells
    assert "skipped" not in steady_cells


SIZES = "100,200,400,800"


def test_a_comparison_shows_a_growth_row_per_distribution(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test the last row of a comparison gives the growth class of each implementation."""
    use_fake_runners(
        {"flat": sort_correctly, "steep": sort_correctly},
        {"flat": compute_linear_seconds, "steep": compute_quadratic_seconds},
    )

    result = invoke_benchmark(
        "--command",
        "flat",
        "--command",
        "steep",
        "--subtract-startup-time",
        sizes=SIZES,
    )

    assert result.exit_code == 0, result.stdout
    assert parse_table_rows(result.stdout)[-1] == [
        "growth",
        "~ n (n^1.00)",
        "~ n^2 (n^2.00)",
    ]


def test_a_single_implementation_shows_the_exponent_under_its_median(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test the growth of a lone implementation is shown under its median column."""
    use_fake_runners({"steep": sort_correctly}, {"steep": compute_quadratic_seconds})

    result = invoke_benchmark(
        "--command", "steep", "--subtract-startup-time", sizes=SIZES
    )

    assert result.exit_code == 0, result.stdout
    assert parse_table_rows(result.stdout)[-1] == [
        "growth",
        "",
        "~ n^2 (n^2.00)",
        "",
        "",
    ]


@pytest.mark.parametrize(
    "options",
    [[], ["--subtract-startup-time"]],
    ids=["startup kept", "startup subtracted"],
)
def test_the_growth_excludes_the_startup_time_either_way(
    use_fake_runners: UseFakeRunners,
    options: list[str],
) -> None:
    """Test the estimated growth ignores the startup time whether or not it is subtracted."""
    use_fake_runners(
        {"steep": sort_correctly}, {"steep": compute_mostly_startup_seconds}
    )

    result = invoke_benchmark("--command", "steep", *options, sizes=SIZES)

    growth = parse_table_rows(result.stdout)[-1][2]
    exponent = float(growth[growth.index("(n^") + 3 : growth.index(")")])
    assert exponent == pytest.approx(2.0, abs=0.05)


def test_a_series_that_is_mostly_startup_is_starred_and_explained(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test an unreliable growth estimate is starred and a note explains why."""
    use_fake_runners(
        {"quick": sort_correctly}, {"quick": compute_mostly_startup_seconds}
    )

    result = invoke_benchmark("--command", "quick", sizes=SIZES)

    assert result.exit_code == 0, result.stdout
    assert parse_table_rows(result.stdout)[-1][2].endswith(")*")
    assert (
        "* The medians of this series are too close to the startup time"
        in result.stdout
    )


def test_a_series_well_above_the_startup_is_not_starred(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a reliable growth estimate is neither starred nor explained."""
    use_fake_runners({"steep": sort_correctly}, {"steep": compute_quadratic_seconds})

    result = invoke_benchmark("--command", "steep", sizes=SIZES)

    assert "*" not in parse_table_rows(result.stdout)[-1][2]
    assert "too close to the startup time" not in result.stdout


def test_there_is_no_growth_row_with_fewer_than_three_sizes(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test no growth is estimated from fewer than three sizes."""
    use_fake_runners({"sorter": sort_correctly}, {"sorter": compute_quadratic_seconds})

    result = invoke_benchmark("--command", "sorter", sizes="100,200")

    assert "growth" not in result.stdout
    assert "n^" not in result.stdout


def test_each_distribution_gets_its_own_growth_row_and_unavailable_cells_are_dashes(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test every distribution has a growth row, with a dash for an implementation that failed."""

    def fail_for_large_inputs(values: list[int]) -> list[int]:
        return crash(values) if len(values) > 200 else sorted(values)

    use_fake_runners(
        {"steep": sort_correctly, "flaky": fail_for_large_inputs},
        {"steep": compute_quadratic_seconds, "flaky": compute_quadratic_seconds},
    )

    result = invoke_benchmark(
        "--command",
        "steep",
        "--command",
        "flaky",
        "--distribution",
        "sorted",
        "--distribution",
        "reversed",
        "--subtract-startup-time",
        sizes=SIZES,
    )

    assert result.exit_code == 1, result.stdout
    growth_rows = [row for row in parse_table_rows(result.stdout) if row[0] == "growth"]
    assert growth_rows == [
        ["growth", "~ n^2 (n^2.00)", "-"],
        ["growth", "~ n^2 (n^2.00)", "-"],
    ]


@pytest.fixture
def plotted(monkeypatch: pytest.MonkeyPatch) -> list[ChartSeries]:
    """The series that get plotted; the output counts as a terminal, which a plot needs."""
    series: list[ChartSeries] = []

    def capture(lines: list[ChartSeries], **_keywords: object) -> None:
        series.extend(lines)

    replace_command_dependencies(monkeypatch, render_line_chart=capture)
    monkeypatch.setenv("FORCE_COLOR", "1")
    return series


def test_the_json_report_records_distributions_and_growth(
    use_fake_runners: UseFakeRunners,
    tmp_path: Path,
) -> None:
    """Test the JSON report records every distribution, its results, and its growth."""
    use_fake_runners({"steep": sort_correctly}, {"steep": compute_quadratic_seconds})
    json_path = tmp_path / "report.json"

    result = invoke_benchmark(
        "--command",
        "steep",
        "--distribution",
        "sorted",
        "--distribution",
        "all_equal",
        "--subtract-startup-time",
        "--json",
        str(json_path),
        sizes="100,200,400",
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(json_path.read_text())
    assert report["report"] == "benchmark"
    assert report["format_version"] == 6
    assert report["settings"]["distributions"] == ["sorted", "all_equal"]
    (implementation,) = report["implementations"]
    assert [
        (record["distribution"], record["size"]) for record in implementation["results"]
    ] == [
        ("sorted", 100),
        ("sorted", 200),
        ("sorted", 400),
        ("all_equal", 100),
        ("all_equal", 200),
        ("all_equal", 400),
    ]
    assert (
        implementation["results"][0]["case_identifier"]
        == "generated:sorted:size=100:seed=0"
    )
    assert implementation["time_growth"] == {
        distribution: {
            "exponent": pytest.approx(2.0),
            "class": "n^2",
            "reliable": True,
        }
        for distribution in ("sorted", "all_equal")
    }


def test_no_plot_is_drawn_when_the_output_is_not_a_terminal(
    use_fake_runners: UseFakeRunners, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test the chart is skipped, and no color codes are written, when not on a terminal."""
    drawn: list[object] = []
    replace_command_dependencies(
        monkeypatch,
        render_line_chart=lambda *arguments, **_keywords: drawn.append(arguments),
    )
    use_fake_runners({"sorter": sort_correctly}, {"sorter": compute_linear_seconds})

    result = invoke_benchmark_with_plot("--command", "sorter")

    assert result.exit_code == 0, result.stdout
    assert drawn == []
    assert "\x1b[" not in result.stdout


def test_one_distribution_labels_the_series_with_the_implementation_only(
    use_fake_runners: UseFakeRunners, plotted: list[ChartSeries]
) -> None:
    """Test the plot has one series per implementation, named after it."""
    use_fake_runners(
        {"first": sort_correctly, "second": sort_correctly},
        {"first": compute_linear_seconds, "second": compute_quadratic_seconds},
    )

    result = invoke_benchmark_with_plot("--command", "first", "--command", "second")

    assert result.exit_code == 0, result.stdout
    assert [line.name for line in plotted] == ["first", "second"]


def test_several_distributions_draw_one_series_per_implementation_and_distribution(
    use_fake_runners: UseFakeRunners, plotted: list[ChartSeries]
) -> None:
    """Test the plot has a series for every pair of implementation and distribution."""
    use_fake_runners(
        {"first": sort_correctly, "second": sort_correctly},
        {"first": compute_linear_seconds, "second": compute_quadratic_seconds},
    )

    result = invoke_benchmark_with_plot(
        "--command",
        "first",
        "--command",
        "second",
        "--distribution",
        "sorted",
        "--distribution",
        "reversed",
    )

    assert result.exit_code == 0, result.stdout
    assert [line.name for line in plotted] == [
        "first (sorted)",
        "first (reversed)",
        "second (sorted)",
        "second (reversed)",
    ]
    assert all(line.x_values == (10, 100, 1000) for line in plotted)
