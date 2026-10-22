"""Tests for the scores the benchmark command reports from the problem's verifier."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from algorithm_playground.core import Size, generate_case, get_default_generator
from helpers.fakes import FakeRunners, crash, sort_correctly
from helpers.scoring import (
    NearSortingProblem,
    build_lazy_then_exact,
    count_inversions,
    keep_as_is,
    register_near_sorting_problem,
)
from helpers.support import assert_exits_with, invoke_cli, parse_table_rows

pytestmark = pytest.mark.integration


UseFakeRunners = Callable[..., FakeRunners]


def compute_generated_inversions(size: int, seed: int) -> int:
    """Count the inversions of the default generator's input for a size and seed."""
    generator = get_default_generator(NearSortingProblem())
    return count_inversions(
        generate_case(generator, size=Size(size=size), seed=seed).input_data
    )


def test_a_scored_problem_gets_a_table_of_median_scores(
    use_fake_runners: UseFakeRunners, tmp_path: Path
) -> None:
    """Test a problem that scores outputs gets a table with the median score per size."""
    use_fake_runners({"exact": sort_correctly, "lazy": keep_as_is})
    name = register_near_sorting_problem()
    json_path = tmp_path / "report.json"

    result = invoke_cli(
        *["benchmark", name, "--command", "exact", "--command", "lazy"],
        *["--sizes", "4,8", "--seed", "3", "--repetitions", "1", "--warmup", "0"],
        *["--no-plot", "--json", str(json_path)],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    title = f"inversions — {name}"
    assert title in result.stdout
    assert parse_table_rows(result.stdout[result.stdout.index(title) :]) == [
        ["4", "0", str(compute_generated_inversions(4, 3))],
        ["8", "0", str(compute_generated_inversions(8, 3))],
    ]
    report = json.loads(json_path.read_text())
    assert report["score_name"] == "inversions"
    exact, lazy = report["implementations"]
    assert [record["scores"] for record in exact["results"]] == [[0.0], [0.0]]
    assert [record["scores"] for record in lazy["results"]] == [
        [float(compute_generated_inversions(4, 3))],
        [float(compute_generated_inversions(8, 3))],
    ]


def test_an_unscored_problem_has_no_score_table_or_name(
    use_fake_runners: UseFakeRunners, tmp_path: Path
) -> None:
    """Test the sorting problem, which scores nothing, reports no score name and no scores."""
    use_fake_runners({"sorter": sort_correctly})
    json_path = tmp_path / "report.json"

    result = invoke_cli(
        *["benchmark", "sorting", "--command", "sorter", "--sizes", "4"],
        *["--repetitions", "1", "--warmup", "0", "--no-plot", "--json", str(json_path)],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert result.stdout.count(" — sorting") == 1
    report = json.loads(json_path.read_text())
    assert report["score_name"] is None
    assert report["implementations"][0]["results"][0]["scores"] == []


def test_the_score_table_marks_the_cells_of_a_failed_implementation(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test the score cells of an implementation read failed where it failed and skipped after."""

    def fail_above_four(values: list[int]) -> list[int]:
        return crash(values) if len(values) > 4 else keep_as_is(values)

    use_fake_runners({"lazy": keep_as_is, "flaky": fail_above_four})
    name = register_near_sorting_problem()

    result = invoke_cli(
        *["benchmark", name, "--command", "lazy", "--command", "flaky"],
        *["--sizes", "4,8,16", "--seed", "3", "--repetitions", "1", "--warmup", "0"],
        "--no-plot",
    )

    assert_exits_with(result, 1)
    title = f"inversions — {name}"
    assert parse_table_rows(result.stdout[result.stdout.index(title) :]) == [
        ["4", "3", "3"],
        ["8", str(compute_generated_inversions(8, 3)), "failed"],
        ["16", str(compute_generated_inversions(16, 3)), "skipped"],
    ]


def test_a_median_between_two_scores_shows_two_decimals(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a median that is not a whole number is shown with two decimals."""
    use_fake_runners({"wobbly": build_lazy_then_exact()})
    name = register_near_sorting_problem()

    result = invoke_cli(
        *["benchmark", name, "--command", "wobbly", "--sizes", "4", "--seed", "3"],
        *["--repetitions", "2", "--warmup", "0", "--no-plot"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    title = f"inversions — {name}"
    assert parse_table_rows(result.stdout[result.stdout.index(title) :]) == [
        ["4", "1.50"]
    ]


def test_there_is_no_score_table_without_verification(
    use_fake_runners: UseFakeRunners,
) -> None:
    """Test a scored problem gets no score table when outputs are not verified."""
    use_fake_runners({"lazy": keep_as_is})
    name = register_near_sorting_problem()

    result = invoke_cli(
        *["benchmark", name, "--command", "lazy", "--sizes", "4", "--no-verify"],
        *["--repetitions", "1", "--warmup", "0", "--no-plot"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert f"inversions — {name}" not in result.stdout
