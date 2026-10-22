"""Tests for the frames and the failure block that the debug command shows."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import Result

from algorithm_playground.core import Frame
from algorithm_playground.problems.sorting import SortingProblem, SortingTrace
from helpers.executables import INSTRUMENTED_INSERTION
from helpers.support import (
    assert_exits_with,
    invoke_cli,
)

pytestmark = pytest.mark.integration


def invoke_debug_on_instrumented_insertion() -> Result:
    """Run ``debug`` on the instrumented insertion sort with an input of five values."""
    return invoke_cli(
        "debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5"
    )


def test_a_failing_output_is_described_like_a_failure_of_test(
    unsorted_output_executable: Path,
) -> None:
    """Test an output that fails verification is described with input, expected and actual."""
    result = invoke_cli(
        "debug",
        "sorting",
        str(unsorted_output_executable),
        "--size",
        "6",
        "--seed",
        "3",
    )

    assert_exits_with(result, 1)
    lines = [line.strip() for line in result.stderr.splitlines()]
    assert lines[0].startswith("Output did not verify: Output is not sorted ascending")
    assert any(line.startswith("input: [") for line in lines)
    assert any(line.startswith("expected: [") for line in lines)
    assert any(line.startswith("actual: [") for line in lines)


def test_the_description_fits_the_terminal(
    unsorted_output_executable: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test the lines that describe a failure are shortened to the width of the terminal."""
    monkeypatch.setenv("COLUMNS", "60")

    result = invoke_cli(
        "debug",
        "sorting",
        str(unsorted_output_executable),
        "--distribution",
        "uniform",
        "--size",
        "30",
    )

    described = [
        line
        for line in result.stderr.splitlines()
        if line.strip().startswith(("input:", "actual:"))
    ]
    assert described
    assert all(len(line) <= 60 for line in described)
    assert "(30 values" in result.stderr


def test_a_run_that_verifies_prints_no_block(python_sort_executable: Path) -> None:
    """Test a run whose output verifies prints no failure description."""
    result = invoke_cli("debug", "sorting", str(python_sort_executable), "--size", "5")

    assert result.exit_code == 0
    assert "input:" not in result.stderr


def test_the_trace_hooks_receive_the_input_and_the_output_of_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the frames and warnings hooks are called, in that order, with the run's data."""
    seen: list[tuple[str, list[int], list[int]]] = []
    original_frames = SortingProblem.trace_frames
    original_warnings = SortingProblem.trace_warnings

    def frames(
        self: SortingProblem,
        input_data: list[int],
        output: list[int],
        trace: SortingTrace,
    ) -> Sequence[Frame]:
        seen.append(("trace_frames", input_data, output))
        return original_frames(self, input_data, output, trace)

    def warnings(
        self: SortingProblem,
        input_data: list[int],
        output: list[int],
        trace: SortingTrace,
    ) -> Sequence[str]:
        seen.append(("trace_warnings", input_data, output))
        return original_warnings(self, input_data, output, trace)

    monkeypatch.setattr(SortingProblem, "trace_frames", frames)
    monkeypatch.setattr(SortingProblem, "trace_warnings", warnings)

    result = invoke_cli(
        "debug",
        "sorting",
        "--command",
        INSTRUMENTED_INSERTION,
        "--size",
        "5",
        "--seed",
        "2",
    )

    assert result.exit_code == 0, result.stderr
    (_, input_data, output), (_, same_input, same_output) = seen
    assert sorted(input_data) == output == same_output
    assert input_data == same_input
    assert [name for name, *_ in seen] == ["trace_frames", "trace_warnings"]


def test_a_trace_without_frames_falls_back_to_the_input_and_output_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a trace that has no frames makes debug show the input and the output instead."""

    def no_frames(
        _self: SortingProblem,
        _input_data: Sequence[int],
        _output: Sequence[int],
        _trace: object,
    ) -> tuple[Frame, ...]:
        return ()

    monkeypatch.setattr(SortingProblem, "trace_frames", no_frames)

    result = invoke_debug_on_instrumented_insertion()

    assert result.exit_code == 0, result.stderr
    assert "The trace has no frames to step through" in result.stderr
    assert "Falling back to input/output visualization." in result.stderr
    assert "output (sorted)" in result.stdout


def test_a_trace_without_frames_and_a_problem_without_a_picture_just_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test debug only notes the missing frames when the problem has no input/output view."""
    monkeypatch.setattr(
        SortingProblem,
        "trace_frames",
        lambda _self, _input_data, _output, _trace: (),
    )
    monkeypatch.setattr(
        SortingProblem,
        "input_output_frame",
        lambda _self, _input_data, _output: None,
    )

    result = invoke_debug_on_instrumented_insertion()

    assert result.exit_code == 0, result.stderr
    assert "The trace has no frames" in result.stderr
    assert "Output verified." in result.stdout


def test_a_trace_with_frames_does_not_fall_back() -> None:
    """Test a trace that has frames is stepped through without the fallback view."""
    result = invoke_debug_on_instrumented_insertion()

    assert "no frames" not in result.stderr
    assert "output (sorted)" not in result.stdout
