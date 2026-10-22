"""Tests for comparing implementations in the benchmark command."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import Result

from helpers.executables import write_sorter
from helpers.fakes import FakeRunners, sort_correctly
from helpers.support import (
    assert_exits_with,
    find_table_header,
    invoke_cli,
    parse_table_rows,
)

pytestmark = pytest.mark.integration


RATIO = re.compile(r"\((\d+\.\d+)x\)")


# How long the slow sorter waits per run. Under heavy parallel load a process can be delayed by
# several hundred milliseconds, so the gap must be far larger than that for the comparison
# between a real fast and a real slow process to be stable.
SLOW_SORTER_SECONDS = 1.0


def invoke_comparison(
    *arguments: str, sizes: str = "4,50", warmup: str = "0"
) -> Result:
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
        warmup,
        "--no-plot",
    )


UseFakeRunners = Callable[..., FakeRunners]


FAST_SECONDS = 0.010


SLOW_SECONDS = 0.050


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


@pytest.fixture
def sorters(tmp_path: Path) -> dict[str, Path]:
    """Sorters that are fast, slow, and fail for inputs of more than ten elements."""
    return {
        "fast": write_sorter(tmp_path / "fast.py"),
        "slow": write_sorter(tmp_path / "slow.py", sleep_seconds=SLOW_SORTER_SECONDS),
        "flaky": write_sorter(tmp_path / "flaky.py", fail_above=10),
    }


def test_a_slower_implementation_is_reported_slower_than_the_reference(
    sorters: dict[str, Path],
) -> None:
    """Test a real sorter that waits is reported with a ratio above one to a quick one."""
    # The ratio arithmetic is tested with exact durations by the fake-runner tests in
    # this file; this checks the wiring with real processes. The first launch of a newly
    # written script is not timed: the system checks a new executable before it starts,
    # which takes hundreds of milliseconds when the suite writes many of them at once
    # and would land on whichever sorter starts first. With that warmup run and one
    # size, the slow sorter's wait dwarfs any scheduling delay.
    result = invoke_comparison(
        str(sorters["fast"]), str(sorters["slow"]), sizes="4", warmup="1"
    )

    assert result.exit_code == 0, result.stdout
    assert "ratio to fast.py" in result.stdout
    header = find_table_header(result.stdout)
    assert header.index("fast.py") < header.index("slow.py")
    rows = parse_table_rows(result.stdout)
    assert [row[0] for row in rows] == ["startup", "4"]
    for row in rows:
        reference_ratio, slow_ratio = (
            float(value) for value in RATIO.findall(" ".join(row))
        )
        assert reference_ratio == 1.0
        assert slow_ratio > 1.0, row


def test_a_failed_implementation_shows_failed_cells_only_where_it_did_not_finish(
    sorters: dict[str, Path],
) -> None:
    """Test an implementation that fails for large inputs is marked failed for those only."""
    result = invoke_comparison(str(sorters["fast"]), str(sorters["flaky"]))

    assert_exits_with(result, 1)
    startup, size_4, size_50 = parse_table_rows(result.stdout)
    assert [startup[0], size_4[0], size_50[0]] == ["startup", "4", "50"]
    assert "failed" not in startup[2]
    assert "failed" not in size_4[2]
    assert size_50[1] != "failed"
    assert size_50[2] == "failed"
    assert "flaky.py failed:" in result.stdout
    assert "Run failed for size 50" in result.stdout


def test_a_failed_reference_leaves_the_other_cells_without_ratios(
    sorters: dict[str, Path],
) -> None:
    """Test no ratio is shown for a size at which the reference failed."""
    result = invoke_comparison(
        str(sorters["flaky"]), str(sorters["fast"]), "--reference", "flaky.py"
    )

    assert_exits_with(result, 1)
    startup, size_4, size_50 = parse_table_rows(result.stdout)
    assert RATIO.findall(" ".join(startup))[0] == "1.00"
    assert len(RATIO.findall(" ".join(size_4))) == 2
    assert size_50[1] == "failed"
    assert size_50[2] != "failed"
    assert "x)" not in size_50[2]


@pytest.fixture
def fast_and_slow(use_fake_runners: UseFakeRunners) -> None:
    """Fake runners for a fast and a slow implementation."""
    use_fake_runners(
        {"fast": sort_correctly, "slow": sort_correctly},
        {"fast": FAST_SECONDS, "slow": SLOW_SECONDS},
    )


@pytest.mark.usefixtures("fast_and_slow")
def test_the_second_implementation_is_compared_to_the_first() -> None:
    """Test the median of each implementation is shown with its ratio to the first."""
    result = invoke_benchmark("--command", "fast", "--command", "slow")

    assert result.exit_code == 0, result.stdout
    assert "median in ms, ratio to fast" in result.stdout
    assert parse_table_rows(result.stdout) == [
        ["startup", "10.000 (1.00x)", "50.000 (5.00x)"],
        ["4", "10.000 (1.00x)", "50.000 (5.00x)"],
        ["8", "10.000 (1.00x)", "50.000 (5.00x)"],
    ]


@pytest.mark.usefixtures("fast_and_slow")
def test_a_non_first_reference_becomes_the_denominator() -> None:
    """Test the reference option chooses the implementation the ratios are relative to."""
    result = invoke_benchmark(
        "--command", "fast", "--command", "slow", "--reference", "slow"
    )

    assert result.exit_code == 0, result.stdout
    assert "ratio to slow" in result.stdout
    assert parse_table_rows(result.stdout)[1:] == [
        ["4", "10.000 (0.20x)", "50.000 (1.00x)"],
        ["8", "10.000 (0.20x)", "50.000 (1.00x)"],
    ]


def test_the_ratio_is_left_out_when_the_reference_took_no_measurable_time(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test no ratio is shown when the reference took no time."""
    use_fake_runners({"zero": sort_correctly, "other": sort_correctly}, {"zero": 0.0})

    result = invoke_benchmark("--command", "zero", "--command", "other")

    assert result.exit_code == 0, result.stdout
    assert parse_table_rows(result.stdout)[1] == ["4", "0.000", "1.000"]
