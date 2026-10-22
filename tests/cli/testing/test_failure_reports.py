"""Tests for how the test command reports failures: the matrix, grouped failures, descriptions."""

import json
import re
import shlex
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from typer.testing import Result

from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import FakeRunners, drop_last_above_five, sort_correctly
from helpers.support import (
    assert_exits_with,
    invoke_cli,
    parse_table_rows,
)

pytestmark = pytest.mark.integration


UseFakeTestRunners = Callable[..., FakeRunners]


LARGE_CASE = "generated:uniform:size=12:seed=5"


class ReportRun(NamedTuple):
    """The outcome of a test command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]


def extract_reproduce_arguments(output: str) -> list[str]:
    """Return the words of the reproduce command that the output of ``test`` prints."""
    line = next(
        line.strip().removeprefix("reproduce: ")
        for line in output.splitlines()
        if line.strip().startswith("reproduce: ")
    )
    return shlex.split(line)


UseFakeRunners = Callable[..., FakeRunners]


FIXTURES = {fixture.name: fixture.input_data for fixture in SortingProblem().fixtures()}


FAILING_FIXTURES = [name for name, values in FIXTURES.items() if len(values) > 5]


def drop_last_or_reverse(values: list[int]) -> list[int]:
    """Two kinds of wrong: loses an element of a long input, leaves a short one in reverse."""
    return values[:-1] if len(values) > 5 else sorted(values, reverse=True)


def render_failure_text(columns: int, monkeypatch: pytest.MonkeyPatch) -> str:
    """Return the output of a failing case on a terminal with the given number of columns."""
    monkeypatch.setenv("COLUMNS", str(columns))
    result = invoke_cli(
        "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
    )
    return result.stdout


@pytest.fixture(scope="module")
def drops_last_result(drops_last_executable: Path) -> Result:
    """The result of testing the sorter that loses its last element on a large case."""
    return invoke_cli(
        "test", "sorting", str(drops_last_executable), "--case", LARGE_CASE
    )


@pytest.fixture
def shrink_failure(
    use_fake_test_runners: UseFakeTestRunners,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> ReportRun:
    """Run a failing case of a problem whose shrink hook raises, writing a JSON report."""

    def explode(_self: SortingProblem, _input_data: list[int]) -> Iterator[list[int]]:
        message = "shrink exploded"
        raise RuntimeError(message)

    monkeypatch.setattr(SortingProblem, "shrink", explode)
    use_fake_test_runners({"drops": drop_last_above_five})
    path = tmp_path / "report.json"
    result = invoke_cli(
        *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
        *["--json", str(path)],
    )
    return ReportRun(result, json.loads(path.read_text()))


def test_a_failing_generated_case_is_described_with_a_window_around_the_difference(
    drops_last_result: Result,
) -> None:
    """Test a failing generated case is named, explained, and its output compared."""
    output = drops_last_result.stdout

    assert drops_last_result.exit_code == 1, output
    assert f"FAIL drops_last.py on {LARGE_CASE}" in output
    assert "message: Output length 11 does not match input length 12" in output
    assert "input: [" in output
    # The windows are around the first difference, the missing last element.
    assert re.search(
        r"expected: \[\.\.\., -?\d+\] \(12 values, index 11 shown\)", output
    )
    assert re.search(r"actual: \[\.\.\., -?\d+\] \(11 values, index 10 shown\)", output)
    assert "drops_last.py: 0/1 cases passed" in output


def test_a_failing_generated_case_is_shrunk_to_a_smaller_input(
    drops_last_result: Result,
) -> None:
    """Test a failing generated case is reported again with its shrunk input."""
    output = drops_last_result.stdout

    assert "shrunk case:" not in output
    assert "shrink note" not in output
    assert "shrunk input: [0, 0, 0, 0, 0, 0]" in output
    assert "shrunk message: Output length 5 does not match input length 6" in output


def test_a_failing_generated_case_is_reproducible_from_the_printed_command(
    drops_last_result: Result,
) -> None:
    """Test running the printed reproduce command fails the same case again."""
    arguments = extract_reproduce_arguments(drops_last_result.stdout)

    again = invoke_cli(*arguments[1:], "--no-shrink")

    assert arguments[:3] == ["algorithm-playground", "test", "sorting"]
    assert again.exit_code == 1
    assert f"FAIL drops_last on {LARGE_CASE}" in again.stdout


def test_a_failing_fixture_says_why_it_is_interesting(
    use_fake_test_runners: UseFakeTestRunners,
) -> None:
    """Test the failure of a fixture is described with the reason for the fixture."""
    use_fake_test_runners({"unsorted": list})

    result = invoke_cli(
        "test", "sorting", "--command", "unsorted", "--fixture", "two_unsorted"
    )

    assert result.exit_code == 1
    assert "fixture: two elements out of order" in result.stdout


def test_a_generated_failure_has_no_fixture_line(
    use_fake_test_runners: UseFakeTestRunners,
) -> None:
    """Test the failure of a generated case has no fixture description."""
    use_fake_test_runners({"drops": drop_last_above_five})

    result = invoke_cli(
        "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
    )

    assert result.exit_code == 1
    assert "FAIL drops on generated:" in result.stdout
    assert "    fixture:" not in result.stdout


def test_a_shrink_hook_that_raises_is_noted_in_the_report(
    shrink_failure: ReportRun,
) -> None:
    """Test a shrink hook that raises is explained in the printed failure."""
    assert shrink_failure.result.exit_code == 1
    assert (
        "shrink note: the problem's shrink hook raised RuntimeError: shrink exploded"
        in shrink_failure.result.stdout
    )


def test_a_shrink_hook_that_raises_is_noted_in_the_json(
    shrink_failure: ReportRun,
) -> None:
    """Test a shrink hook that raises is recorded in the JSON report as a note."""
    (outcome,) = shrink_failure.report["implementations"][0]["outcomes"]

    assert outcome["shrink_note"] == (
        "the problem's shrink hook raised RuntimeError: shrink exploded"
    )
    assert outcome["shrunk"] is None


def test_no_shrink_leaves_the_failure_unshrunk(drops_last_executable: Path) -> None:
    """Test the no-shrink option reports the failure without a shrunk input."""
    result = invoke_cli(
        "test",
        "sorting",
        str(drops_last_executable),
        "--case",
        LARGE_CASE,
        "--no-shrink",
    )

    assert result.exit_code == 1
    assert "shrunk" not in result.stdout


def test_identical_error_messages_are_reported_once(crashing_executable: Path) -> None:
    """Test cases that fail with the same error share one message and list the cases."""
    result = invoke_cli(
        "test",
        "sorting",
        str(crashing_executable),
        "--fixture",
        "single",
        "--fixture",
        "empty",
        "--fixture",
        "two_sorted",
    )

    assert result.exit_code == 1
    assert result.stdout.count("exited with code 3") == 1
    assert result.stdout.count("kaboom") == 1
    assert "crashing.py: 3 of 3 cases did not pass" in result.stdout
    assert "same failure on: fixture:single, fixture:two_sorted" in result.stdout


def test_failures_beyond_the_maximum_are_only_listed(
    use_fake_test_runners: UseFakeTestRunners,
) -> None:
    """Test only the maximum number of failures is described in full."""

    def unsorted_or_short(values: list[int]) -> list[int]:
        return values[:-1] if len(values) > 5 else list(values)

    use_fake_test_runners({"mixed": unsorted_or_short})

    result = invoke_cli(
        "test",
        "sorting",
        *["--command", "mixed"],
        *["--fixture", "two_unsorted", "--fixture", "reverse_sorted"],
        *["--fixture", "duplicates"],
        "--maximum-failures",
        "1",
    )

    assert result.exit_code == 1
    assert result.stdout.count("FAIL mixed on") == 1
    assert "more failing cases are not described" in result.stdout


def test_the_reproduce_command_carries_a_timeout_that_is_not_the_default(
    use_fake_test_runners: UseFakeTestRunners,
) -> None:
    """Test the reproduce command repeats a timeout that differs from the default."""
    use_fake_test_runners({"drops": drop_last_above_five})

    result = invoke_cli(
        *["test", "sorting", "--command", "drops", "--case", LARGE_CASE],
        *["--timeout", "7.5", "--no-shrink"],
    )

    arguments = extract_reproduce_arguments(result.stdout)
    assert arguments[arguments.index("--timeout") + 1] == "7.5"
    assert arguments[-2:] == ["--case", LARGE_CASE]


def test_the_reproduce_command_has_no_timeout_when_it_is_the_default(
    use_fake_test_runners: UseFakeTestRunners,
) -> None:
    """Test the reproduce command leaves out the timeout when it has the default value."""
    use_fake_test_runners({"drops": drop_last_above_five})

    result = invoke_cli(
        "test", "sorting", "--command", "drops", "--case", LARGE_CASE, "--no-shrink"
    )

    assert "--timeout" not in extract_reproduce_arguments(result.stdout)


def test_the_reproduce_command_carries_every_option_that_changes_the_outcome(
    use_fake_test_runners: UseFakeTestRunners,
    tmp_path: Path,
) -> None:
    """Test the reproduce command repeats the options that affect how a case runs."""
    configuration = tmp_path / "reproduce.toml"
    configuration.write_text("")
    module = tmp_path / "reproduce_problem_module.py"
    module.write_text("VALUE = 1\n")
    use_fake_test_runners({"unsorted": list})

    result = invoke_cli(
        *["test", "sorting", "--command", "unsorted", "--fixture", "two_unsorted"],
        *["--inherit-environment", "--no-build"],
        *["--configuration", str(configuration), "--problem-module", str(module)],
    )

    arguments = extract_reproduce_arguments(result.stdout)
    assert "--inherit-environment" in arguments
    assert "--no-build" in arguments
    assert arguments[arguments.index("--configuration") + 1] == str(configuration)
    assert arguments[arguments.index("--problem-module") + 1] == str(module)


def test_the_reproduce_command_names_a_configured_implementation(
    configure: Callable[..., Path],
    unsorted_output_executable: Path,
) -> None:
    """Test the reproduce command names a configured implementation instead of its command."""
    configure(
        "[[implementations]]\n"
        'name = "configured-unsorted"\n'
        'problem = "sorting"\n'
        f"command = {json.dumps([sys.executable, str(unsorted_output_executable)])}\n"
    )

    result = invoke_cli("test", "sorting", "--fixture", "two_unsorted")

    assert result.exit_code == 1
    assert (
        "reproduce: algorithm-playground test sorting configured-unsorted --case"
        in (result.stdout)
    )


def test_the_fixtures_are_one_row_and_only_failing_ones_get_a_row_of_their_own(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test passing fixtures are counted in one row and each failing fixture has its own."""
    use_fake_test_runners({"good": sort_correctly, "bad": drop_last_above_five})

    result = invoke_cli("test", "sorting", "--command", "good", "--command", "bad")

    assert_exits_with(result, 1)
    rows = parse_table_rows(result.stdout)
    failing = len(FAILING_FIXTURES)
    assert rows[0] == ["fixtures", "24/24", f"{24 - failing}/24"]
    assert [row[0] for row in rows[1 : 1 + failing]] == FAILING_FIXTURES
    assert all(row[1:] == ["PASS", "FAIL"] for row in rows[1 : 1 + failing])
    assert rows[1 + failing][0] == "uniform"


def test_all_passing_fixtures_are_a_single_row(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test fixtures that all pass are summarized in one row, followed by the distributions."""
    use_fake_test_runners({"good": sort_correctly})

    result = invoke_cli("test", "sorting", "--command", "good")

    assert result.exit_code == 0, result.stdout
    rows = parse_table_rows(result.stdout)
    assert rows[0] == ["fixtures", "24/24"]
    assert [row[0] for row in rows[1:]] == [
        generator.name for generator in SortingProblem().generators()
    ]


def test_the_expanded_fixture_rows_are_indented_under_the_counted_row(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test the rows of failing fixtures are indented below the row that counts fixtures."""
    use_fake_test_runners({"bad": drop_last_above_five})

    result = invoke_cli("test", "sorting", "--command", "bad", "--random-cases", "0")

    lines = [line for line in result.stdout.splitlines() if line.startswith("│")]
    assert lines[0].startswith("│ fixtures")
    assert lines[1].startswith("│   ")


def test_verbose_shows_every_fixture_and_no_counted_row(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test the verbose option gives every fixture its own row and no counting row."""
    use_fake_test_runners({"good": sort_correctly, "bad": drop_last_above_five})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "good",
        "--command",
        "bad",
        "--verbose",
        "--random-cases",
        "0",
    )

    rows = parse_table_rows(result.stdout)
    assert [row[0] for row in rows] == list(FIXTURES)
    assert {row[1] for row in rows} == {"PASS"}
    assert {row[2] for row in rows} == {"PASS", "FAIL"}
    assert "fixtures" not in {row[0] for row in rows}


def test_distributions_are_named_without_a_prefix_below_a_rule(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test generated cases are grouped by distribution name, below a rule under fixtures."""
    use_fake_test_runners({"good": sort_correctly})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "good",
        "--distribution",
        "sorted",
        "--random-cases",
        "4",
    )

    assert [row[0] for row in parse_table_rows(result.stdout)] == [
        "fixtures",
        "sorted",
    ]
    assert "generated:sorted" not in result.stdout
    assert "├" in result.stdout


def test_a_matrix_with_only_generated_cases_has_no_rule(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test no rule is drawn when there are no fixtures to separate from the generated cases."""
    use_fake_test_runners({"good": sort_correctly})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "good",
        "--no-fixtures",
        "--random-cases",
        "3",
    )

    assert "├" not in result.stdout
    assert "fixtures" not in {row[0] for row in parse_table_rows(result.stdout)}


def test_a_long_case_name_is_folded_not_cut(
    use_fake_test_runners: UseFakeRunners,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a row label that is too wide for the terminal is folded over lines, not cut."""
    monkeypatch.setenv("COLUMNS", "40")
    use_fake_test_runners(
        {"one": sort_correctly, "two": sort_correctly, "six": sort_correctly}
    )

    result = invoke_cli(
        "test",
        "sorting",
        *["--command", "one", "--command", "two", "--command", "six"],
        *[
            "--distribution",
            "median_of_three_killer",
            "--random-cases",
            "1",
            "--no-fixtures",
        ],
    )

    assert "…" not in result.stdout
    assert "median_of_three" in result.stdout.replace("\n", "").replace(
        "│", ""
    ).replace(" ", "")


def test_failures_that_shrink_to_the_same_input_are_one_block(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test failures that shrink to the same input are described once."""
    use_fake_test_runners({"bad": drop_last_above_five})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "bad",
        "--fixture",
        "duplicates",
        "--case",
        LARGE_CASE,
    )

    assert_exits_with(result, 1)
    assert result.stdout.count("FAIL bad on") == 2  # the shrunk one, and the fixture
    assert "shrunk input: [0, 0, 0, 0, 0, 0]" in result.stdout


def test_many_generated_failures_become_one_block_naming_the_others(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test generated failures beyond the shrunk ones are grouped in one block."""
    use_fake_test_runners({"bad": drop_last_above_five})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "bad",
        "--no-fixtures",
        "--random-cases",
        "6",
        "--seed",
        "3",
    )

    blocks = [
        line for line in result.stdout.splitlines() if line.startswith("FAIL bad on")
    ]
    shrunk_blocks = re.findall(r"shrunk input: (.*)", result.stdout)
    assert len(blocks) == 2  # the three that were shrunk, and the rest
    assert shrunk_blocks == ["[0, 0, 0, 0, 0, 0]"]
    assert "same failure on: " in result.stdout


def test_the_smallest_failing_input_comes_first(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test fixtures come before generated cases, and the smaller generated case leads."""
    use_fake_test_runners({"mixed": drop_last_or_reverse})

    result = invoke_cli(
        "test",
        "sorting",
        *["--command", "mixed", "--no-shrink", "--maximum-failures", "9"],
        *[
            "--case",
            "generated:uniform:size=30:seed=1",
            "--case",
            "generated:uniform:size=9:seed=1",
        ],
        *["--case", "fixture:two_unsorted"],
    )

    order = re.findall(r"^FAIL mixed on (\S+)$", result.stdout, re.MULTILINE)
    # A fixture comes before generated cases, and the smaller generated case leads the
    # block of its kind of failure, with the larger one listed after "same failure on".
    assert order == ["fixture:two_unsorted", "generated:uniform:size=9:seed=1"]
    assert "same failure on: generated:uniform:size=30:seed=1" in result.stdout


def test_a_shrunk_group_comes_before_unshrunk_failures(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test the failures that were shrunk are described before those that were not."""
    use_fake_test_runners({"bad": drop_last_above_five})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "bad",
        "--fixture",
        "reverse_sorted",
        "--case",
        LARGE_CASE,
    )

    order = re.findall(r"^FAIL bad on (\S+)$", result.stdout, re.MULTILINE)
    assert order == [LARGE_CASE, "fixture:reverse_sorted"]


def test_failures_of_another_category_are_a_block_of_their_own(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test failures with a different cause are not grouped with the others."""
    use_fake_test_runners({"mixed": drop_last_or_reverse})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "mixed",
        "--no-shrink",
        "--maximum-failures",
        "9",
        *["--fixture", "two_unsorted", "--fixture", "three_321"],
        *["--fixture", "reverse_sorted", "--fixture", "duplicates"],
    )

    headers = re.findall(r"^FAIL mixed on (\S+)$", result.stdout, re.MULTILINE)
    assert sorted(headers) == ["fixture:reverse_sorted", "fixture:two_unsorted"]
    assert "same failure on: fixture:duplicates" in result.stdout
    assert "same failure on: fixture:three_321" in result.stdout


def test_cases_left_unshrunk_by_the_limit_say_so_once_per_block(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test a block says once that its cases were not shrunk because of the limit."""
    use_fake_test_runners({"bad": drop_last_above_five})

    result = invoke_cli(
        "test",
        "sorting",
        "--command",
        "bad",
        "--no-fixtures",
        "--random-cases",
        "12",
        "--seed",
        "1",
    )

    assert (
        "shrink note: not shrunk: the limit of 3 shrunk cases per implementation"
        in result.stdout
    )
    assert result.stdout.count("shrink note:") == 1


def test_the_json_report_has_every_failure_even_when_blocks_are_grouped(
    use_fake_test_runners: UseFakeRunners, tmp_path: Path
) -> None:
    """Test the JSON report lists each failing case, however the printed blocks are grouped."""
    use_fake_test_runners({"bad": drop_last_above_five})
    path = tmp_path / "report.json"

    invoke_cli("test", "sorting", "--command", "bad", "--json", str(path))

    outcomes = json.loads(path.read_text())["implementations"][0]["outcomes"]
    failing = [outcome for outcome in outcomes if outcome["status"] == "failed"]
    assert len(failing) > 10
    assert {outcome["category"] for outcome in failing} == {"wrong length"}


def test_a_wide_terminal_shows_the_whole_input(
    use_fake_test_runners: UseFakeRunners, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test a wide terminal has room for the whole input in the description of a failure."""
    use_fake_test_runners({"drops": drop_last_above_five})

    text = render_failure_text(300, monkeypatch)

    assert "(12 values)" not in text
    assert re.search(r"input: \[(-?\d+, ){11}-?\d+\]", text)


def test_a_narrow_terminal_shortens_it_to_fit_a_line(
    use_fake_test_runners: UseFakeRunners, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test a narrow terminal shortens the lines that describe a failure to its width."""
    use_fake_test_runners({"drops": drop_last_above_five})

    text = render_failure_text(70, monkeypatch)

    lines = [
        line
        for line in text.splitlines()
        if line.strip().startswith(("input:", "expected:", "actual:"))
    ]
    assert len(lines) == 3
    assert all(len(line) <= 70 for line in lines), lines
    assert "(12 values" in text
