"""CLI tests for a problem whose hooks misbehave, and for the usage errors around it.

A problem comes from outside the package, so a hook that raises must end a command with
a message that names the hook and the failure exit code, never with a traceback. The
problem is ``tests/misbehaving.py``; implementations are in-process fakes where the
command starts none.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fakes import FakeRunners
from misbehaving import distinct_count
from support import Invoke, TableRows, WriteExecutable, assert_exits_with
from typer.testing import Result

pytestmark = pytest.mark.integration

UseFakeRunners = Callable[..., FakeRunners]
RegisterFaultyProblem = Callable[[str], str]

FIXTURES_MESSAGE = "The problem's fixtures hook raised RuntimeError: fixtures exploded."
GENERATORS_MESSAGE = "The problem's generators hook raised RuntimeError: generators exploded."
GENERATOR_MESSAGE = "The problem's 'broken' generator hook raised RuntimeError: generator exploded."


def assert_hook_failure(result: Result, message: str) -> None:
    """Assert the command exited with code 1 and the message, without a traceback."""
    assert_exits_with(result, 1)
    output = f"{result.stdout}{result.stderr}"
    assert message in output
    assert "Traceback" not in output


class TestMissingProblemArgument:
    @pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
    def test_it_is_a_usage_error_not_an_unknown_problem(self, invoke: Invoke, command: str) -> None:
        result = invoke(command)
        assert_exits_with(result, 2)
        output = f"{result.stdout}{result.stderr}"
        assert "Missing argument 'PROBLEM'" in output
        assert "Unknown problem" not in output

    def test_options_without_the_problem_are_the_same_usage_error(self, invoke: Invoke) -> None:
        result = invoke("test", "--random-cases", "3")
        assert_exits_with(result, 2)
        assert "Missing argument 'PROBLEM'" in f"{result.stdout}{result.stderr}"


class TestTestCommandWithFailingHooks:
    @pytest.mark.parametrize(
        ("fault", "message", "arguments"),
        [
            ("fixtures", FIXTURES_MESSAGE, []),
            ("fixtures", FIXTURES_MESSAGE, ["--fixture", "one"]),
            ("fixtures", FIXTURES_MESSAGE, ["--case", "fixture:one"]),
            ("generators", GENERATORS_MESSAGE, []),
            ("generators", GENERATORS_MESSAGE, ["--no-fixtures"]),
            ("generators", GENERATORS_MESSAGE, ["--case", "generated:uniform:size=3:seed=1"]),
            ("generator", GENERATOR_MESSAGE, []),
            ("generator", GENERATOR_MESSAGE, ["--case", "generated:broken:size=3:seed=1"]),
        ],
    )
    def test_the_hook_is_named_and_the_exit_code_is_1(
        self,
        invoke: Invoke,
        use_fake_test_runners: UseFakeRunners,
        register_faulty_problem: RegisterFaultyProblem,
        fault: str,
        message: str,
        arguments: list[str],
    ) -> None:
        use_fake_test_runners({"impl": distinct_count})
        name = register_faulty_problem(fault)
        result = invoke("test", name, "--command", "impl", "--no-shrink", *arguments)
        assert_hook_failure(result, message)

    def test_a_generator_that_works_is_not_reported(
        self,
        invoke: Invoke,
        use_fake_test_runners: UseFakeRunners,
        register_faulty_problem: RegisterFaultyProblem,
    ) -> None:
        use_fake_test_runners({"impl": distinct_count})
        name = register_faulty_problem("generator")
        result = invoke("test", name, "--command", "impl", "--distribution", "uniform")
        assert result.exit_code == 0, result.stdout + result.stderr

    def test_a_verify_that_raises_is_an_error_outcome_not_a_crash(
        self,
        invoke: Invoke,
        use_fake_test_runners: UseFakeRunners,
        register_faulty_problem: RegisterFaultyProblem,
    ) -> None:
        use_fake_test_runners({"impl": distinct_count})
        name = register_faulty_problem("verify")
        result = invoke("test", name, "--command", "impl", "--fixture", "one")
        assert_exits_with(result, 1)
        assert "verify exploded" in result.stdout


class TestBenchmarkCommandWithFailingHooks:
    ARGUMENTS = ("--sizes", "3,6", "--repetitions", "1", "--warmup", "0", "--no-plot")

    def test_a_generators_hook_that_raises_ends_the_command_before_anything_runs(
        self,
        invoke: Invoke,
        use_fake_runners: UseFakeRunners,
        register_faulty_problem: RegisterFaultyProblem,
    ) -> None:
        runners = use_fake_runners({"impl": distinct_count})
        name = register_faulty_problem("generators")
        result = invoke("benchmark", name, "--command", "impl", *self.ARGUMENTS)
        assert_hook_failure(result, GENERATORS_MESSAGE)
        assert runners.calls == []

    def test_a_generator_that_raises_fails_its_distribution_for_every_implementation(
        self,
        invoke: Invoke,
        use_fake_runners: UseFakeRunners,
        register_faulty_problem: RegisterFaultyProblem,
        table_rows: TableRows,
        tmp_path: Path,
    ) -> None:
        use_fake_runners({"first": distinct_count, "second": distinct_count})
        name = register_faulty_problem("generator")
        json_path = tmp_path / "report.json"
        result = invoke(
            *["benchmark", name, "--command", "first", "--command", "second"],
            *["--distribution", "uniform", "--distribution", "broken"],
            *self.ARGUMENTS,
            *["--json", str(json_path)],
        )
        assert_exits_with(result, 1)
        message = "Could not generate the input of size 3 for the distribution 'broken'"
        assert result.stdout.count(message) == 1
        assert GENERATOR_MESSAGE in result.stdout
        assert "Traceback" not in result.stdout + result.stderr

        rows = table_rows(result.stdout)
        labels = [row[0] for row in rows]
        broken_rows = rows[labels.index("broken") + 1 :]
        assert [row[0] for row in broken_rows] == ["3", "6"]
        assert all(row[1:] == ["failed", "failed"] for row in broken_rows)
        uniform_rows = rows[labels.index("uniform") + 1 : labels.index("broken")]
        assert [row[0] for row in uniform_rows[:2]] == ["3", "6"]
        assert all("failed" not in cell for row in uniform_rows for cell in row)

        report = json.loads(json_path.read_text())
        assert report["format_version"] == 6
        for implementation in report["implementations"]:
            (failure,) = implementation["failures"]
            assert (failure["stage"], failure["distribution"], failure["size"]) == (
                "distribution",
                "broken",
                None,
            )
            assert GENERATOR_MESSAGE in failure["message"]
            assert [item["distribution"] for item in implementation["results"]] == [
                "uniform",
                "uniform",
            ]
            assert implementation["startup"] is not None

    def test_a_problem_without_a_trace_format_ignores_count_operations(
        self,
        invoke: Invoke,
        use_fake_runners: UseFakeRunners,
        register_faulty_problem: RegisterFaultyProblem,
        tmp_path: Path,
    ) -> None:
        runners = use_fake_runners({"impl": distinct_count})
        name = register_faulty_problem("")
        json_path = tmp_path / "report.json"
        result = invoke(
            *["benchmark", name, "--command", "impl", "--count-operations"],
            *self.ARGUMENTS,
            *["--json", str(json_path)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert "does not define operation counts" in result.stderr
        assert "no trace format" in result.stderr
        assert runners.traced_calls == []
        assert "No implementation reported operation counts" not in result.stdout
        assert "write the problem's trace format" not in result.stdout
        assert json.loads(json_path.read_text())["settings"]["count_operations"] is False


class TestDebugCommandWithoutATraceFormat:
    @pytest.fixture
    def logging_implementation(
        self, tmp_path: Path, write_executable: WriteExecutable
    ) -> tuple[Path, Path]:
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

    def test_no_trace_path_is_passed_and_the_message_says_there_is_no_format(
        self,
        invoke: Invoke,
        register_faulty_problem: RegisterFaultyProblem,
        logging_implementation: tuple[Path, Path],
    ) -> None:
        script, log = logging_implementation
        name = register_faulty_problem("")
        result = invoke("debug", name, str(script), "--size", "4")
        assert result.exit_code == 0, result.stdout + result.stderr
        assert log.read_text().split() == ["3"]
        assert "Output verified." in result.stdout
        assert f"The problem '{name}' has no trace format" in result.stderr
        assert "Showing the input and the output instead" in result.stderr
        assert "accept an optional third path" not in result.stderr
        assert "did not produce a usable trace file" not in result.stderr


class TestDebugCommandWithFailingHooks:
    @pytest.mark.parametrize(
        ("fault", "message", "arguments"),
        [
            ("fixtures", FIXTURES_MESSAGE, ["--fixture", "one"]),
            ("generators", GENERATORS_MESSAGE, []),
            ("generators", GENERATORS_MESSAGE, ["--distribution", "uniform"]),
            ("generator", GENERATOR_MESSAGE, ["--distribution", "broken"]),
            ("generator", GENERATOR_MESSAGE, ["--case", "generated:broken:size=3:seed=1"]),
        ],
    )
    def test_the_hook_is_named_and_the_exit_code_is_1(
        self,
        invoke: Invoke,
        register_faulty_problem: RegisterFaultyProblem,
        fault: str,
        message: str,
        arguments: list[str],
    ) -> None:
        name = register_faulty_problem(fault)
        result = invoke("debug", name, "--command", "never-started", *arguments)
        assert_hook_failure(result, message)
