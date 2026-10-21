"""End-to-end CLI tests for input validation and failure handling.

Usage errors and failures that stop a command are read from ``result.stderr``;
results (tables, completed rows, kept-directory notes) from ``result.stdout``.
"""

import sys
from pathlib import Path

import pytest
from helpers.executables import write_sorter
from helpers.support import assert_exits_with, invoke_cli

from algorithm_playground.cli import benchmark_command, debug_command, test_command
from algorithm_playground.core import Frame, FrameSequence
from algorithm_playground.problems.sorting import SortingProblem

pytestmark = pytest.mark.integration

INSTRUMENTED_SORT = Path(__file__).resolve().parent.parent / "helpers" / "instrumented_sort.py"
INSTRUMENTED_INSERTION = f"{sys.executable} {INSTRUMENTED_SORT} insertion"


def raise_keyboard_interrupt(*arguments: object, **keywords: object) -> None:
    """Raise the interrupt that Ctrl+C causes, whatever the arguments are."""
    raise KeyboardInterrupt


class TestSizesOption:
    def test_duplicate_sizes_are_a_usage_error(self, python_sort_executable: Path) -> None:
        """Test sizes that repeat are a usage error naming the repeated size."""
        result = invoke_cli(
            "benchmark", "sorting", str(python_sort_executable), "--sizes", "4,8,4", "--no-plot"
        )

        assert result.exit_code == 2
        assert "Sizes must be unique" in result.stderr
        assert "repeated: 4" in result.stderr

    def test_sizes_that_differ_only_in_notation_are_still_duplicates(
        self, python_sort_executable: Path
    ) -> None:
        """Test sizes that have the same value are duplicates however they are written."""
        result = invoke_cli(
            "benchmark", "sorting", str(python_sort_executable), "--sizes", "1_000,1000"
        )

        assert_exits_with(result, 2)
        assert "repeated: 1000" in result.stderr


class TestTimeoutOption:
    @pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
    @pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
    def test_non_finite_timeouts_are_usage_errors(
        self, python_sort_executable: Path, command: str, value: str
    ) -> None:
        """Test a timeout that is not a finite number is a usage error for every command."""
        result = invoke_cli(command, "sorting", str(python_sort_executable), "--timeout", value)

        assert_exits_with(result, 2)
        assert "--timeout" in result.stderr
        # Negative infinity already fails the minimum; the others are caught by the finite check.
        assert ("finite" in result.stderr) == (value != "-inf")

    def test_a_finite_timeout_is_accepted(self, python_sort_executable: Path) -> None:
        """Test a timeout that is a finite number is accepted."""
        result = invoke_cli(
            "debug", "sorting", str(python_sort_executable), "--size", "4", "--timeout", "30"
        )

        assert result.exit_code == 0, result.stderr


class TestSingleImplementationBenchmarkFailure:
    def test_completed_rows_are_printed_before_the_failure(self, tmp_path: Path) -> None:
        """Test the rows measured before a failure are printed and the failure comes after."""
        flaky = write_sorter(tmp_path / "flaky.py", fail_above=10)

        result = invoke_cli(
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
        self, crashing_executable: Path
    ) -> None:
        """Test an implementation that fails at startup gets no table, only the failure."""
        result = invoke_cli(
            "benchmark", "sorting", str(crashing_executable), "--sizes", "4", "--no-plot"
        )

        assert result.exit_code == 1
        assert "benchmark — sorting" not in result.stdout
        assert "crashing.py failed:" in result.stdout


class TestKeepTemporaryFiles:
    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_kept_directory_is_shown_for_a_failing_case(
        self,
        crashing_executable: Path,
        scratch_root: Path,
    ) -> None:
        """Test the option keeps the files of a failing case and says where they are."""
        result = invoke_cli("test", "sorting", str(crashing_executable), "--keep-temporary-files")

        assert result.exit_code == 1
        assert "Temporary files were kept in " in result.stdout
        line = next(
            line for line in result.stdout.splitlines() if "Temporary files were kept in" in line
        )
        directory = Path(line.strip().removeprefix("Temporary files were kept in "))
        assert directory.parent == scratch_root
        assert (directory / "input.bin").is_file()

    @pytest.mark.usefixtures("only_first_fixture")
    def test_nothing_is_said_without_the_option(self, crashing_executable: Path) -> None:
        """Test no temporary files are mentioned when the option is not given."""
        result = invoke_cli("test", "sorting", str(crashing_executable))

        assert result.exit_code == 1
        assert "Temporary files" not in result.stdout


class TestDebugFailures:
    def test_an_output_that_fails_verification_exits_with_one_after_the_visualization(
        self, unsorted_output_executable: Path
    ) -> None:
        """Test an output that does not verify is still shown and ends the command with one."""
        result = invoke_cli(
            "debug", "sorting", str(unsorted_output_executable), "--size", "6", "--seed", "3"
        )

        assert_exits_with(result, 1)
        assert "Output did not verify:" in result.stderr
        assert "Output verified." not in result.stdout
        assert "output (sorted)" in result.stdout

    def test_a_failed_run_is_a_runner_error_on_standard_error(
        self, crashing_executable: Path
    ) -> None:
        """Test an implementation that crashes is reported as a runner error and prints nothing."""
        result = invoke_cli("debug", "sorting", str(crashing_executable))

        assert_exits_with(result, 1)
        assert "Runner error:" in result.stderr
        assert "kaboom" in result.stderr
        assert result.stdout == ""


class TestDebugHooksThatRaise:
    """A bug in a hook of the problem ends in a message that names the hook, not a traceback."""

    @pytest.mark.parametrize("hook", ["trace_frames", "trace_warnings"])
    def test_a_trace_hook_that_raises(self, monkeypatch: pytest.MonkeyPatch, hook: str) -> None:
        """Test a trace hook that raises is reported by name and ends debug with exit code 1."""

        def explode(
            self: SortingProblem, input_data: object, output: object, trace: object
        ) -> None:
            raise RuntimeError(f"{hook} exploded")

        monkeypatch.setattr(SortingProblem, hook, explode)

        result = invoke_cli("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")

        assert_exits_with(result, 1)
        assert f"The problem's {hook} hook raised RuntimeError: {hook} exploded." in result.stderr

    def test_the_input_output_frame_hook_that_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Test an input/output view hook that raises is reported by name with exit code 1."""

        def explode(self: SortingProblem, input_data: object, output: object) -> None:
            raise RuntimeError("cannot draw")

        monkeypatch.setattr(SortingProblem, "input_output_frame", explode)

        result = invoke_cli(
            "debug", "sorting", str(write_sorter(tmp_path / "silent.py")), "--size", "5"
        )

        assert_exits_with(result, 1)
        assert (
            "The problem's input_output_frame hook raised RuntimeError: cannot draw."
            in result.stderr
        )

    def test_a_frame_that_cannot_be_drawn_while_stepping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test a frame that fails to build while stepping is reported without a traceback."""

        def lazy_frames(
            self: SortingProblem, input_data: object, output: object, trace: object
        ) -> FrameSequence:
            def build(position: int) -> Frame:
                raise ValueError("bad frame")

            return FrameSequence(3, build)

        monkeypatch.setattr(SortingProblem, "trace_frames", lazy_frames)

        result = invoke_cli("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")

        assert_exits_with(result, 1)
        assert "A frame of the trace could not be drawn" in result.stderr
        assert "ValueError: bad frame" in result.stderr

    def test_a_verify_hook_that_raises_still_shows_the_picture_and_exits_with_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Test a verify hook that raises is reported, the output is shown, and debug fails."""

        def explode(self: SortingProblem, input_data: object, output: object) -> None:
            raise RuntimeError("verifier exploded")

        monkeypatch.setattr(SortingProblem, "verify", explode)

        result = invoke_cli(
            "debug", "sorting", str(write_sorter(tmp_path / "silent.py")), "--size", "5"
        )

        assert_exits_with(result, 1)
        assert "Output not checked:" in result.stderr
        assert "Verification raised RuntimeError: verifier exploded" in result.stderr
        assert "output (sorted)" in result.stdout


class TestInterrupt:
    def test_ctrl_c_in_the_stepper_exits_with_130(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test an interrupt while stepping ends debug with exit code 130."""
        monkeypatch.setattr(debug_command, "step_through", raise_keyboard_interrupt)

        result = invoke_cli("debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5")

        assert_exits_with(result, 130)
        assert "Interrupted." in result.stderr

    @pytest.mark.parametrize("command", ["test", "benchmark"])
    def test_ctrl_c_during_a_run_exits_with_130_like_everywhere_else(
        self,
        monkeypatch: pytest.MonkeyPatch,
        python_sort_executable: Path,
        command: str,
    ) -> None:
        """Test an interrupt during a test or benchmark run ends the command with exit code 130."""
        monkeypatch.setattr(test_command, "run_tests", raise_keyboard_interrupt)
        monkeypatch.setattr(benchmark_command, "run_benchmark", raise_keyboard_interrupt)

        result = invoke_cli(command, "sorting", str(python_sort_executable))

        assert_exits_with(result, 130)
        assert "Interrupted." in result.stderr
