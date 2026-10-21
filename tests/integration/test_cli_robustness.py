"""End-to-end CLI tests for input validation and failure handling.

Usage errors and failures that stop a command are read from ``result.stderr``;
results (tables, completed rows, kept-directory notes) from ``result.stdout``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support import Invoke, WriteSorter, assert_exits_with

from algorithm_playground.cli import benchmark_command, debug_command, test_command
from algorithm_playground.core import Frame, FrameSequence
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

INSTRUMENTED_SORT = Path(__file__).resolve().parent.parent / "instrumented_sort.py"
INSTRUMENTED_INSERTION = f"{sys.executable} {INSTRUMENTED_SORT} insertion"


class TestSizesOption:
    def test_duplicate_sizes_are_a_usage_error(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke(
            "benchmark", "sorting", str(python_sort_executable), "--sizes", "4,8,4", "--no-plot"
        )
        assert result.exit_code == 2
        assert "Sizes must be unique" in result.stderr
        assert "repeated: 4" in result.stderr

    def test_sizes_that_differ_only_in_notation_are_still_duplicates(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke(
            "benchmark", "sorting", str(python_sort_executable), "--sizes", "1_000,1000"
        )
        assert_exits_with(result, 2)
        assert "repeated: 1000" in result.stderr


class TestTimeoutOption:
    @pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
    @pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
    def test_non_finite_timeouts_are_usage_errors(
        self, invoke: Invoke, python_sort_executable: Path, command: str, value: str
    ) -> None:
        result = invoke(command, "sorting", str(python_sort_executable), "--timeout", value)
        assert_exits_with(result, 2)
        assert "--timeout" in result.stderr
        # Negative infinity already fails the minimum; the others are caught by the finite check.
        assert ("finite" in result.stderr) == (value != "-inf")

    def test_a_finite_timeout_is_accepted(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke(
            "debug", "sorting", str(python_sort_executable), "--size", "4", "--timeout", "30"
        )
        assert result.exit_code == 0, result.stderr


class TestSingleImplementationBenchmarkFailure:
    def test_completed_rows_are_printed_before_the_failure(
        self, invoke: Invoke, tmp_path: Path, write_sorter: WriteSorter
    ) -> None:
        flaky = write_sorter(tmp_path / "flaky.py", fail_above=10)
        result = invoke(
            "benchmark",
            "sorting",
            str(flaky),
            "--sizes",
            "4,50,60",
            "--repetitions",
            "1",
            "--warmup",
            "0",
            "--no-plot",
        )
        assert_exits_with(result, 1)
        output = result.stdout
        assert "startup" in output
        rows = [line for line in output.splitlines() if line.startswith("│")]
        assert len(rows) == 2, output
        assert rows[1].split("│")[1].strip() == "4"
        assert output.index("startup") < output.index("flaky.py failed:")
        assert "Run failed for size 50" in output

    def test_a_failure_during_startup_prints_only_the_failure(
        self, invoke: Invoke, crashing_executable: Path
    ) -> None:
        result = invoke(
            "benchmark", "sorting", str(crashing_executable), "--sizes", "4", "--no-plot"
        )
        assert result.exit_code == 1
        assert "benchmark — sorting" not in result.stdout
        assert "crashing.py failed:" in result.stdout


class TestKeepTemporaryFiles:
    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_kept_directory_is_shown_for_a_failing_case(
        self,
        invoke: Invoke,
        crashing_executable: Path,
        scratch_root: Path,
    ) -> None:
        result = invoke("test", "sorting", str(crashing_executable), "--keep-temporary-files")
        assert result.exit_code == 1
        assert "Temporary files were kept in " in result.stdout
        line = next(
            line for line in result.stdout.splitlines() if "Temporary files were kept in" in line
        )
        directory = Path(line.strip().removeprefix("Temporary files were kept in "))
        assert directory.parent == scratch_root
        assert (directory / "input.bin").is_file()

    @pytest.mark.usefixtures("only_first_fixture")
    def test_nothing_is_said_without_the_option(
        self, invoke: Invoke, crashing_executable: Path
    ) -> None:
        result = invoke("test", "sorting", str(crashing_executable))
        assert result.exit_code == 1
        assert "Temporary files" not in result.stdout


class TestDebugFailures:
    def test_an_output_that_fails_verification_exits_with_one_after_the_visualization(
        self, invoke: Invoke, unsorted_output_executable: Path
    ) -> None:
        result = invoke(
            "debug", "sorting", str(unsorted_output_executable), "--size", "6", "--seed", "3"
        )
        assert_exits_with(result, 1)
        assert "Output did not verify:" in result.stderr
        assert "Output verified." not in result.stdout
        assert "output (sorted)" in result.stdout

    def test_a_failed_run_is_a_runner_error_on_standard_error(
        self, invoke: Invoke, crashing_executable: Path
    ) -> None:
        result = invoke("debug", "sorting", str(crashing_executable))
        assert_exits_with(result, 1)
        assert "Runner error:" in result.stderr
        assert "kaboom" in result.stderr
        assert result.stdout == ""


class TestDebugHooksThatRaise:
    """A bug in a hook of the problem ends in a message that names the hook, not a traceback."""

    @staticmethod
    def break_hook(monkeypatch: pytest.MonkeyPatch, name: str, replacement: object) -> None:
        monkeypatch.setattr(SortingProblem, name, replacement)

    @pytest.mark.parametrize("hook", ["trace_frames", "trace_warnings"])
    def test_a_trace_hook_that_raises(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch, hook: str
    ) -> None:
        def explode(
            self: SortingProblem, input_data: object, output: object, trace: object
        ) -> None:
            raise RuntimeError(f"{hook} exploded")

        self.break_hook(monkeypatch, hook, explode)
        result = invoke("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")
        assert_exits_with(result, 1)
        assert f"The problem's {hook} hook raised RuntimeError: {hook} exploded." in result.stderr

    def test_the_input_output_frame_hook_that_raises(
        self,
        invoke: Invoke,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        write_sorter: WriteSorter,
    ) -> None:
        def explode(self: SortingProblem, input_data: object, output: object) -> None:
            raise RuntimeError("cannot draw")

        self.break_hook(monkeypatch, "input_output_frame", explode)
        result = invoke(
            "debug", "sorting", str(write_sorter(tmp_path / "silent.py")), "--size", "5"
        )
        assert_exits_with(result, 1)
        assert (
            "The problem's input_output_frame hook raised RuntimeError: cannot draw."
            in result.stderr
        )

    def test_a_frame_that_cannot_be_drawn_while_stepping(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def lazy_frames(
            self: SortingProblem, input_data: object, output: object, trace: object
        ) -> FrameSequence:
            def build(position: int) -> Frame:
                raise ValueError("bad frame")

            return FrameSequence(3, build)

        self.break_hook(monkeypatch, "trace_frames", lazy_frames)
        result = invoke("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")
        assert_exits_with(result, 1)
        assert "A frame of the trace could not be drawn" in result.stderr
        assert "ValueError: bad frame" in result.stderr

    def test_a_verify_hook_that_raises_still_shows_the_picture_and_exits_with_one(
        self,
        invoke: Invoke,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        write_sorter: WriteSorter,
    ) -> None:
        def explode(self: SortingProblem, input_data: object, output: object) -> None:
            raise RuntimeError("verifier exploded")

        self.break_hook(monkeypatch, "verify", explode)
        result = invoke(
            "debug", "sorting", str(write_sorter(tmp_path / "silent.py")), "--size", "5"
        )
        assert_exits_with(result, 1)
        assert "Output not checked:" in result.stderr
        assert "Verification raised RuntimeError: verifier exploded" in result.stderr
        assert "output (sorted)" in result.stdout


class TestInterrupt:
    def test_ctrl_c_in_the_stepper_exits_with_130(
        self, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def interrupt(*arguments: object, **keywords: object) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(debug_command, "step_through", interrupt)
        result = invoke("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")
        assert_exits_with(result, 130)
        assert "Interrupted." in result.stderr

    @pytest.mark.parametrize("command", ["test", "benchmark"])
    def test_ctrl_c_during_a_run_exits_with_130_like_everywhere_else(
        self,
        invoke: Invoke,
        monkeypatch: pytest.MonkeyPatch,
        python_sort_executable: Path,
        command: str,
    ) -> None:
        def interrupt(*arguments: object, **keywords: object) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(test_command, "run_tests", interrupt)
        monkeypatch.setattr(benchmark_command, "run_benchmark", interrupt)
        result = invoke(command, "sorting", str(python_sort_executable))
        assert_exits_with(result, 130)
        assert "Interrupted." in result.stderr
