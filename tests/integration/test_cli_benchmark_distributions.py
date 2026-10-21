"""CLI tests for benchmark ratios, distributions, and growth estimates.

Timings come from in-process fake runners with fixed durations, so the numbers
in the tables are exact and nothing here depends on how fast the machine is.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import FakeRunners, crash, sort_correctly
from support import Invoke, TableRows, assert_exits_with
from typer.testing import Result

from algorithm_playground.cli import benchmark_rendering
from algorithm_playground.visualization import ChartSeries

pytestmark = pytest.mark.integration

UseFakeRunners = Callable[..., FakeRunners]

FAST = 0.010
SLOW = 0.050


def quadratic(values: list[int]) -> float:
    return 0.010 + 1e-6 * len(values) ** 2


def linear(values: list[int]) -> float:
    return 0.010 + 1e-4 * len(values)


def mostly_startup(values: list[int]) -> float:
    return 0.010 + 1e-9 * len(values) ** 2


def benchmark(invoke: Invoke, *arguments: str, sizes: str = "4,8") -> Result:
    return invoke(
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


class TestRatios:
    def test_the_second_implementation_is_compared_to_the_first(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners(
            {"fast": sort_correctly, "slow": sort_correctly}, {"fast": FAST, "slow": SLOW}
        )
        result = benchmark(invoke, "--command", "fast", "--command", "slow")
        assert result.exit_code == 0, result.stdout
        assert "median in ms, ratio to fast" in result.stdout
        assert table_rows(result.stdout) == [
            ["startup", "10.000 (1.00x)", "50.000 (5.00x)"],
            ["4", "10.000 (1.00x)", "50.000 (5.00x)"],
            ["8", "10.000 (1.00x)", "50.000 (5.00x)"],
        ]

    def test_a_non_first_reference_becomes_the_denominator(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners(
            {"fast": sort_correctly, "slow": sort_correctly}, {"fast": FAST, "slow": SLOW}
        )
        result = benchmark(invoke, "--command", "fast", "--command", "slow", "--reference", "slow")
        assert result.exit_code == 0, result.stdout
        assert "ratio to slow" in result.stdout
        assert table_rows(result.stdout)[1:] == [
            ["4", "10.000 (0.20x)", "50.000 (1.00x)"],
            ["8", "10.000 (0.20x)", "50.000 (1.00x)"],
        ]

    def test_the_ratio_is_left_out_when_the_reference_took_no_measurable_time(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners({"zero": sort_correctly, "other": sort_correctly}, {"zero": 0.0})
        result = benchmark(invoke, "--command", "zero", "--command", "other")
        assert result.exit_code == 0, result.stdout
        assert table_rows(result.stdout)[1] == ["4", "0.000", "1.000"]


class TestDistributionOption:
    def test_the_default_generator_alone_is_measured_and_named_in_the_title(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners({"a": sort_correctly, "b": sort_correctly})
        result = benchmark(invoke, "--command", "a", "--command", "b")
        assert result.exit_code == 0, result.stdout
        assert "median in ms, ratio to a" in result.stdout
        assert "distribution: uniform" in result.stdout
        assert "distribution " not in next(
            line for line in result.stdout.splitlines() if line.startswith("┃")
        )

    def test_an_unknown_distribution_is_a_usage_error_before_anything_runs(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners
    ) -> None:
        runners = use_fake_runners({"a": sort_correctly})
        result = benchmark(invoke, "--command", "a", "--distribution", "nope")
        assert_exits_with(result, 2)
        assert "Unknown distribution 'nope'" in result.stderr
        assert "median_of_three_killer" in result.stderr
        assert result.stdout == ""
        assert runners.calls == []

    def test_several_distributions_share_one_table_with_a_header_row_each(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners(
            {"fast": sort_correctly, "slow": sort_correctly}, {"fast": FAST, "slow": SLOW}
        )
        result = benchmark(
            invoke,
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
        header = next(line for line in result.stdout.splitlines() if line.startswith("┃"))
        assert "distribution" not in header
        assert "median in ms, ratio to fast" in result.stdout
        assert "distribution:" not in result.stdout
        assert table_rows(result.stdout) == [
            ["startup", "10.000 (1.00x)", "50.000 (5.00x)"],
            ["sorted", "", ""],
            ["4", "10.000 (1.00x)", "50.000 (5.00x)"],
            ["8", "10.000 (1.00x)", "50.000 (5.00x)"],
            ["few_unique", "", ""],
            ["4", "10.000 (1.00x)", "50.000 (5.00x)"],
            ["8", "10.000 (1.00x)", "50.000 (5.00x)"],
        ]

    def test_a_repeated_distribution_is_measured_once(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        runners = use_fake_runners({"a": sort_correctly})
        result = benchmark(
            invoke, "--command", "a", "--distribution", "sorted", "--distribution", "sorted"
        )
        assert result.exit_code == 0, result.stdout
        assert [row[0] for row in table_rows(result.stdout)] == ["startup", "4", "8"]
        assert len(runners.calls) == 1 + 2  # the startup, and one run per size

    def test_the_adversary_is_selectable_by_name(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners
    ) -> None:
        runners = use_fake_runners({"a": sort_correctly})
        result = benchmark(invoke, "--command", "a", "--distribution", "median_of_three_killer")
        assert result.exit_code == 0, result.stdout
        _, small, large = runners.inputs_of("a")
        assert len(small) == 4
        assert [sorted(large).index(value) + 1 for value in large] == [1, 5, 3, 7, 2, 4, 6, 8]

    def test_a_failure_in_one_distribution_is_reported_with_its_name(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        def fail_on_sorted_input(values: list[int]) -> list[int]:
            return crash(values) if values == sorted(values) and len(values) > 3 else sorted(values)

        use_fake_runners({"picky": fail_on_sorted_input, "steady": sort_correctly})
        result = benchmark(
            invoke,
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
        for row in table_rows(result.stdout):
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
        steady_cells = [row[2] for row in table_rows(result.stdout)[1:]]
        assert "failed" not in steady_cells and "skipped" not in steady_cells


class TestGrowthRows:
    SIZES = "100,200,400,800"

    def test_a_comparison_shows_a_growth_row_per_distribution(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners(
            {"flat": sort_correctly, "steep": sort_correctly},
            {"flat": linear, "steep": quadratic},
        )
        result = benchmark(
            invoke,
            "--command",
            "flat",
            "--command",
            "steep",
            "--subtract-startup-time",
            sizes=self.SIZES,
        )
        assert result.exit_code == 0, result.stdout
        assert table_rows(result.stdout)[-1] == ["growth", "~ n (n^1.00)", "~ n^2 (n^2.00)"]

    def test_a_single_implementation_shows_the_exponent_under_its_median(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners({"steep": sort_correctly}, {"steep": quadratic})
        result = benchmark(
            invoke, "--command", "steep", "--subtract-startup-time", sizes=self.SIZES
        )
        assert result.exit_code == 0, result.stdout
        assert table_rows(result.stdout)[-1] == ["growth", "", "~ n^2 (n^2.00)", "", ""]

    @pytest.mark.parametrize(
        "options",
        [[], ["--subtract-startup-time"]],
        ids=["startup kept", "startup subtracted"],
    )
    def test_the_growth_excludes_the_startup_time_either_way(
        self,
        invoke: Invoke,
        use_fake_runners: UseFakeRunners,
        table_rows: TableRows,
        options: list[str],
    ) -> None:
        use_fake_runners({"steep": sort_correctly}, {"steep": mostly_startup})
        result = benchmark(invoke, "--command", "steep", *options, sizes=self.SIZES)
        growth = table_rows(result.stdout)[-1][2]
        exponent = float(growth[growth.index("(n^") + 3 : growth.index(")")])
        assert exponent == pytest.approx(2.0, abs=0.05)

    def test_a_series_that_is_mostly_startup_is_starred_and_explained(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners({"quick": sort_correctly}, {"quick": mostly_startup})
        result = benchmark(invoke, "--command", "quick", sizes=self.SIZES)
        assert result.exit_code == 0, result.stdout
        assert table_rows(result.stdout)[-1][2].endswith(")*")
        assert "* The medians of this series are too close to the startup time" in result.stdout

    def test_a_series_well_above_the_startup_is_not_starred(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners({"steep": sort_correctly}, {"steep": quadratic})
        result = benchmark(invoke, "--command", "steep", sizes=self.SIZES)
        assert "*" not in table_rows(result.stdout)[-1][2]
        assert "too close to the startup time" not in result.stdout

    def test_there_is_no_growth_row_with_fewer_than_three_sizes(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        use_fake_runners({"a": sort_correctly}, {"a": quadratic})
        result = benchmark(invoke, "--command", "a", sizes="100,200")
        assert "growth" not in result.stdout
        assert "n^" not in result.stdout

    def test_each_distribution_gets_its_own_growth_row_and_unavailable_cells_are_dashes(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, table_rows: TableRows
    ) -> None:
        def flaky(values: list[int]) -> list[int]:
            return crash(values) if len(values) > 200 else sorted(values)

        use_fake_runners(
            {"steep": sort_correctly, "flaky": flaky},
            {"steep": quadratic, "flaky": quadratic},
        )
        result = benchmark(
            invoke,
            "--command",
            "steep",
            "--command",
            "flaky",
            "--distribution",
            "sorted",
            "--distribution",
            "reversed",
            "--subtract-startup-time",
            sizes=self.SIZES,
        )
        assert result.exit_code == 1, result.stdout
        growth_rows = [row for row in table_rows(result.stdout) if row[0] == "growth"]
        assert growth_rows == [
            ["growth", "~ n^2 (n^2.00)", "-"],
            ["growth", "~ n^2 (n^2.00)", "-"],
        ]


class TestReportAndPlot:
    def test_the_json_report_records_distributions_and_growth(
        self,
        invoke: Invoke,
        use_fake_runners: UseFakeRunners,
        tmp_path: Path,
    ) -> None:
        use_fake_runners({"steep": sort_correctly}, {"steep": quadratic})
        json_path = tmp_path / "report.json"
        result = benchmark(
            invoke,
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
        assert implementation["results"][0]["case_identifier"] == "generated:sorted:size=100:seed=0"
        assert implementation["time_growth"] == {
            distribution: {"exponent": pytest.approx(2.0), "class": "n^2", "reliable": True}
            for distribution in ("sorted", "all_equal")
        }

    @pytest.fixture
    def plotted(self, monkeypatch: pytest.MonkeyPatch) -> list[ChartSeries]:
        """The series that get plotted; the output counts as a terminal, which a plot needs."""
        series: list[ChartSeries] = []

        def capture(lines: list[ChartSeries], **keywords: object) -> None:
            series.extend(lines)

        monkeypatch.setattr(benchmark_rendering, "line_chart", capture)
        monkeypatch.setenv("FORCE_COLOR", "1")
        return series

    def test_no_plot_is_drawn_when_the_output_is_not_a_terminal(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        drawn: list[object] = []
        monkeypatch.setattr(
            benchmark_rendering,
            "line_chart",
            lambda *arguments, **keywords: drawn.append(arguments),
        )
        use_fake_runners({"a": sort_correctly}, {"a": linear})
        result = self.plot(invoke, "--command", "a")
        assert result.exit_code == 0, result.stdout
        assert drawn == []
        assert "\x1b[" not in result.stdout

    def plot(self, invoke: Invoke, *arguments: str) -> Result:
        return invoke(
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

    def test_one_distribution_labels_the_series_with_the_implementation_only(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, plotted: list[ChartSeries]
    ) -> None:
        use_fake_runners({"a": sort_correctly, "b": sort_correctly}, {"a": linear, "b": quadratic})
        result = self.plot(invoke, "--command", "a", "--command", "b")
        assert result.exit_code == 0, result.stdout
        assert [line.name for line in plotted] == ["a", "b"]

    def test_several_distributions_draw_one_series_per_implementation_and_distribution(
        self, invoke: Invoke, use_fake_runners: UseFakeRunners, plotted: list[ChartSeries]
    ) -> None:
        use_fake_runners({"a": sort_correctly, "b": sort_correctly}, {"a": linear, "b": quadratic})
        result = self.plot(
            invoke,
            "--command",
            "a",
            "--command",
            "b",
            "--distribution",
            "sorted",
            "--distribution",
            "reversed",
        )
        assert result.exit_code == 0, result.stdout
        assert [line.name for line in plotted] == [
            "a (sorted)",
            "a (reversed)",
            "b (sorted)",
            "b (reversed)",
        ]
        assert all(line.x_values == (10, 100, 1000) for line in plotted)
