"""Tests for which cases the test command runs, against which implementations."""

import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import Result

from helpers.fakes import FakeRunners
from helpers.misbehaving import count_distinct_values
from helpers.registration import register_faulty_problem, register_other_problem
from helpers.scoring import keep_as_is, register_near_sorting_problem
from helpers.support import (
    Configure,
    assert_exits_with,
    invoke_cli,
    parse_table_rows,
)

pytestmark = pytest.mark.integration


def format_toml_list(*items: str) -> str:
    """Format the items as a TOML array of strings."""
    return json.dumps(list(items))


def build_configured_entry(
    name: str,
    script: Path,
    *,
    build_command: tuple[str, ...] | None = None,
    problem: str = "sorting",
    extra_lines: tuple[str, ...] = (),
) -> str:
    """Build the text of one ``[[implementations]]`` entry that runs a Python script.

    Args:
        name: The name of the implementation.
        script: The Python script the implementation runs.
        build_command: The build command, if the implementation has one.
        problem: The name of the problem the implementation solves.
        extra_lines: Further lines to add to the entry.

    Returns:
        The entry, ending in a newline.
    """
    lines = [
        "[[implementations]]",
        f"name = {json.dumps(name)}",
        f'problem = "{problem}"',
        f"command = {format_toml_list(sys.executable, str(script))}",
    ]
    if build_command is not None:
        lines.append(f"build_command = {format_toml_list(*build_command)}")
    lines.extend(extra_lines)
    return "\n".join(lines) + "\n"


def build_python_command_text(script: Path) -> str:
    """Build the text of a command line that runs a script with the current interpreter."""
    return shlex.join([sys.executable, str(script)])


UseFakeTestRunners = Callable[..., FakeRunners]


LARGE_CASE = "generated:uniform:size=12:seed=5"


UseFakeRunners = Callable[..., FakeRunners]


FIXTURES_MESSAGE = "The problem's fixtures hook raised RuntimeError: fixtures exploded."


GENERATORS_MESSAGE = (
    "The problem's generators hook raised RuntimeError: generators exploded."
)


GENERATOR_MESSAGE = (
    "The problem's 'broken' generator hook raised RuntimeError: generator exploded."
)


def assert_hook_failure(result: Result, message: str) -> None:
    """Assert the command exited with code 1 and the message, without a traceback."""
    assert_exits_with(result, 1)
    output = f"{result.stdout}{result.stderr}"
    assert message in output
    assert "Traceback" not in output


def test_python_sort_passes_every_fixture(
    python_sort_executable: Path, sorting_fixture_count: int
) -> None:
    """Test the reference Python sorter passes every fixture and the generated case."""
    result = invoke_cli(
        "test", "sorting", str(python_sort_executable), "--random-cases", "1"
    )

    assert result.exit_code == 0, result.stdout
    total = sorting_fixture_count
    assert (
        f"python_sort.py: {total + 1}/{total + 1} cases passed "
        f"({total}/{total} fixtures, 1/1 generated)"
    ) in result.stdout


def test_unknown_problem_exits_with_code_2_and_names_the_registered_ones_on_standard_error(
    python_sort_executable: Path,
) -> None:
    """Test an unknown problem is a usage error that lists the registered problems."""
    result = invoke_cli("test", "not-a-problem", str(python_sort_executable))

    assert_exits_with(result, 2)
    assert result.stderr.startswith(
        "Unknown problem 'not-a-problem'. Registered problems:"
    )
    assert "sorting" in result.stderr
    assert result.stdout == ""


@pytest.mark.usefixtures("only_first_fixture")
def test_malformed_output_is_reported_per_case(
    truncated_output_executable: Path,
) -> None:
    """Test an implementation that writes a malformed output errors every case."""
    result = invoke_cli(
        "test", "sorting", str(truncated_output_executable), "--random-cases", "1"
    )

    # Every case errors, and the CLI exits with the failure code instead of crashing.
    assert_exits_with(result, 1)
    assert "ERROR" in result.stdout
    assert "0/2 cases passed (0/1 fixtures, 0/1 generated)" in result.stdout


@pytest.fixture(scope="module")
def mixed_result(
    python_sort_executable: Path, unsorted_output_executable: Path
) -> Result:
    """The result of testing a correct and a wrong sorter on four fixtures."""
    return invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        str(unsorted_output_executable),
        *["--fixture", "empty", "--fixture", "already_sorted"],
        *["--fixture", "two_unsorted", "--fixture", "reverse_sorted"],
    )


def test_two_implementations_share_one_matrix(mixed_result: Result) -> None:
    """Test two implementations are compared in one matrix of passes and failures."""
    assert "python_sort.py" in mixed_result.stdout
    assert "unsorted_output.py" in mixed_result.stdout
    assert "PASS" in mixed_result.stdout
    assert "FAIL" in mixed_result.stdout


def test_each_implementation_gets_a_summary_line(mixed_result: Result) -> None:
    """Test every implementation is summarized with the cases it passed."""
    assert "python_sort.py: 4/4 cases passed" in mixed_result.stdout
    assert "unsorted_output.py: 2/4 cases passed" in mixed_result.stdout


def test_a_failing_implementation_makes_the_command_exit_with_one(
    mixed_result: Result,
) -> None:
    """Test a failing case ends the command with exit code 1 and names the case."""
    assert_exits_with(mixed_result, 1)
    assert "FAIL unsorted_output.py on fixture:two_unsorted" in mixed_result.stdout


@pytest.mark.usefixtures("only_first_fixture")
def test_an_error_prints_every_line_of_the_message(crashing_executable: Path) -> None:
    """Test an implementation that crashes has its whole error message printed."""
    result = invoke_cli("test", "sorting", str(crashing_executable))

    assert_exits_with(result, 1)
    assert "ERROR" in result.stdout
    assert "exited with code 3" in result.stdout
    assert "kaboom" in result.stdout


@pytest.mark.usefixtures("only_first_fixture")
def test_configuration_without_positionals_runs_every_configured_implementation(
    configure: Configure,
    python_sort_executable: Path,
) -> None:
    """Test the implementations configured for the problem run when none is named."""
    register_other_problem("searching")
    configure(
        build_configured_entry("configured-sorter", python_sort_executable),
        build_configured_entry(
            "other-problem", python_sort_executable, problem="searching"
        ),
    )

    result = invoke_cli("test", "sorting")

    assert result.exit_code == 0, result.stdout
    assert "configured-sorter: 1/1 cases passed" in result.stdout
    assert "other-problem" not in result.stdout


@pytest.mark.usefixtures("only_first_fixture")
def test_command_runs_a_script_without_the_executable_bit(
    plain_sort_script: Path,
) -> None:
    """Test a script without the executable bit runs through an interpreter command."""
    assert not plain_sort_script.stat().st_mode & 0o111

    result = invoke_cli(
        "test", "sorting", "--command", build_python_command_text(plain_sort_script)
    )

    assert result.exit_code == 0, result.stdout
    assert "plain sort: 1/1 cases passed" in result.stdout


def test_generated_cases_are_summarized_per_distribution(
    python_sort_executable: Path,
) -> None:
    """Test generated cases are counted in one row for each distribution."""
    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "--no-fixtures",
        "--random-cases",
        "3",
        "--maximum-size",
        "8",
        "--seed",
        "1",
    )

    assert result.exit_code == 0, result.stdout
    assert parse_table_rows(result.stdout) == [
        ["uniform", "1/1"],
        ["sorted", "1/1"],
        ["reversed", "1/1"],
    ]
    assert "python_sort.py: 3/3 cases passed" in result.stdout


def test_case_runs_exactly_the_named_cases(python_sort_executable: Path) -> None:
    """Test the case option runs the named cases together with the chosen fixture."""
    result = invoke_cli(
        "test",
        "sorting",
        str(python_sort_executable),
        "--case",
        "fixture:empty",
        "--case",
        LARGE_CASE,
        "--fixture",
        "single",
    )

    assert result.exit_code == 0, result.stdout
    assert parse_table_rows(result.stdout) == [
        ["fixtures", "2/2"],
        ["uniform", "1/1"],
    ]


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--case", "fixture:nope"], "No fixture named 'nope'"),
        (["--fixture", "nope"], "No fixture named 'nope'"),
        (["--case", "nonsense"], "Unrecognized case identifier"),
        (["--case", "shrunk:fixture:empty"], "cannot be replayed"),
        (["--case", "generated:nope:size=1:seed=1"], "Unknown distribution 'nope'"),
        (["--distribution", "nope"], "Unknown distribution 'nope'"),
        (["--no-fixtures", "--random-cases", "0"], "no cases to run"),
        (
            ["--case", "fixture:empty", "--random-cases", "3"],
            "cannot be combined with",
        ),
        (["--fixture", "empty", "--distribution", "uniform"], "--distribution"),
        (["--case", "generated:uniform:size=05:seed=1"], "no valid 'size=N' part"),
        (["--case", "generated:uniform:size=+5:seed=1"], "no valid 'size=N' part"),
        (["--case", "generated:uniform:size=1_0:seed=1"], "no valid 'size=N' part"),
        (["--case", "generated:uniform:size=5:seed= 1"], "no valid 'seed=N' part"),
        (["--case", "generated:uniform:size=5:seed=001"], "no valid 'seed=N' part"),
        (["--maximum-size", "vertices=5"], "size=N"),
    ],
)
def test_bad_case_options_are_usage_errors(
    python_sort_executable: Path, options: list[str], message: str
) -> None:
    """Test case options that name nothing valid are usage errors and run nothing."""
    result = invoke_cli("test", "sorting", str(python_sort_executable), *options)

    assert_exits_with(result, 2)
    assert message in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("options", "runs"),
    [
        (["--case", "fixture:single", "--case", "fixture:single"], 1),
        (["--fixture", "single", "--case", "fixture:single"], 1),
        (["--case", LARGE_CASE, "--case", LARGE_CASE, "--fixture", "empty"], 2),
    ],
    ids=["same case twice", "fixture and case", "generated twice"],
)
def test_a_case_named_twice_runs_once(
    use_fake_test_runners: UseFakeTestRunners,
    options: list[str],
    runs: int,
) -> None:
    """Test a case that is selected more than once is run once."""
    runners = use_fake_test_runners({"sorter": sorted})

    result = invoke_cli("test", "sorting", "--command", "sorter", *options)

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(runners.collect_inputs_of("sorter")) == runs


@pytest.mark.parametrize(
    ("fault", "message", "arguments"),
    [
        ("fixtures", FIXTURES_MESSAGE, []),
        ("fixtures", FIXTURES_MESSAGE, ["--fixture", "one"]),
        ("fixtures", FIXTURES_MESSAGE, ["--case", "fixture:one"]),
        ("generators", GENERATORS_MESSAGE, []),
        ("generators", GENERATORS_MESSAGE, ["--no-fixtures"]),
        (
            "generators",
            GENERATORS_MESSAGE,
            ["--case", "generated:uniform:size=3:seed=1"],
        ),
        ("generator", GENERATOR_MESSAGE, []),
        (
            "generator",
            GENERATOR_MESSAGE,
            ["--case", "generated:broken:size=3:seed=1"],
        ),
    ],
)
def test_the_hook_is_named_and_the_exit_code_is_1(
    use_fake_test_runners: UseFakeRunners,
    fault: str,
    message: str,
    arguments: list[str],
) -> None:
    """Test a hook that raises ends the test command with its name and exit code 1."""
    use_fake_test_runners({"counter": count_distinct_values})
    name = register_faulty_problem(fault)

    result = invoke_cli("test", name, "--command", "counter", "--no-shrink", *arguments)

    assert_hook_failure(result, message)


def test_a_generator_that_works_is_not_reported(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test a working distribution passes even if another distribution of the problem raises."""
    use_fake_test_runners({"counter": count_distinct_values})
    name = register_faulty_problem("generator")

    result = invoke_cli(
        "test", name, "--command", "counter", "--distribution", "uniform"
    )

    assert result.exit_code == 0, result.stdout + result.stderr


def test_a_verify_that_raises_is_an_error_outcome_not_a_crash(
    use_fake_test_runners: UseFakeRunners,
) -> None:
    """Test a verify hook that raises makes the case an error and the command exit with one."""
    use_fake_test_runners({"counter": count_distinct_values})
    name = register_faulty_problem("verify")

    result = invoke_cli("test", name, "--command", "counter", "--fixture", "one")

    assert_exits_with(result, 1)
    assert "verify exploded" in result.stdout


def test_the_summary_names_the_mean_score_of_a_scored_problem(
    use_fake_test_runners: UseFakeTestRunners,
) -> None:
    """Test the summary line of a scored problem gives the mean score over the scored cases."""
    use_fake_test_runners({"lazy": keep_as_is})
    name = register_near_sorting_problem()

    result = invoke_cli(
        *["test", name, "--command", "lazy", "--no-shrink"],
        *["--fixture", "two_unsorted", "--fixture", "reverse_sorted"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "lazy: 2/2 cases passed" in result.stdout
    assert "mean inversions 23 over 2 scored cases" in result.stdout
