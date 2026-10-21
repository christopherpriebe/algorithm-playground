"""CLI tests for what ``debug`` runs and how it reports: saved inputs, option rules, frames."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from support import Invoke, assert_exits_with, logged_inputs
from typer.testing import Result

from algorithm_playground.core import Frame
from algorithm_playground.core.problem import Problem
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

INSTRUMENTED_SORT = Path(__file__).resolve().parent.parent / "instrumented_sort.py"
INSTRUMENTED_INSERTION = f"{sys.executable} {INSTRUMENTED_SORT} insertion"


def saved_input(directory: Path, values: list[int]) -> Path:
    path = directory / "saved.bin"
    SortingProblem().serialize_input(values, path)
    return path


class TestInputFile:
    def test_the_input_in_the_file_is_the_input_that_runs(
        self, invoke: Invoke, recording_sorter: tuple[Path, Path], tmp_path: Path
    ) -> None:
        script, log = recording_sorter
        result = invoke(
            "debug", "sorting", str(script), "--input-file", str(saved_input(tmp_path, [5, 3, 9]))
        )
        assert result.exit_code == 0, result.stderr
        assert "Output verified." in result.stdout
        assert logged_inputs(log) == [[5, 3, 9]]

    def test_an_empty_input_can_be_run(
        self, invoke: Invoke, recording_sorter: tuple[Path, Path], tmp_path: Path
    ) -> None:
        script, log = recording_sorter
        result = invoke(
            "debug", "sorting", str(script), "--input-file", str(saved_input(tmp_path, []))
        )
        assert result.exit_code == 0, result.stderr
        assert logged_inputs(log) == [[]]

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
        self,
        invoke: Invoke,
        python_sort_executable: Path,
        tmp_path: Path,
        extra: list[str],
        named: str,
    ) -> None:
        result = invoke(
            "debug",
            "sorting",
            str(python_sort_executable),
            "--input-file",
            str(saved_input(tmp_path, [1])),
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
        self,
        invoke: Invoke,
        python_sort_executable: Path,
        selector: list[str],
        extra: list[str],
        named: str,
    ) -> None:
        result = invoke("debug", "sorting", str(python_sort_executable), *selector, *extra)
        assert_exits_with(result, 2)
        assert (
            f"{selector[0]} selects an exact input, so it cannot be combined with {named}"
            in result.stderr
        )

    def test_a_seed_of_zero_is_still_a_seed(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke(
            "debug", "sorting", str(python_sort_executable), "--fixture", "empty", "--seed", "0"
        )
        assert_exits_with(result, 2)
        assert "cannot be combined with --seed" in result.stderr

    def test_a_file_cannot_be_combined_with_a_fixture_or_a_case(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        path = saved_input(tmp_path, [1])
        result = invoke(
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
        self, invoke: Invoke, recording_sorter: tuple[Path, Path]
    ) -> None:
        script, log = recording_sorter
        invoke("debug", "sorting", str(script))
        invoke(
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
        first, second = logged_inputs(log)
        assert first == second and len(first) == 16

    def test_a_file_that_is_not_an_input_is_a_usage_error_naming_the_problem(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        path = tmp_path / "garbage.bin"
        path.write_bytes(b"\x07\x00")
        result = invoke("debug", "sorting", str(python_sort_executable), "--input-file", str(path))
        assert_exits_with(result, 2)
        assert (
            f"Could not read {path} as an input of problem 'sorting': BinaryFormatError"
            in result.stderr
        )

    def test_a_missing_file_is_a_usage_error(
        self,
        invoke: Invoke,
        python_sort_executable: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A wide terminal keeps the long temporary path from wrapping the error text.
        monkeypatch.setenv("COLUMNS", "500")
        result = invoke(
            "debug",
            "sorting",
            str(python_sort_executable),
            "--input-file",
            str(tmp_path / "missing.bin"),
        )
        assert_exits_with(result, 2)
        assert "--input-file" in result.stderr and "does not exist" in result.stderr

    def test_a_problem_that_cannot_read_its_inputs_says_so(
        self,
        invoke: Invoke,
        python_sort_executable: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = saved_input(tmp_path, [1])
        monkeypatch.setattr(SortingProblem, "deserialize_input", Problem.deserialize_input)
        result = invoke("debug", "sorting", str(python_sort_executable), "--input-file", str(path))
        assert_exits_with(result, 2)
        assert (
            "--input-file cannot be used: The problem 'sorting' does not implement "
            "deserialize_input, so it cannot read an input file." in result.stderr
        )


class TestFailureBlock:
    def test_a_failing_output_is_described_like_a_failure_of_test(
        self, invoke: Invoke, unsorted_output_executable: Path
    ) -> None:
        result = invoke(
            "debug", "sorting", str(unsorted_output_executable), "--size", "6", "--seed", "3"
        )
        assert_exits_with(result, 1)
        lines = [line.strip() for line in result.stderr.splitlines()]
        assert lines[0].startswith("Output did not verify: Output is not sorted ascending")
        assert any(line.startswith("input: [") for line in lines)
        assert any(line.startswith("expected: [") for line in lines)
        assert any(line.startswith("actual: [") for line in lines)

    def test_the_description_fits_the_terminal(
        self, invoke: Invoke, unsorted_output_executable: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("COLUMNS", "60")
        result = invoke(
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
        assert described and all(len(line) <= 60 for line in described)
        assert "(30 values" in result.stderr

    def test_a_run_that_verifies_prints_no_block(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke("debug", "sorting", str(python_sort_executable), "--size", "5")
        assert result.exit_code == 0
        assert "input:" not in result.stderr


class TestFrames:
    def test_the_trace_hooks_receive_the_input_and_the_output_of_the_run(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[tuple[str, list[int], list[int]]] = []
        original_frames = SortingProblem.trace_frames
        original_warnings = SortingProblem.trace_warnings

        def frames(self: SortingProblem, input_data: list[int], output: list[int], trace: object):
            seen.append(("trace_frames", input_data, output))
            return original_frames(self, input_data, output, trace)  # ty: ignore[invalid-argument-type]

        def warnings(self: SortingProblem, input_data: list[int], output: list[int], trace: object):
            seen.append(("trace_warnings", input_data, output))
            return original_warnings(self, input_data, output, trace)  # ty: ignore[invalid-argument-type]

        monkeypatch.setattr(SortingProblem, "trace_frames", frames)
        monkeypatch.setattr(SortingProblem, "trace_warnings", warnings)
        result = invoke(
            "debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5", "--seed", "2"
        )
        assert result.exit_code == 0, result.stderr
        (_, input_data, output), (_, same_input, same_output) = seen
        assert sorted(input_data) == output == same_output and input_data == same_input
        assert [name for name, *_ in seen] == ["trace_frames", "trace_warnings"]

    def test_a_trace_without_frames_falls_back_to_the_input_and_output_view(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_frames(
            self: SortingProblem, input_data: Sequence[int], output: Sequence[int], trace: object
        ) -> tuple[Frame, ...]:
            return ()

        monkeypatch.setattr(SortingProblem, "trace_frames", no_frames)
        result = invoke("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")
        assert result.exit_code == 0, result.stderr
        assert "The trace has no frames to step through" in result.stderr
        assert "Falling back to input/output visualization." in result.stderr
        assert "output (sorted)" in result.stdout

    def test_a_trace_without_frames_and_a_problem_without_a_picture_just_says_so(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            SortingProblem, "trace_frames", lambda self, input_data, output, trace: ()
        )
        monkeypatch.setattr(
            SortingProblem, "input_output_frame", lambda self, input_data, output: None
        )
        result = invoke("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")
        assert result.exit_code == 0, result.stderr
        assert "The trace has no frames" in result.stderr
        assert "Output verified." in result.stdout

    def test_a_trace_with_frames_does_not_fall_back(self, invoke: Invoke) -> None:
        result = invoke("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")
        assert "no frames" not in result.stderr
        assert "output (sorted)" not in result.stdout


class TestHookResultsThatCannotBeUsed:
    def debug(self, invoke: Invoke) -> Result:
        return invoke("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")

    def test_frames_that_are_not_a_sequence_name_the_hook(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            SortingProblem, "trace_frames", lambda self, input_data, output, trace: None
        )
        result = self.debug(invoke)
        assert_exits_with(result, 1)
        assert "The problem's trace_frames hook raised TypeError" in result.stderr
        assert "Traceback" not in result.stderr

    def test_warnings_that_cannot_be_listed_name_the_hook(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            SortingProblem, "trace_warnings", lambda self, input_data, output, trace: None
        )
        result = self.debug(invoke)
        assert_exits_with(result, 1)
        assert "The problem's trace_warnings hook raised TypeError" in result.stderr
        assert "Traceback" not in result.stderr

    def test_a_view_that_is_not_a_frame_names_the_hook(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            SortingProblem, "trace_frames", lambda self, input_data, output, trace: ()
        )
        monkeypatch.setattr(
            SortingProblem, "input_output_frame", lambda self, input_data, output: "not a frame"
        )
        result = self.debug(invoke)
        assert_exits_with(result, 1)
        assert "The problem's input_output_frame hook raised AttributeError" in result.stderr
        assert "Traceback" not in result.stderr
