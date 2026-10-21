"""End-to-end CLI tests for comparing, configuring, and building implementations.

These tests keep the number of executable runs small: tiny sizes, one
repetition, no warmup, and the build tests use ``debug`` (one run) or a single
fixture rather than the whole fixture list. Tests that do not depend on the
number of fixtures restrict the problem to its first one.
"""

import json
import re
import shlex
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from helpers.executables import write_executable, write_sorter
from helpers.registration import register_other_problem
from helpers.support import (
    Configure,
    assert_exits_with,
    find_table_header,
    invoke_cli,
    parse_table_rows,
)
from typer.testing import Result

pytestmark = pytest.mark.integration


BENCHMARK_OPTIONS = ["--sizes", "4,8", "--repetitions", "1", "--warmup", "0"]
BUILD_MARKER = "open('built.marker', 'w').write('built')"
FAILING_BUILD = (
    sys.executable,
    "-c",
    "import sys; print('compile exploded', file=sys.stderr); sys.exit(1)",
)
BUILD_OUTPUT = "standard error:\ncompile exploded"
RATIO = re.compile(r"\((\d+\.\d+)x\)")

# How long the slow sorter waits per run. Under heavy parallel load a process can be delayed by
# several hundred milliseconds, so the gap must be far larger than that for the comparison
# between a real fast and a real slow process to be stable.
SLOW_SORTER_SECONDS = 1.0


class BenchmarkRun(NamedTuple):
    """The outcome of a benchmark command that also wrote a JSON report."""

    result: Result
    report: dict[str, Any]


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


def invoke_comparison(*arguments: str, sizes: str = "4,50") -> Result:
    """Benchmark the implementations with one repetition per size and no plot."""
    return invoke_cli(
        "benchmark",
        "sorting",
        *arguments,
        "--sizes",
        sizes,
        "--repetitions",
        "1",
        "--warmup",
        "0",
        "--no-plot",
    )


class TestTestCommand:
    @pytest.fixture(scope="class")
    def mixed_result(
        self, python_sort_executable: Path, unsorted_output_executable: Path
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

    def test_two_implementations_share_one_matrix(self, mixed_result: Result) -> None:
        """Test two implementations are compared in one matrix of passes and failures."""
        assert "python_sort.py" in mixed_result.stdout
        assert "unsorted_output.py" in mixed_result.stdout
        assert "PASS" in mixed_result.stdout
        assert "FAIL" in mixed_result.stdout

    def test_each_implementation_gets_a_summary_line(self, mixed_result: Result) -> None:
        """Test every implementation is summarized with the cases it passed."""
        assert "python_sort.py: 4/4 cases passed" in mixed_result.stdout
        assert "unsorted_output.py: 2/4 cases passed" in mixed_result.stdout

    def test_a_failing_implementation_makes_the_command_exit_with_one(
        self, mixed_result: Result
    ) -> None:
        """Test a failing case ends the command with exit code 1 and names the case."""
        assert_exits_with(mixed_result, 1)
        assert "FAIL unsorted_output.py on fixture:two_unsorted" in mixed_result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_an_error_prints_every_line_of_the_message(self, crashing_executable: Path) -> None:
        """Test an implementation that crashes has its whole error message printed."""
        result = invoke_cli("test", "sorting", str(crashing_executable))

        assert_exits_with(result, 1)
        assert "ERROR" in result.stdout
        assert "exited with code 3" in result.stdout
        assert "kaboom" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_configuration_without_positionals_runs_every_configured_implementation(
        self,
        configure: Configure,
        python_sort_executable: Path,
    ) -> None:
        """Test the implementations configured for the problem run when none is named."""
        register_other_problem("searching")
        configure(
            build_configured_entry("configured-sorter", python_sort_executable),
            build_configured_entry("other-problem", python_sort_executable, problem="searching"),
        )

        result = invoke_cli("test", "sorting")

        assert result.exit_code == 0, result.stdout
        assert "configured-sorter: 1/1 cases passed" in result.stdout
        assert "other-problem" not in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_command_runs_a_script_without_the_executable_bit(
        self, plain_sort_script: Path
    ) -> None:
        """Test a script without the executable bit runs through an interpreter command."""
        assert not plain_sort_script.stat().st_mode & 0o111

        result = invoke_cli(
            "test", "sorting", "--command", build_python_command_text(plain_sort_script)
        )

        assert result.exit_code == 0, result.stdout
        assert "plain sort: 1/1 cases passed" in result.stdout


class TestBenchmarkCommand:
    @pytest.fixture(scope="class")
    def plain_script(
        self, python_sort_executable: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> Path:
        """A copy of the reference sorter without the executable bit."""
        script = tmp_path_factory.mktemp("plain") / "plain sort.py"
        shutil.copyfile(python_sort_executable, script)
        return script

    @pytest.fixture(scope="class")
    def comparison(
        self,
        python_sort_executable: Path,
        plain_script: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> BenchmarkRun:
        """Benchmark the reference sorter against a copy of it, writing a JSON report."""
        json_path = tmp_path_factory.mktemp("comparison") / "report.json"
        result = invoke_cli(
            "benchmark",
            "sorting",
            str(python_sort_executable),
            "--command",
            build_python_command_text(plain_script),
            *BENCHMARK_OPTIONS,
            "--json",
            str(json_path),
        )
        return BenchmarkRun(result, json.loads(json_path.read_text()))

    @pytest.fixture(scope="class")
    def failing_run(
        self,
        python_sort_executable: Path,
        crashing_executable: Path,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> BenchmarkRun:
        """Benchmark a working sorter next to one that crashes, writing a JSON report."""
        json_path = tmp_path_factory.mktemp("failing") / "report.json"
        result = invoke_cli(
            "benchmark",
            "sorting",
            str(python_sort_executable),
            str(crashing_executable),
            *BENCHMARK_OPTIONS,
            "--no-plot",
            "--json",
            str(json_path),
        )
        return BenchmarkRun(result, json.loads(json_path.read_text()))

    def test_compared_implementations_show_ratios_and_the_startup_row(
        self, comparison: BenchmarkRun
    ) -> None:
        """Test the table of two implementations has a startup row and ratios to the first."""
        assert comparison.result.exit_code == 0, comparison.result.stdout
        assert "(1.00x)" in comparison.result.stdout
        assert "startup" in comparison.result.stdout

    def test_the_json_report_names_the_problem_the_settings_and_the_host(
        self, comparison: BenchmarkRun
    ) -> None:
        """Test the JSON report records the problem, the sizes, and the host."""
        report = comparison.report

        assert report["report"] == "benchmark"
        assert report["problem"] == "sorting"
        assert report["settings"]["sizes"] == [4, 8]
        assert report["host"]["system"]

    def test_the_json_report_describes_each_compared_implementation(
        self, comparison: BenchmarkRun, python_sort_executable: Path, plain_script: Path
    ) -> None:
        """Test the JSON report records the name, command, and files of each implementation."""
        first, second = comparison.report["implementations"]

        assert first["name"] == "python_sort.py"
        assert first["failures"] == []
        assert first["command"] == [str(python_sort_executable.resolve())]
        assert first["files"][0]["sha256"]
        assert second["name"] == "plain sort"
        assert second["command"] == [sys.executable, str(plain_script)]
        assert str(plain_script.resolve()) in {file["path"] for file in second["files"]}

    def test_the_json_report_holds_one_sample_per_run_of_each_implementation(
        self, comparison: BenchmarkRun
    ) -> None:
        """Test every implementation has one startup sample and one sample per size."""
        for implementation in comparison.report["implementations"]:
            assert len(implementation["startup"]["samples_seconds"]) == 1
            assert [record["size"] for record in implementation["results"]] == [4, 8]
            for record in implementation["results"]:
                assert len(record["samples_seconds"]) == 1
                assert len(record["raw_samples_seconds"]) == 1

    def test_a_failing_implementation_is_reported_while_the_others_finish(
        self, failing_run: BenchmarkRun
    ) -> None:
        """Test a crashing implementation is named in the output and the command exits with one."""
        assert_exits_with(failing_run.result, 1)
        assert "failed" in failing_run.result.stdout
        assert "crashing.py failed:" in failing_run.result.stdout
        assert "kaboom" in failing_run.result.stdout

    def test_the_json_report_records_the_failure_next_to_the_finished_results(
        self, failing_run: BenchmarkRun
    ) -> None:
        """Test the report keeps the results of the working implementation and the failure."""
        good, bad = failing_run.report["implementations"]

        assert good["failures"] == []
        assert len(good["results"]) == 2
        assert [failure["stage"] for failure in bad["failures"]] == ["startup"]
        assert "kaboom" in bad["failures"][0]["message"]
        assert bad["results"] == []

    def test_unknown_reference_exits_with_code_2_before_running(
        self, python_sort_executable: Path
    ) -> None:
        """Test an unknown reference is a usage error and nothing is benchmarked."""
        result = invoke_cli(
            "benchmark",
            "sorting",
            str(python_sort_executable),
            *BENCHMARK_OPTIONS,
            "--reference",
            "nope",
        )

        assert_exits_with(result, 2)
        assert "Unknown reference 'nope'" in result.stderr
        assert result.stdout == ""


class TestBenchmarkComparison:
    @pytest.fixture
    def sorters(self, tmp_path: Path) -> dict[str, Path]:
        """Sorters that are fast, slow, and fail for inputs of more than ten elements."""
        return {
            "fast": write_sorter(tmp_path / "fast.py"),
            "slow": write_sorter(tmp_path / "slow.py", sleep_seconds=SLOW_SORTER_SECONDS),
            "flaky": write_sorter(tmp_path / "flaky.py", fail_above=10),
        }

    def test_a_slower_implementation_is_reported_slower_than_the_reference(
        self, sorters: dict[str, Path]
    ) -> None:
        """Test a real sorter that waits is reported with a ratio above one to a quick one."""
        # The ratio arithmetic is tested with exact durations in
        # test_cli_benchmark_distributions.py; this checks the wiring with real processes. One
        # size keeps the slow sorter to two runs, and its wait dwarfs any scheduling delay.
        result = invoke_comparison(str(sorters["fast"]), str(sorters["slow"]), sizes="4")

        assert result.exit_code == 0, result.stdout
        assert "ratio to fast.py" in result.stdout
        header = find_table_header(result.stdout)
        assert header.index("fast.py") < header.index("slow.py")
        rows = parse_table_rows(result.stdout)
        assert [row[0] for row in rows] == ["startup", "4"]
        for row in rows:
            reference_ratio, slow_ratio = (float(value) for value in RATIO.findall(" ".join(row)))
            assert reference_ratio == 1.0
            assert slow_ratio > 1.0, row

    def test_a_failed_implementation_shows_failed_cells_only_where_it_did_not_finish(
        self, sorters: dict[str, Path]
    ) -> None:
        """Test an implementation that fails for large inputs is marked failed for those only."""
        result = invoke_comparison(str(sorters["fast"]), str(sorters["flaky"]))

        assert_exits_with(result, 1)
        startup, size_4, size_50 = parse_table_rows(result.stdout)
        assert [startup[0], size_4[0], size_50[0]] == ["startup", "4", "50"]
        assert "failed" not in startup[2]
        assert "failed" not in size_4[2]
        assert size_50[1] != "failed"
        assert size_50[2] == "failed"
        assert "flaky.py failed:" in result.stdout
        assert "Run failed for size 50" in result.stdout

    def test_a_failed_reference_leaves_the_other_cells_without_ratios(
        self, sorters: dict[str, Path]
    ) -> None:
        """Test no ratio is shown for a size at which the reference failed."""
        result = invoke_comparison(
            str(sorters["flaky"]), str(sorters["fast"]), "--reference", "flaky.py"
        )

        assert_exits_with(result, 1)
        startup, size_4, size_50 = parse_table_rows(result.stdout)
        assert RATIO.findall(" ".join(startup))[0] == "1.00"
        assert len(RATIO.findall(" ".join(size_4))) == 2
        assert size_50[1] == "failed"
        assert size_50[2] != "failed"
        assert "x)" not in size_50[2]


class TestDebugCommand:
    def test_runs_a_configured_implementation_by_name(
        self, configure: Configure, python_sort_executable: Path
    ) -> None:
        """Test a configured implementation is run when it is named."""
        configure(build_configured_entry("configured-sorter", python_sort_executable))

        result = invoke_cli("debug", "sorting", "configured-sorter", "--size", "4")

        assert result.exit_code == 0, result.stdout
        assert "Output verified." in result.stdout

    def test_needs_exactly_one_implementation(
        self, configure: Configure, python_sort_executable: Path
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
        self, python_sort_executable: Path, plain_sort_script: Path
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

    def test_a_fixture_name_selects_the_input(self, python_sort_executable: Path) -> None:
        """Test a fixture name chooses the input that debug runs."""
        result = invoke_cli("debug", "sorting", str(python_sort_executable), "--fixture", "single")

        assert result.exit_code == 0, result.stderr
        assert "Output verified." in result.stdout

    def test_an_unknown_fixture_name_lists_the_available_fixtures(
        self, python_sort_executable: Path
    ) -> None:
        """Test an unknown fixture name is a usage error that lists the fixtures."""
        result = invoke_cli("debug", "sorting", str(python_sort_executable), "--fixture", "nope")

        assert_exits_with(result, 2)
        assert result.stderr.startswith("No fixture named 'nope'. Available fixtures: empty,")
        assert "i32_extremes" in result.stderr


class TestInheritEnvironment:
    @pytest.fixture
    def recorder(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Callable[..., str]:
        """Run a script that records a marker variable through ``test``; return what it saw."""
        monkeypatch.setenv("PLAYGROUND_MARKER", "visible")
        seen = tmp_path / "seen"
        script = write_executable(
            tmp_path / "recorder.py",
            f"""\
            #!/usr/bin/env python3
            import os, shutil, sys
            with open({str(seen)!r}, "w") as log:
                log.write(os.environ.get("PLAYGROUND_MARKER", "absent"))
            shutil.copyfile(sys.argv[1], sys.argv[2])
            """,
        )

        def run(*options: str) -> str:
            result = invoke_cli("test", "sorting", str(script), *options)
            assert result.exit_code == 0, result.stderr
            return seen.read_text()

        return run

    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_environment_is_minimal_by_default(self, recorder: Callable[..., str]) -> None:
        """Test the variables of the caller are hidden from the implementation by default."""
        assert recorder() == "absent"

    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_flag_passes_the_caller_environment_through(
        self, recorder: Callable[..., str]
    ) -> None:
        """Test the inherit flag makes the variables of the caller visible."""
        assert recorder("--inherit-environment") == "visible"


class TestConfiguredEnvironmentAndTimeout:
    @pytest.fixture
    def seen(self, tmp_path: Path) -> Path:
        """A script that logs two variables of its environment and then sorts correctly."""
        log = tmp_path / "seen"
        write_executable(
            tmp_path / "recorder.py",
            f"""\
            #!/usr/bin/env python3
            import os, shutil, sys
            with open({str(log)!r}, "w") as stream:
                stream.write(os.environ.get("PYTHONPATH", "none") + "|")
                stream.write(os.environ.get("PLAYGROUND_MARKER", "absent"))
            shutil.copyfile(sys.argv[1], sys.argv[2])
            """,
        )
        return log

    @pytest.fixture
    def sleeper(self, tmp_path: Path) -> Path:
        """A correct sorter that waits half a second on every run."""
        return write_sorter(tmp_path / "sleeper.py", sleep_seconds=0.5)

    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_environment_table_reaches_the_run_with_the_configuration_directory_filled_in(
        self, configure: Configure, seen: Path, tmp_path: Path
    ) -> None:
        """Test the configured environment is set for the run, with its directory placeholder."""
        configure(
            build_configured_entry(
                "helper",
                tmp_path / "recorder.py",
                extra_lines=('environment = { PYTHONPATH = "{configuration_directory}/helpers" }',),
            )
        )

        result = invoke_cli("test", "sorting")

        assert result.exit_code == 0, result.stderr
        assert seen.read_text() == f"{tmp_path.resolve()}/helpers|absent"

    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_configured_environment_is_applied_on_top_of_the_inherited_environment(
        self,
        configure: Configure,
        seen: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test configured variables override inherited ones and the others stay visible."""
        monkeypatch.setenv("PLAYGROUND_MARKER", "inherited")
        monkeypatch.setenv("PYTHONPATH", "from-the-host")
        configure(
            build_configured_entry(
                "helper",
                tmp_path / "recorder.py",
                extra_lines=(
                    "inherit_environment = true",
                    'environment = { PYTHONPATH = "from-the-configuration" }',
                ),
            )
        )

        result = invoke_cli("test", "sorting")

        assert result.exit_code == 0, result.stderr
        assert seen.read_text() == "from-the-configuration|inherited"

    def test_the_configured_environment_reaches_the_build_command(
        self, configure: Configure, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test the build command sees the environment configured for its implementation."""
        marker = tmp_path / "build-saw"
        build = (
            sys.executable,
            "-c",
            f"import os; open({str(marker)!r}, 'w').write(os.environ['BUILD_VARIABLE'])",
        )
        configure(
            build_configured_entry(
                "built",
                python_sort_executable,
                build_command=build,
                extra_lines=('environment = { BUILD_VARIABLE = "visible" }',),
            )
        )

        result = invoke_cli("debug", "sorting", "--size", "3")

        assert result.exit_code == 0, result.stderr
        assert marker.read_text() == "visible"

    @pytest.mark.usefixtures("only_first_fixture")
    def test_a_timeout_of_the_implementation_ends_its_runs_early(
        self, configure: Configure, sleeper: Path
    ) -> None:
        """Test the timeout configured for an implementation stops a run that takes longer."""
        configure(
            build_configured_entry("sleeper", sleeper, extra_lines=("timeout_seconds = 0.2",))
        )

        result = invoke_cli("test", "sorting")

        assert_exits_with(result, 1)
        assert "timed out after 0.200s" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_a_configured_timeout_replaces_the_timeout_option_for_that_implementation_only(
        self,
        configure: Configure,
        sleeper: Path,
        tmp_path: Path,
    ) -> None:
        """Test the timeout option applies only to implementations without their own timeout."""
        quick = write_sorter(tmp_path / "quick.py")
        configure(
            build_configured_entry("patient", sleeper, extra_lines=("timeout_seconds = 30",))
            + build_configured_entry("impatient", quick),
        )

        result = invoke_cli("test", "sorting", "--timeout", "0.2")

        assert result.exit_code == 0, result.stdout
        assert "patient: 1/1 cases passed" in result.stdout
        assert "impatient: 1/1 cases passed" in result.stdout


class TestConfigurationInParentDirectories:
    @pytest.fixture
    def nested(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """A directory below the temporary directory that is the current directory."""
        directory = tmp_path / "solutions" / "sorting" / "c"
        directory.mkdir(parents=True)
        monkeypatch.chdir(directory)
        return directory

    @pytest.fixture
    def parent_configuration(
        self, tmp_path: Path, nested: Path, python_sort_executable: Path
    ) -> Path:
        """A configuration file in the temporary directory, above the current directory."""
        path = tmp_path / "algorithm-playground.toml"
        path.write_text(build_configured_entry("up-above", python_sort_executable))
        return path

    @pytest.mark.usefixtures("only_first_fixture", "parent_configuration")
    def test_a_configuration_above_the_current_directory_is_found(self) -> None:
        """Test a configuration file in a parent directory supplies the implementations."""
        result = invoke_cli("test", "sorting")

        assert result.exit_code == 0, result.stderr
        assert "up-above: 1/1 cases passed" in result.stdout

    @pytest.mark.usefixtures("parent_configuration")
    def test_list_shows_where_it_found_the_configuration(self) -> None:
        """Test list shows the implementations of a configuration found in a parent directory."""
        result = invoke_cli("list")

        assert result.exit_code == 0, result.stderr
        assert "up-above" in result.stdout
        assert "Configured implementations" in result.stdout

    @pytest.mark.usefixtures("parent_configuration")
    def test_the_search_stops_at_the_root_of_a_repository(self, tmp_path: Path) -> None:
        """Test a configuration above the root of a repository is not used."""
        (tmp_path / "solutions" / ".git").mkdir()

        result = invoke_cli("test", "sorting")

        assert_exits_with(result, 2)
        assert "No implementation was given for problem 'sorting'" in result.stderr

    @pytest.mark.usefixtures("only_first_fixture", "nested")
    def test_an_implementation_runs_in_the_directory_of_its_configuration_file(
        self, tmp_path: Path
    ) -> None:
        """Test the working directory of a run is the directory of the configuration file."""
        log = tmp_path / "where"
        write_executable(
            tmp_path / "where.py",
            f"""\
            #!/usr/bin/env python3
            import os, shutil, sys
            open({str(log)!r}, "w").write(os.getcwd())
            shutil.copyfile(sys.argv[1], sys.argv[2])
            """,
        )
        (tmp_path / "algorithm-playground.toml").write_text(
            build_configured_entry("where", tmp_path / "where.py")
        )

        result = invoke_cli("test", "sorting")

        assert result.exit_code == 0, result.stderr
        assert log.read_text() == str(tmp_path.resolve())


class TestBuildCommands:
    @pytest.fixture
    def built_sorter(self, configure: Configure, python_sort_executable: Path) -> Path:
        """Configure a sorter whose build command writes a marker file; return the marker."""
        path = configure(
            build_configured_entry(
                "built-sorter",
                python_sort_executable,
                build_command=(sys.executable, "-c", BUILD_MARKER),
            ),
        )
        return path.parent / "built.marker"

    def test_the_build_command_runs_in_the_configuration_directory_before_the_run(
        self, built_sorter: Path
    ) -> None:
        """Test the build command runs once, in the configuration directory, before the run."""
        result = invoke_cli("debug", "sorting", "--size", "4")

        assert result.exit_code == 0, result.stdout
        assert "Building built-sorter" in result.stderr
        assert built_sorter.read_text() == "built"

    def test_no_build_skips_the_build_command(self, built_sorter: Path) -> None:
        """Test the no-build option runs the implementation without building it."""
        result = invoke_cli("debug", "sorting", "--size", "4", "--no-build")

        assert result.exit_code == 0, result.stdout
        assert "Building" not in result.stderr
        assert not built_sorter.exists()

    def test_a_failing_build_exits_with_one_and_shows_its_output(
        self, configure: Configure, python_sort_executable: Path
    ) -> None:
        """Test a build that fails ends the command with exit code 1 and its output."""
        configure(
            build_configured_entry(
                "broken-build", python_sort_executable, build_command=FAILING_BUILD
            )
        )

        result = invoke_cli("debug", "sorting", "--size", "4")

        assert_exits_with(result, 1)
        assert "Building broken-build" in result.stderr
        assert result.stderr.count(BUILD_OUTPUT) == 1
        assert "No implementation could be built" in result.stderr
        assert "Output verified" not in result.stdout


class TestBuildFailureIsolation:
    @pytest.fixture
    def run_log(self, tmp_path: Path) -> Path:
        """The file in which the sorters log their runs."""
        return tmp_path / "runs.log"

    @pytest.fixture
    def mixed_builds(self, configure: Configure, tmp_path: Path, run_log: Path) -> None:
        """A sorter that builds and runs, and one whose build fails (and must never run)."""
        good = write_sorter(tmp_path / "good.py", log_path=run_log, label="good")
        bad = write_sorter(tmp_path / "bad.py", log_path=run_log, label="bad")
        configure(
            build_configured_entry("good", good),
            build_configured_entry("bad", bad, build_command=FAILING_BUILD),
        )

    @pytest.fixture
    def benchmark_run(self, mixed_builds: None, tmp_path: Path) -> BenchmarkRun:
        """Benchmark the mixed builds, writing a JSON report."""
        json_path = tmp_path / "report.json"
        result = invoke_cli(
            "benchmark",
            "sorting",
            *BENCHMARK_OPTIONS,
            "--no-plot",
            "--json",
            str(json_path),
        )
        return BenchmarkRun(result, json.loads(json_path.read_text()))

    @pytest.mark.usefixtures("mixed_builds", "only_first_fixture")
    def test_the_failed_build_is_marked_in_the_matrix_and_the_other_implementation_runs(
        self, run_log: Path
    ) -> None:
        """Test the matrix marks the failed build and the other implementation still runs."""
        result = invoke_cli("test", "sorting")

        assert_exits_with(result, 1)
        header = find_table_header(result.stdout)
        assert header.index("good") < header.index("bad")
        assert parse_table_rows(result.stdout) == [["fixtures", "1/1", "build failed"]]
        assert "good: 1/1 cases passed" in result.stdout
        assert "bad: build failed, not run" in result.stdout
        assert set(run_log.read_text().split()) == {"good"}

    @pytest.mark.usefixtures("mixed_builds", "only_first_fixture")
    def test_the_build_output_is_printed_once_on_standard_error(self) -> None:
        """Test the output of a failed build is printed once, on standard error only."""
        result = invoke_cli("test", "sorting")

        assert "Building bad" in result.stderr
        assert "Building good" not in result.stderr
        assert result.stderr.count(BUILD_OUTPUT) == 1
        assert BUILD_OUTPUT not in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_a_failed_build_does_not_stop_later_builds(
        self,
        configure: Configure,
        python_sort_executable: Path,
        tmp_path: Path,
    ) -> None:
        """Test the implementations after one whose build failed are still built and run."""
        configure(
            build_configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD),
            build_configured_entry(
                "good",
                python_sort_executable,
                build_command=(sys.executable, "-c", BUILD_MARKER),
            ),
        )

        result = invoke_cli("test", "sorting")

        assert result.exit_code == 1
        assert (tmp_path / "built.marker").read_text() == "built"
        assert "good: 1/1 cases passed" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_when_nothing_builds_nothing_runs(
        self, configure: Configure, python_sort_executable: Path
    ) -> None:
        """Test no case is run when no implementation could be built."""
        configure(
            build_configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD)
        )

        result = invoke_cli("test", "sorting")

        assert_exits_with(result, 1)
        assert result.stdout == ""
        assert result.stderr.count(BUILD_OUTPUT) == 1
        assert "No implementation could be built, so nothing was run." in result.stderr

    def test_benchmark_shows_the_failed_build_as_a_failed_implementation(
        self, benchmark_run: BenchmarkRun, run_log: Path
    ) -> None:
        """Test the benchmark table shows the failed build as failed and runs the other one."""
        result = benchmark_run.result

        assert_exits_with(result, 1)
        rows = parse_table_rows(result.stdout)
        assert [row[0] for row in rows] == ["startup", "4", "8"]
        assert all(row[2] == "failed" for row in rows)
        assert all("failed" not in row[1] and "skipped" not in row[1] for row in rows)
        assert result.stderr.count(BUILD_OUTPUT) == 1
        assert BUILD_OUTPUT not in result.stdout
        assert set(run_log.read_text().split()) == {"good"}

    def test_benchmark_records_the_failed_build_in_the_json_report(
        self, benchmark_run: BenchmarkRun
    ) -> None:
        """Test the JSON report has the results of the built sorter and the build failure."""
        good, bad = benchmark_run.report["implementations"]

        assert (good["name"], good["failures"]) == ("good", [])
        assert [record["size"] for record in good["results"]] == [4, 8]
        assert bad["name"] == "bad"
        assert [failure["stage"] for failure in bad["failures"]] == ["build"]
        assert "compile exploded" in bad["failures"][0]["message"]
        assert bad["startup"] is None
        assert bad["results"] == []

    def test_benchmark_runs_nothing_when_no_implementation_builds(
        self, configure: Configure, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test the benchmark runs and reports nothing when no implementation could be built."""
        configure(
            build_configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD)
        )
        json_path = tmp_path / "report.json"

        result = invoke_cli("benchmark", "sorting", *BENCHMARK_OPTIONS, "--json", str(json_path))

        assert_exits_with(result, 1)
        assert result.stdout == ""
        assert "No implementation could be built" in result.stderr
        assert not json_path.exists()

    def test_a_reference_whose_build_failed_leaves_the_other_cells_without_ratios(
        self,
        configure: Configure,
        python_sort_executable: Path,
    ) -> None:
        """Test no ratios are shown when the reference is an implementation that failed to build."""
        configure(
            build_configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD),
            build_configured_entry("good", python_sort_executable),
        )

        result = invoke_cli(
            "benchmark", "sorting", *BENCHMARK_OPTIONS, "--no-plot", "--reference", "bad"
        )

        assert result.exit_code == 1, result.stdout
        assert "ratio to bad" in result.stdout
        rows = parse_table_rows(result.stdout)
        assert all(row[1] == "failed" for row in rows)
        assert all("x)" not in row[2] for row in rows)

    def test_the_default_reference_is_the_first_implementation_that_is_ready(
        self,
        configure: Configure,
        python_sort_executable: Path,
    ) -> None:
        """Test ratios are taken to the first implementation that built when none is chosen."""
        configure(
            build_configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD),
            build_configured_entry("good", python_sort_executable),
            build_configured_entry("also-good", python_sort_executable),
        )

        result = invoke_cli("benchmark", "sorting", *BENCHMARK_OPTIONS, "--no-plot")

        assert result.exit_code == 1, result.stdout
        assert "ratio to good" in result.stdout
        assert "ratio to bad" not in result.stdout
        rows = parse_table_rows(result.stdout)
        assert any(RATIO.search(row[3]) for row in rows)


class TestUsageErrors:
    def test_unknown_implementation_name_exits_with_code_2(
        self, configure: Configure, python_sort_executable: Path
    ) -> None:
        """Test an implementation name that is neither configured nor a file is a usage error."""
        configure(build_configured_entry("configured-sorter", python_sort_executable))

        result = invoke_cli("test", "sorting", "no-such-implementation")

        assert_exits_with(result, 2)
        assert "no-such-implementation" in result.stderr
        assert "'configured-sorter'" in result.stderr
        assert result.stdout == ""

    def test_no_implementation_and_no_configuration_exits_with_code_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test running without any implementation or configuration says how to supply one."""
        monkeypatch.chdir(tmp_path)

        result = invoke_cli("test", "sorting")

        assert_exits_with(result, 2)
        assert "--command" in result.stderr
        assert "algorithm-playground.toml" in result.stderr

    def test_invalid_configuration_exits_with_code_2(
        self, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test a configuration entry without a command is a configuration error."""
        path = tmp_path / "invalid.toml"
        path.write_text('[[implementations]]\nname = "missing-command"\nproblem = "sorting"\n')

        result = invoke_cli(
            "test", "sorting", str(python_sort_executable), "--configuration", str(path)
        )

        assert_exits_with(result, 2)
        assert "Configuration error" in result.stderr
        assert "missing required key 'command'" in result.stderr

    def test_the_former_build_key_is_rejected_with_a_hint(self, tmp_path: Path) -> None:
        """Test the retired ``build`` key is rejected with a hint to use ``build_command``."""
        path = tmp_path / "former.toml"
        path.write_text(
            '[[implementations]]\nname = "former"\nproblem = "sorting"\n'
            'command = "./former"\nbuild = "make"\n'
        )

        result = invoke_cli("test", "sorting", "--configuration", str(path))

        assert result.exit_code == 2
        assert "unknown key(s): build." in result.stderr
        assert "build_command" in result.stderr
        assert "newer algorithm-playground" in result.stderr

    def test_missing_configuration_file_exits_with_code_2(
        self, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        """Test a configuration file that does not exist is a usage error."""
        result = invoke_cli(
            "test",
            "sorting",
            str(python_sort_executable),
            "--configuration",
            str(tmp_path / "missing.toml"),
        )

        assert_exits_with(result, 2)
        assert "configuration file not found" in result.stderr

    def test_a_configuration_path_inside_the_current_directory_is_shown_relative(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test an error about a configuration below the current directory shows a short path."""
        (tmp_path / "broken.toml").write_text("[[implementations\n")
        monkeypatch.chdir(tmp_path)

        result = invoke_cli("list", "--configuration", str(tmp_path / "broken.toml"))

        assert result.exit_code == 2
        assert result.stderr.startswith("Configuration error: broken.toml: invalid TOML")


class TestListCommand:
    def test_shows_configured_implementations_when_a_configuration_is_given(
        self, configure: Configure, python_sort_executable: Path
    ) -> None:
        """Test list shows the problems and the implementations of the given configuration."""
        path = configure(build_configured_entry("configured-sorter", python_sort_executable))

        result = invoke_cli("list", "--configuration", str(path))

        assert result.exit_code == 0, result.stdout
        assert "Registered problems" in result.stdout
        assert "Configured implementations" in result.stdout
        assert "configured-sorter" in result.stdout

    def test_omits_the_implementation_table_without_a_configuration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test list shows no implementation table when there is no configuration."""
        monkeypatch.chdir(tmp_path)

        result = invoke_cli("list")

        assert result.exit_code == 0, result.stdout
        assert "Configured implementations" not in result.stdout

    def test_a_configuration_without_implementations_is_a_warning_on_standard_error(
        self, configure: Configure
    ) -> None:
        """Test a configuration that configures nothing is reported as a warning."""
        configure("")

        result = invoke_cli("list")

        assert result.exit_code == 0
        assert "algorithm-playground.toml configures no implementations." in result.stderr
        assert "configures no implementations" not in result.stdout


class TestMarkupInUserText:
    """Names and paths are shown as typed; text that looks like Rich markup is not interpreted."""

    @pytest.fixture
    def odd_configuration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, python_sort_executable: Path
    ) -> Path:
        """A configuration in a directory named like markup, for an implementation named so."""
        directory = tmp_path / "[b]odd"
        directory.mkdir()
        path = directory / "algorithm-playground.toml"
        path.write_text(build_configured_entry("[red]odd[/red]", python_sort_executable))
        monkeypatch.chdir(tmp_path)
        return path

    @pytest.mark.usefixtures("wide_terminal")
    def test_list_shows_the_configuration_path_and_name_literally(
        self, odd_configuration: Path
    ) -> None:
        """Test list prints a configuration path and an implementation name as typed."""
        result = invoke_cli("list", "--configuration", str(odd_configuration))

        assert result.exit_code == 0, result.stderr
        assert "Configured implementations ([b]odd/algorithm-playground.toml)" in result.stdout
        assert "[red]odd[/red]" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture", "wide_terminal")
    def test_test_shows_the_name_literally_in_the_matrix_and_the_summary(
        self, odd_configuration: Path
    ) -> None:
        """Test the matrix header and the summary print an implementation name as typed."""
        result = invoke_cli("test", "sorting", "--configuration", str(odd_configuration))

        assert result.exit_code == 0, result.stderr
        assert "[red]odd[/red]" in find_table_header(result.stdout)
        assert "[red]odd[/red]: 1/1 cases passed" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_a_name_with_markup_is_shown_literally_when_its_build_fails(
        self, configure: Configure, python_sort_executable: Path
    ) -> None:
        """Test the build message prints an implementation name as typed."""
        configure(
            build_configured_entry(
                "[red]odd[/red]", python_sort_executable, build_command=FAILING_BUILD
            )
        )

        result = invoke_cli("test", "sorting")

        assert "Building [red]odd[/red]" in result.stderr
