"""Tests for choosing the input and the implementation that the debug command steps through."""

import json
import shlex
import sys
from pathlib import Path

import pytest

from algorithm_playground.core import Problem, resolve_case
from algorithm_playground.problems.sorting import SortingProblem
from helpers.support import (
    Configure,
    assert_exits_with,
    invoke_cli,
    read_logged_inputs,
)

pytestmark = pytest.mark.integration


def write_saved_input(directory: Path, values: list[int]) -> Path:
    """Write the values as a saved input of the sorting problem; return the file."""
    path = directory / "saved.bin"
    SortingProblem().serialize_input(values, path)
    return path


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


def test_the_input_in_the_file_is_the_input_that_runs(
    recording_sorter: tuple[Path, Path], tmp_path: Path
) -> None:
    """Test debug runs the input that is stored in the input file."""
    script, log = recording_sorter

    result = invoke_cli(
        "debug",
        "sorting",
        str(script),
        "--input-file",
        str(write_saved_input(tmp_path, [5, 3, 9])),
    )

    assert result.exit_code == 0, result.stderr
    assert "Output verified." in result.stdout
    assert read_logged_inputs(log) == [[5, 3, 9]]


def test_an_empty_input_can_be_run(
    recording_sorter: tuple[Path, Path], tmp_path: Path
) -> None:
    """Test an input file that holds no values is run."""
    script, log = recording_sorter

    result = invoke_cli(
        "debug",
        "sorting",
        str(script),
        "--input-file",
        str(write_saved_input(tmp_path, [])),
    )

    assert result.exit_code == 0, result.stderr
    assert read_logged_inputs(log) == [[]]


@pytest.mark.parametrize(
    ("extra", "named"),
    [
        (["--seed", "3"], "--seed"),
        (["--size", "4"], "--size"),
        (["--distribution", "sorted"], "--distribution"),
        (["--seed", "3", "--size", "4"], "--seed, --size"),
    ],
)
def test_options_that_generate_an_input_cannot_be_combined_with_a_file(
    python_sort_executable: Path,
    tmp_path: Path,
    extra: list[str],
    named: str,
) -> None:
    """Test an input file is a usage error together with options that generate an input."""
    result = invoke_cli(
        "debug",
        "sorting",
        str(python_sort_executable),
        "--input-file",
        str(write_saved_input(tmp_path, [1])),
        *extra,
    )

    assert_exits_with(result, 2)
    assert (
        f"--input-file selects an exact input, so it cannot be combined with {named}"
        in result.stderr
    )
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("selector", "extra", "named"),
    [
        (["--fixture", "empty"], ["--seed", "1"], "--seed"),
        (["--case", "fixture:empty"], ["--size", "3"], "--size"),
        (["--fixture", "empty"], ["--distribution", "sorted"], "--distribution"),
    ],
)
def test_options_that_generate_an_input_cannot_be_combined_with_a_fixture_or_case(
    python_sort_executable: Path,
    selector: list[str],
    extra: list[str],
    named: str,
) -> None:
    """Test a fixture or case is a usage error together with options that generate an input."""
    result = invoke_cli(
        "debug", "sorting", str(python_sort_executable), *selector, *extra
    )

    assert_exits_with(result, 2)
    assert (
        f"{selector[0]} selects an exact input, so it cannot be combined with {named}"
        in result.stderr
    )


def test_a_seed_of_zero_is_still_a_seed(python_sort_executable: Path) -> None:
    """Test a seed of zero counts as a given seed when it is combined with a fixture."""
    result = invoke_cli(
        "debug",
        "sorting",
        str(python_sort_executable),
        "--fixture",
        "empty",
        "--seed",
        "0",
    )

    assert_exits_with(result, 2)
    assert "cannot be combined with --seed" in result.stderr


def test_a_file_cannot_be_combined_with_a_fixture_or_a_case(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test an input file and a fixture together are a usage error."""
    path = write_saved_input(tmp_path, [1])

    result = invoke_cli(
        "debug",
        "sorting",
        str(python_sort_executable),
        "--input-file",
        str(path),
        "--fixture",
        "empty",
    )

    assert_exits_with(result, 2)
    assert "--fixture and --input-file cannot be used together" in result.stderr


def test_the_default_input_is_unchanged_without_those_options(
    recording_sorter: tuple[Path, Path],
) -> None:
    """Test the input that debug generates by default is the one of the documented options."""
    script, log = recording_sorter

    invoke_cli("debug", "sorting", str(script))
    invoke_cli(
        "debug",
        "sorting",
        str(script),
        "--seed",
        "0",
        "--size",
        "16",
        "--distribution",
        "small_range",
    )

    first, second = read_logged_inputs(log)
    assert first == second
    assert len(first) == 16


def test_a_file_that_is_not_an_input_is_a_usage_error_naming_the_problem(
    python_sort_executable: Path, tmp_path: Path
) -> None:
    """Test a file that is not an input of the problem is a usage error naming the problem."""
    path = tmp_path / "garbage.bin"
    path.write_bytes(b"\x07\x00")

    result = invoke_cli(
        "debug", "sorting", str(python_sort_executable), "--input-file", str(path)
    )

    assert_exits_with(result, 2)
    assert (
        f"Could not read {path} as an input of problem 'sorting': BinaryFormatError"
        in result.stderr
    )


def test_a_missing_file_is_a_usage_error(
    python_sort_executable: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test an input file that does not exist is a usage error."""
    # A wide terminal keeps the long temporary path from wrapping the error text.
    monkeypatch.setenv("COLUMNS", "500")

    result = invoke_cli(
        "debug",
        "sorting",
        str(python_sort_executable),
        "--input-file",
        str(tmp_path / "missing.bin"),
    )

    assert_exits_with(result, 2)
    assert "--input-file" in result.stderr
    assert "does not exist" in result.stderr


def test_a_problem_that_cannot_read_its_inputs_says_so(
    python_sort_executable: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test an input file is refused when the problem does not implement reading inputs."""
    path = write_saved_input(tmp_path, [1])
    monkeypatch.setattr(SortingProblem, "deserialize_input", Problem.deserialize_input)

    result = invoke_cli(
        "debug", "sorting", str(python_sort_executable), "--input-file", str(path)
    )

    assert_exits_with(result, 2)
    assert (
        "--input-file cannot be used: The problem 'sorting' does not implement "
        "deserialize_input, so it cannot read an input file." in result.stderr
    )


def test_case_replays_a_generated_input_exactly(
    recording_sorter: tuple[Path, Path],
) -> None:
    """Test the case option runs the input that the identifier generates."""
    script, log = recording_sorter
    identifier = "generated:uniform:size=4:seed=2"

    result = invoke_cli("debug", "sorting", str(script), "--case", identifier)

    assert result.exit_code == 0, result.stderr
    assert "Output verified." in result.stdout
    assert read_logged_inputs(log) == [
        resolve_case(SortingProblem(), identifier).input_data
    ]


def test_a_fixture_is_replayed_exactly(recording_sorter: tuple[Path, Path]) -> None:
    """Test the fixture option runs the input of the fixture."""
    script, log = recording_sorter

    result = invoke_cli("debug", "sorting", str(script), "--fixture", "duplicates")

    assert result.exit_code == 0, result.stderr
    assert read_logged_inputs(log) == [[3, 1, 4, 1, 5, 9, 2, 6, 5, 3]]


def test_a_generated_input_draws_from_the_distribution_the_problem_prefers(
    recording_sorter: tuple[Path, Path],
) -> None:
    """Test debug generates a small-range input of the debug size by default."""
    script, log = recording_sorter

    result = invoke_cli("debug", "sorting", str(script), "--seed", "4")

    assert result.exit_code == 0, result.stderr
    (values,) = read_logged_inputs(log)
    assert len(values) == 16
    assert all(-10 <= value <= 10 for value in values)


def test_a_distribution_and_a_size_can_be_chosen(
    recording_sorter: tuple[Path, Path],
) -> None:
    """Test the distribution and size options choose the generated input."""
    script, log = recording_sorter

    result = invoke_cli(
        "debug",
        "sorting",
        str(script),
        *["--distribution", "uniform", "--size", "9"],
    )

    assert result.exit_code == 0, result.stderr
    (values,) = read_logged_inputs(log)
    assert len(values) == 9
    assert any(abs(value) > 1000 for value in values)


def test_an_unknown_distribution_is_a_usage_error(python_sort_executable: Path) -> None:
    """Test debug refuses a distribution the problem does not have."""
    result = invoke_cli(
        "debug", "sorting", str(python_sort_executable), "--distribution", "nope"
    )

    assert_exits_with(result, 2)
    assert "Unknown distribution 'nope'" in result.stderr


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--case", "fixture:nope"], "No fixture named 'nope'"),
        (["--fixture", "nope"], "No fixture named 'nope'"),
        (
            ["--fixture", "empty", "--case", "fixture:empty"],
            "cannot be used together",
        ),
    ],
)
def test_bad_options_are_usage_errors(
    python_sort_executable: Path, options: list[str], message: str
) -> None:
    """Test debug options that select no valid input are usage errors."""
    result = invoke_cli("debug", "sorting", str(python_sort_executable), *options)

    assert result.exit_code == 2
    assert message in result.stderr


def test_runs_a_configured_implementation_by_name(
    configure: Configure, python_sort_executable: Path
) -> None:
    """Test a configured implementation is run when it is named."""
    configure(build_configured_entry("configured-sorter", python_sort_executable))

    result = invoke_cli("debug", "sorting", "configured-sorter", "--size", "4")

    assert result.exit_code == 0, result.stdout
    assert "Output verified." in result.stdout


def test_needs_exactly_one_implementation(
    configure: Configure, python_sort_executable: Path
) -> None:
    """Test two configured implementations make debug a usage error that lists them."""
    configure(
        build_configured_entry("first", python_sort_executable),
        build_configured_entry("second", python_sort_executable),
    )

    result = invoke_cli("debug", "sorting")

    assert_exits_with(result, 2)
    assert "exactly one implementation" in result.stderr
    assert "'first', 'second'" in result.stderr


def test_a_positional_implementation_and_a_command_are_two_implementations(
    python_sort_executable: Path, plain_sort_script: Path
) -> None:
    """Test an implementation given both ways counts twice, so debug refuses to run."""
    result = invoke_cli(
        "debug",
        "sorting",
        str(python_sort_executable),
        "--command",
        build_python_command_text(plain_sort_script),
    )

    assert_exits_with(result, 2)
    assert "exactly one implementation, but 2 were selected" in result.stderr
    assert "'python_sort.py', 'plain sort'" in result.stderr
    assert result.stdout == ""


def test_a_fixture_name_selects_the_input(python_sort_executable: Path) -> None:
    """Test a fixture name chooses the input that debug runs."""
    result = invoke_cli(
        "debug", "sorting", str(python_sort_executable), "--fixture", "single"
    )

    assert result.exit_code == 0, result.stderr
    assert "Output verified." in result.stdout


def test_an_unknown_fixture_name_lists_the_available_fixtures(
    python_sort_executable: Path,
) -> None:
    """Test an unknown fixture name is a usage error that lists the fixtures."""
    result = invoke_cli(
        "debug", "sorting", str(python_sort_executable), "--fixture", "nope"
    )

    assert_exits_with(result, 2)
    assert result.stderr.startswith(
        "No fixture named 'nope'. Available fixtures: empty,"
    )
    assert "i32_extremes" in result.stderr


def test_an_implementation_without_a_trace_falls_back_to_the_input_output_view(
    c_qsort_executable: Path,
) -> None:
    """Test debug shows the input and output when the implementation writes no trace."""
    result = invoke_cli(
        "debug", "sorting", str(c_qsort_executable), "--size", "4", "--seed", "1"
    )

    assert result.exit_code == 0, result.stdout
    assert "did not produce a usable trace" in result.stderr
    assert "did not produce a usable trace" not in result.stdout


def test_malformed_trace_is_reported_then_falls_back(
    malformed_trace_executable: Path,
) -> None:
    """Test debug reports a malformed trace once and shows the input and output instead."""
    result = invoke_cli(
        "debug",
        "sorting",
        str(malformed_trace_executable),
        "--size",
        "4",
        "--seed",
        "1",
    )

    assert result.exit_code == 0, result.exception
    assert "Trace file is malformed" in result.stderr
    assert "did not produce a usable trace" in result.stderr
    assert result.stdout.count("Output verified.") == 1
