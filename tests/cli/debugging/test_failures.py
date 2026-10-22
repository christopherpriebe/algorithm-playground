"""Tests for how the debug command handles hooks and runs that fail."""

from pathlib import Path

import pytest
from typer.testing import Result

from algorithm_playground.core import Frame, FrameSequence
from algorithm_playground.problems.sorting import SortingProblem
from helpers.executables import INSTRUMENTED_INSERTION, write_executable, write_sorter
from helpers.registration import register_faulty_problem
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


@pytest.mark.parametrize("hook", ["trace_frames", "trace_warnings"])
def test_a_trace_hook_result_that_cannot_be_used_names_the_hook(
    monkeypatch: pytest.MonkeyPatch, hook: str
) -> None:
    """Test a trace hook that returns nothing is reported by name, without a traceback."""
    monkeypatch.setattr(
        SortingProblem, hook, lambda _self, _input_data, _output, _trace: None
    )

    result = invoke_debug_on_instrumented_insertion()

    assert_exits_with(result, 1)
    assert f"The problem's {hook} hook raised TypeError" in result.stderr
    assert "Traceback" not in result.stderr


def test_a_view_that_is_not_a_frame_names_the_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test an input/output view that is not a frame is reported by name, without a traceback."""
    monkeypatch.setattr(
        SortingProblem,
        "trace_frames",
        lambda _self, _input_data, _output, _trace: (),
    )
    monkeypatch.setattr(
        SortingProblem,
        "input_output_frame",
        lambda _self, _input_data, _output: "not a frame",
    )

    result = invoke_debug_on_instrumented_insertion()

    assert_exits_with(result, 1)
    assert (
        "The problem's input_output_frame hook raised AttributeError" in result.stderr
    )
    assert "Traceback" not in result.stderr


@pytest.fixture
def logging_implementation(tmp_path: Path) -> tuple[Path, Path]:
    """A correct implementation that logs how many command-line arguments it received."""
    log = tmp_path / "argument_counts.log"
    script = write_executable(
        tmp_path / "distinct.py",
        f"""\
            #!/usr/bin/env python3
            import struct, sys
            with open({str(log)!r}, "a") as stream:
                stream.write(str(len(sys.argv)) + "\\n")
            raw = open(sys.argv[1], "rb").read()
            count = struct.unpack_from("<Q", raw)[0]
            values = struct.unpack_from(f"<{{count}}i", raw, 8)
            open(sys.argv[2], "wb").write(struct.pack("<Q", len(set(values))))
            """,
    )
    return script, log


def test_no_trace_path_is_passed_to_the_implementation(
    logging_implementation: tuple[Path, Path],
) -> None:
    """Test the implementation gets only the input and output paths, not a trace path."""
    script, log = logging_implementation
    name = register_faulty_problem("")

    result = invoke_cli("debug", name, str(script), "--size", "4")

    assert result.exit_code == 0, result.stdout + result.stderr
    assert log.read_text().split() == ["3"]
    assert "Output verified." in result.stdout


def test_the_message_says_there_is_no_format(
    logging_implementation: tuple[Path, Path],
) -> None:
    """Test debug says the problem has no trace format and shows the input and output."""
    script, _ = logging_implementation
    name = register_faulty_problem("")

    result = invoke_cli("debug", name, str(script), "--size", "4")

    assert f"The problem '{name}' has no trace format" in result.stderr
    assert "Showing the input and the output instead" in result.stderr
    assert "accept an optional third path" not in result.stderr
    assert "did not produce a usable trace file" not in result.stderr


@pytest.mark.parametrize(
    ("fault", "message", "arguments"),
    [
        ("fixtures", FIXTURES_MESSAGE, ["--fixture", "one"]),
        ("generators", GENERATORS_MESSAGE, []),
        ("generators", GENERATORS_MESSAGE, ["--distribution", "uniform"]),
        ("generator", GENERATOR_MESSAGE, ["--distribution", "broken"]),
        (
            "generator",
            GENERATOR_MESSAGE,
            ["--case", "generated:broken:size=3:seed=1"],
        ),
    ],
)
def test_the_hook_is_named_and_the_exit_code_is_1(
    fault: str,
    message: str,
    arguments: list[str],
) -> None:
    """Test a hook that raises ends the debug command with its name and exit code 1."""
    name = register_faulty_problem(fault)

    result = invoke_cli("debug", name, "--command", "never-started", *arguments)

    assert_hook_failure(result, message)


def test_an_output_that_fails_verification_exits_with_one_after_the_visualization(
    unsorted_output_executable: Path,
) -> None:
    """Test an output that does not verify is still shown and ends the command with one."""
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
    assert "Output did not verify:" in result.stderr
    assert "Output verified." not in result.stdout
    assert "output (sorted)" in result.stdout


def test_a_failed_run_is_a_runner_error_on_standard_error(
    crashing_executable: Path,
) -> None:
    """Test an implementation that crashes is reported as a runner error and prints nothing."""
    result = invoke_cli("debug", "sorting", str(crashing_executable))

    assert_exits_with(result, 1)
    assert "Runner error:" in result.stderr
    assert "kaboom" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("hook", ["trace_frames", "trace_warnings"])
def test_a_trace_hook_that_raises(monkeypatch: pytest.MonkeyPatch, hook: str) -> None:
    """Test a trace hook that raises is reported by name and ends debug with exit code 1."""

    def explode(
        _self: SortingProblem, _input_data: object, _output: object, _trace: object
    ) -> None:
        message = f"{hook} exploded"
        raise RuntimeError(message)

    monkeypatch.setattr(SortingProblem, hook, explode)

    result = invoke_cli(
        "debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5"
    )

    assert_exits_with(result, 1)
    assert (
        f"The problem's {hook} hook raised RuntimeError: {hook} exploded."
        in result.stderr
    )


def test_the_input_output_frame_hook_that_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test an input/output view hook that raises is reported by name with exit code 1."""

    def explode(_self: SortingProblem, _input_data: object, _output: object) -> None:
        message = "cannot draw"
        raise RuntimeError(message)

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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a frame that fails to build while stepping is reported without a traceback."""

    def lazy_frames(
        _self: SortingProblem, _input_data: object, _output: object, _trace: object
    ) -> FrameSequence:
        def build(_position: int) -> Frame:
            message = "bad frame"
            raise ValueError(message)

        return FrameSequence(3, build)

    monkeypatch.setattr(SortingProblem, "trace_frames", lazy_frames)

    result = invoke_cli(
        "debug", "sorting", "--command", INSTRUMENTED_INSERTION, "--size", "5"
    )

    assert_exits_with(result, 1)
    assert "A frame of the trace could not be drawn" in result.stderr
    assert "ValueError: bad frame" in result.stderr


def test_a_verify_hook_that_raises_still_shows_the_picture_and_exits_with_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test a verify hook that raises is reported, the output is shown, and debug fails."""

    def explode(_self: SortingProblem, _input_data: object, _output: object) -> None:
        message = "verifier exploded"
        raise RuntimeError(message)

    monkeypatch.setattr(SortingProblem, "verify", explode)

    result = invoke_cli(
        "debug", "sorting", str(write_sorter(tmp_path / "silent.py")), "--size", "5"
    )

    assert_exits_with(result, 1)
    assert "Output not checked:" in result.stderr
    assert "Verification raised RuntimeError: verifier exploded" in result.stderr
    assert "output (sorted)" in result.stdout
