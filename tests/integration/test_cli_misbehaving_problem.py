"""CLI tests for a problem whose hooks misbehave, and for the usage errors around it.

A problem comes from outside the package, so a hook that raises must end a command with
a message that names the hook and the failure exit code, never with a traceback. The
problem is ``tests/helpers/misbehaving.py``; implementations are in-process fakes where the
command starts none.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from helpers.executables import write_executable
from helpers.fakes import FakeRunners
from helpers.misbehaving import count_distinct_values
from helpers.registration import register_faulty_problem
from helpers.support import assert_exits_with, invoke_cli, parse_table_rows
from typer.testing import Result

pytestmark = pytest.mark.integration

UseFakeRunners = Callable[..., FakeRunners]

FIXTURES_MESSAGE = "The problem's fixtures hook raised RuntimeError: fixtures exploded."
GENERATORS_MESSAGE = "The problem's generators hook raised RuntimeError: generators exploded."
GENERATOR_MESSAGE = "The problem's 'broken' generator hook raised RuntimeError: generator exploded."


class BenchmarkRun(NamedTuple):
    """The outcome of a benchmark command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]
    runners: FakeRunners


def assert_hook_failure(result: Result, message: str) -> None:
    """Assert the command exited with code 1 and the message, without a traceback."""
    assert_exits_with(result, 1)
    output = f"{result.stdout}{result.stderr}"
    assert message in output
    assert "Traceback" not in output


class TestMissingProblemArgument:
    @pytest.mark.parametrize("command", ["test", "benchmark", "debug"])
    def test_it_is_a_usage_error_not_an_unknown_problem(self, command: str) -> None:
        """Test a command without the problem argument is a usage error naming the argument."""
        result = invoke_cli(command)

        assert_exits_with(result, 2)
        output = f"{result.stdout}{result.stderr}"
        assert "Missing argument 'PROBLEM'" in output
        assert "Unknown problem" not in output

    def test_options_without_the_problem_are_the_same_usage_error(self) -> None:
        """Test options given without the problem argument do not hide the missing argument."""
        result = invoke_cli("test", "--random-cases", "3")

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
        self,
        use_fake_test_runners: UseFakeRunners,
    ) -> None:
        """Test a working distribution passes even if another distribution of the problem raises."""
        use_fake_test_runners({"counter": count_distinct_values})
        name = register_faulty_problem("generator")

        result = invoke_cli("test", name, "--command", "counter", "--distribution", "uniform")

        assert result.exit_code == 0, result.stdout + result.stderr

    def test_a_verify_that_raises_is_an_error_outcome_not_a_crash(
        self,
        use_fake_test_runners: UseFakeRunners,
    ) -> None:
        """Test a verify hook that raises makes the case an error and the command exit with one."""
        use_fake_test_runners({"counter": count_distinct_values})
        name = register_faulty_problem("verify")

        result = invoke_cli("test", name, "--command", "counter", "--fixture", "one")

        assert_exits_with(result, 1)
        assert "verify exploded" in result.stdout


class TestBenchmarkCommandWithFailingHooks:
    ARGUMENTS = ("--sizes", "3,6", "--repetitions", "1", "--warmup", "0", "--no-plot")

    @pytest.fixture
    def broken_distribution_run(
        self, use_fake_runners: UseFakeRunners, tmp_path: Path
    ) -> BenchmarkRun:
        """Benchmark two implementations on a working and a broken distribution; write a report."""
        runners = use_fake_runners(
            {"first": count_distinct_values, "second": count_distinct_values}
        )
        name = register_faulty_problem("generator")
        json_path = tmp_path / "report.json"
        result = invoke_cli(
            *["benchmark", name, "--command", "first", "--command", "second"],
            *["--distribution", "uniform", "--distribution", "broken"],
            *self.ARGUMENTS,
            *["--json", str(json_path)],
        )
        return BenchmarkRun(result, json.loads(json_path.read_text()), runners)

    @pytest.fixture
    def untraced_run(self, use_fake_runners: UseFakeRunners, tmp_path: Path) -> BenchmarkRun:
        """Benchmark with operation counting a problem that has no trace format; write a report."""
        runners = use_fake_runners({"counter": count_distinct_values})
        name = register_faulty_problem("")
        json_path = tmp_path / "report.json"
        result = invoke_cli(
            *["benchmark", name, "--command", "counter", "--count-operations"],
            *self.ARGUMENTS,
            *["--json", str(json_path)],
        )
        return BenchmarkRun(result, json.loads(json_path.read_text()), runners)

    def test_a_generators_hook_that_raises_ends_the_command_before_anything_runs(
        self,
        use_fake_runners: UseFakeRunners,
    ) -> None:
        """Test a generators hook that raises stops the benchmark before any implementation runs."""
        runners = use_fake_runners({"counter": count_distinct_values})
        name = register_faulty_problem("generators")

        result = invoke_cli("benchmark", name, "--command", "counter", *self.ARGUMENTS)

        assert_hook_failure(result, GENERATORS_MESSAGE)
        assert runners.calls == []

    def test_a_generator_that_raises_is_reported_once_with_its_distribution(
        self, broken_distribution_run: BenchmarkRun
    ) -> None:
        """Test a generator that raises is explained once, without a traceback."""
        result = broken_distribution_run.result

        assert_exits_with(result, 1)
        message = "Could not generate the input of size 3 for the distribution 'broken'"
        assert result.stdout.count(message) == 1
        assert GENERATOR_MESSAGE in result.stdout
        assert "Traceback" not in result.stdout + result.stderr

    def test_a_generator_that_raises_fails_its_distribution_for_every_implementation(
        self, broken_distribution_run: BenchmarkRun
    ) -> None:
        """Test every size of the broken distribution is failed and the other one is not."""
        rows = parse_table_rows(broken_distribution_run.result.stdout)

        labels = [row[0] for row in rows]
        broken_rows = rows[labels.index("broken") + 1 :]
        assert [row[0] for row in broken_rows] == ["3", "6"]
        assert all(row[1:] == ["failed", "failed"] for row in broken_rows)
        uniform_rows = rows[labels.index("uniform") + 1 : labels.index("broken")]
        assert [row[0] for row in uniform_rows[:2]] == ["3", "6"]
        assert all("failed" not in cell for row in uniform_rows for cell in row)

    def test_a_generator_that_raises_is_recorded_as_a_distribution_failure_in_the_json_report(
        self, broken_distribution_run: BenchmarkRun
    ) -> None:
        """Test the report records the broken distribution as a failure of every implementation."""
        report = broken_distribution_run.report

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

    def test_a_problem_without_a_trace_format_says_so_when_asked_to_count_operations(
        self, untraced_run: BenchmarkRun
    ) -> None:
        """Test counting operations for a problem without a trace format is ignored with a notice."""
        result = untraced_run.result

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "does not define operation counts" in result.stderr
        assert "no trace format" in result.stderr

    def test_a_problem_without_a_trace_format_runs_no_traced_run(
        self, untraced_run: BenchmarkRun
    ) -> None:
        """Test no traced run is made and no operation table or hint is printed."""
        assert untraced_run.runners.traced_calls == []
        assert "No implementation reported operation counts" not in untraced_run.result.stdout
        assert "write the problem's trace format" not in untraced_run.result.stdout

    def test_a_problem_without_a_trace_format_records_that_nothing_was_counted(
        self, untraced_run: BenchmarkRun
    ) -> None:
        """Test the JSON report records operation counting as off."""
        assert untraced_run.report["settings"]["count_operations"] is False


class TestDebugCommandWithoutATraceFormat:
    @pytest.fixture
    def logging_implementation(self, tmp_path: Path) -> tuple[Path, Path]:
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
        self,
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
        self,
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
        fault: str,
        message: str,
        arguments: list[str],
    ) -> None:
        """Test a hook that raises ends the debug command with its name and exit code 1."""
        name = register_faulty_problem(fault)

        result = invoke_cli("debug", name, "--command", "never-started", *arguments)

        assert_hook_failure(result, message)
