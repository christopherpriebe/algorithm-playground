"""End-to-end CLI tests for comparing, configuring, and building implementations.

These tests keep the number of executable runs small: tiny sizes, one
repetition, no warmup, and the build tests use ``debug`` (one run) or a single
fixture rather than the whole fixture list. Tests that do not depend on the
number of fixtures restrict the problem to its first one.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from support import Configure, Invoke, TableRows, WriteSorter, assert_exits_with
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


def toml_list(*items: str) -> str:
    return json.dumps(list(items))


def configured_entry(
    name: str,
    script: Path,
    *,
    build_command: tuple[str, ...] | None = None,
    problem: str = "sorting",
    extra_lines: tuple[str, ...] = (),
) -> str:
    lines = [
        "[[implementations]]",
        f"name = {json.dumps(name)}",
        f'problem = "{problem}"',
        f"command = {toml_list(sys.executable, str(script))}",
    ]
    if build_command is not None:
        lines.append(f"build_command = {toml_list(*build_command)}")
    lines.extend(extra_lines)
    return "\n".join(lines) + "\n"


def python_command_text(script: Path) -> str:
    return shlex.join([sys.executable, str(script)])


class TestTestCommand:
    def test_two_implementations_share_one_matrix_and_a_failure_exits_with_one(
        self,
        invoke: Invoke,
        python_sort_executable: Path,
        unsorted_output_executable: Path,
    ) -> None:
        result = invoke(
            "test",
            "sorting",
            str(python_sort_executable),
            str(unsorted_output_executable),
            *["--fixture", "empty", "--fixture", "already_sorted"],
            *["--fixture", "two_unsorted", "--fixture", "reverse_sorted"],
        )
        assert_exits_with(result, 1)
        assert "python_sort.py" in result.stdout
        assert "unsorted_output.py" in result.stdout
        assert "PASS" in result.stdout
        assert "FAIL" in result.stdout
        assert "python_sort.py: 4/4 cases passed" in result.stdout
        assert "unsorted_output.py: 2/4 cases passed" in result.stdout
        assert "FAIL unsorted_output.py on fixture:two_unsorted" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_an_error_prints_every_line_of_the_message(
        self, invoke: Invoke, crashing_executable: Path
    ) -> None:
        result = invoke("test", "sorting", str(crashing_executable))
        assert_exits_with(result, 1)
        assert "ERROR" in result.stdout
        assert "exited with code 3" in result.stdout
        assert "kaboom" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_configuration_without_positionals_runs_every_configured_implementation(
        self,
        invoke: Invoke,
        configure: Configure,
        python_sort_executable: Path,
        register_other_problem: Callable[[str], None],
    ) -> None:
        register_other_problem("searching")
        configure(
            configured_entry("configured-sorter", python_sort_executable),
            configured_entry("other-problem", python_sort_executable, problem="searching"),
        )
        result = invoke("test", "sorting")
        assert result.exit_code == 0, result.stdout
        assert "configured-sorter: 1/1 cases passed" in result.stdout
        assert "other-problem" not in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_command_runs_a_script_without_the_executable_bit(
        self, invoke: Invoke, plain_sort_script: Path
    ) -> None:
        assert not plain_sort_script.stat().st_mode & 0o111
        result = invoke("test", "sorting", "--command", python_command_text(plain_sort_script))
        assert result.exit_code == 0, result.stdout
        assert "plain sort: 1/1 cases passed" in result.stdout


class TestBenchmarkCommand:
    def test_compares_two_implementations_and_writes_the_json_report(
        self,
        invoke: Invoke,
        python_sort_executable: Path,
        plain_sort_script: Path,
        tmp_path: Path,
    ) -> None:
        json_path = tmp_path / "report.json"
        result = invoke(
            "benchmark",
            "sorting",
            str(python_sort_executable),
            "--command",
            python_command_text(plain_sort_script),
            *BENCHMARK_OPTIONS,
            "--json",
            str(json_path),
        )
        assert result.exit_code == 0, result.stdout
        assert "(1.00x)" in result.stdout
        assert "startup" in result.stdout

        report = json.loads(json_path.read_text())
        assert report["problem"] == "sorting"
        assert report["settings"]["sizes"] == [4, 8]
        first, second = report["implementations"]
        assert report["report"] == "benchmark"
        assert first["name"] == "python_sort.py"
        assert first["failures"] == []
        assert first["command"] == [str(python_sort_executable.resolve())]
        assert first["files"][0]["sha256"]
        assert second["name"] == "plain sort"
        assert second["command"] == [sys.executable, str(plain_sort_script)]
        assert str(plain_sort_script.resolve()) in {file["path"] for file in second["files"]}
        for implementation in (first, second):
            assert len(implementation["startup"]["samples_seconds"]) == 1
            assert [record["size"] for record in implementation["results"]] == [4, 8]
            for record in implementation["results"]:
                assert len(record["samples_seconds"]) == 1
                assert len(record["raw_samples_seconds"]) == 1
        assert report["host"]["system"]

    def test_a_failing_implementation_is_reported_while_the_others_finish(
        self,
        invoke: Invoke,
        python_sort_executable: Path,
        crashing_executable: Path,
        tmp_path: Path,
    ) -> None:
        json_path = tmp_path / "report.json"
        result = invoke(
            "benchmark",
            "sorting",
            str(python_sort_executable),
            str(crashing_executable),
            *BENCHMARK_OPTIONS,
            "--no-plot",
            "--json",
            str(json_path),
        )
        assert_exits_with(result, 1)
        assert "failed" in result.stdout
        assert "crashing.py failed:" in result.stdout
        assert "kaboom" in result.stdout
        report = json.loads(json_path.read_text())
        good, bad = report["implementations"]
        assert good["failures"] == []
        assert len(good["results"]) == 2
        assert [failure["stage"] for failure in bad["failures"]] == ["startup"]
        assert "kaboom" in bad["failures"][0]["message"]
        assert bad["results"] == []

    def test_unknown_reference_exits_with_code_2_before_running(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke(
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
    def sorters(self, tmp_path: Path, write_sorter: WriteSorter) -> dict[str, Path]:
        return {
            "fast": write_sorter(tmp_path / "fast.py"),
            "slow": write_sorter(tmp_path / "slow.py", sleep_seconds=0.1),
            "flaky": write_sorter(tmp_path / "flaky.py", fail_above=10),
        }

    @staticmethod
    def benchmark(invoke: Invoke, *arguments: str) -> Result:
        return invoke(
            "benchmark",
            "sorting",
            *arguments,
            "--sizes",
            "4,50",
            "--repetitions",
            "1",
            "--warmup",
            "0",
            "--no-plot",
        )

    def test_a_clearly_slower_implementation_has_a_ratio_above_one(
        self, invoke: Invoke, table_rows: TableRows, sorters: dict[str, Path]
    ) -> None:
        # The ratio arithmetic is tested with deterministic durations in
        # test_cli_benchmark_distributions.py; this only checks the real wiring.
        result = self.benchmark(invoke, str(sorters["fast"]), str(sorters["slow"]))
        assert result.exit_code == 0, result.stdout
        assert "ratio to fast.py" in result.stdout
        header = next(line for line in result.stdout.splitlines() if line.startswith("┃"))
        assert header.index("fast.py") < header.index("slow.py")
        for row in table_rows(result.stdout):
            reference_ratio, slow_ratio = (float(value) for value in RATIO.findall(" ".join(row)))
            assert reference_ratio == 1.0
            assert slow_ratio > 1.0, row

    def test_a_failed_implementation_shows_failed_cells_only_where_it_did_not_finish(
        self, invoke: Invoke, table_rows: TableRows, sorters: dict[str, Path]
    ) -> None:
        result = self.benchmark(invoke, str(sorters["fast"]), str(sorters["flaky"]))
        assert_exits_with(result, 1)
        startup, size_4, size_50 = table_rows(result.stdout)
        assert [startup[0], size_4[0], size_50[0]] == ["startup", "4", "50"]
        assert "failed" not in startup[2]
        assert "failed" not in size_4[2]
        assert size_50[1] != "failed"
        assert size_50[2] == "failed"
        assert "flaky.py failed:" in result.stdout
        assert "Run failed for size 50" in result.stdout

    def test_a_failed_reference_leaves_the_other_cells_without_ratios(
        self, invoke: Invoke, table_rows: TableRows, sorters: dict[str, Path]
    ) -> None:
        result = self.benchmark(
            invoke, str(sorters["flaky"]), str(sorters["fast"]), "--reference", "flaky.py"
        )
        assert_exits_with(result, 1)
        startup, size_4, size_50 = table_rows(result.stdout)
        assert RATIO.findall(" ".join(startup))[0] == "1.00"
        assert len(RATIO.findall(" ".join(size_4))) == 2
        assert size_50[1] == "failed"
        assert size_50[2] != "failed"
        assert "x)" not in size_50[2]


class TestDebugCommand:
    def test_runs_a_configured_implementation_by_name(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path
    ) -> None:
        configure(configured_entry("configured-sorter", python_sort_executable))
        result = invoke("debug", "sorting", "configured-sorter", "--size", "4")
        assert result.exit_code == 0, result.stdout
        assert "Output verified." in result.stdout

    def test_needs_exactly_one_implementation(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path
    ) -> None:
        configure(
            configured_entry("first", python_sort_executable),
            configured_entry("second", python_sort_executable),
        )
        result = invoke("debug", "sorting")
        assert_exits_with(result, 2)
        assert "exactly one implementation" in result.stderr
        assert "'first', 'second'" in result.stderr

    def test_a_positional_implementation_and_a_command_are_two_implementations(
        self, invoke: Invoke, python_sort_executable: Path, plain_sort_script: Path
    ) -> None:
        result = invoke(
            "debug",
            "sorting",
            str(python_sort_executable),
            "--command",
            python_command_text(plain_sort_script),
        )
        assert_exits_with(result, 2)
        assert "exactly one implementation, but 2 were selected" in result.stderr
        assert "'python_sort.py', 'plain sort'" in result.stderr
        assert result.stdout == ""

    def test_a_fixture_name_selects_the_input(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke("debug", "sorting", str(python_sort_executable), "--fixture", "single")
        assert result.exit_code == 0, result.stderr
        assert "Output verified." in result.stdout

    def test_an_unknown_fixture_name_lists_the_available_fixtures(
        self, invoke: Invoke, python_sort_executable: Path
    ) -> None:
        result = invoke("debug", "sorting", str(python_sort_executable), "--fixture", "nope")
        assert_exits_with(result, 2)
        assert result.stderr.startswith("No fixture named 'nope'. Available fixtures: empty,")
        assert "i32_extremes" in result.stderr


class TestInheritEnvironment:
    @pytest.fixture
    def recorder(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        write_executable: Callable[[Path, str], Path],
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

        def run(invoke: Invoke, *options: str) -> str:
            result = invoke("test", "sorting", str(script), *options)
            assert result.exit_code == 0, result.stderr
            return seen.read_text()

        return run

    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_environment_is_minimal_by_default(
        self, invoke: Invoke, recorder: Callable[..., str]
    ) -> None:
        assert recorder(invoke) == "absent"

    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_flag_passes_the_caller_environment_through(
        self, invoke: Invoke, recorder: Callable[..., str]
    ) -> None:
        assert recorder(invoke, "--inherit-environment") == "visible"


class TestConfiguredEnvironmentAndTimeout:
    @pytest.fixture
    def seen(self, tmp_path: Path, write_executable: Callable[[Path, str], Path]) -> Path:
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

    @pytest.mark.usefixtures("only_first_fixture")
    def test_the_environment_table_reaches_the_run_with_the_configuration_directory_filled_in(
        self, invoke: Invoke, configure: Configure, seen: Path, tmp_path: Path
    ) -> None:
        configure(
            configured_entry(
                "helper",
                tmp_path / "recorder.py",
                extra_lines=('environment = { PYTHONPATH = "{configuration_directory}/helpers" }',),
            )
        )
        result = invoke("test", "sorting")
        assert result.exit_code == 0, result.stderr
        assert seen.read_text() == f"{tmp_path.resolve()}/helpers|absent"

    @pytest.mark.usefixtures("only_first_fixture")
    def test_it_is_applied_on_top_of_the_inherited_environment(
        self,
        invoke: Invoke,
        configure: Configure,
        seen: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PLAYGROUND_MARKER", "inherited")
        monkeypatch.setenv("PYTHONPATH", "from-the-host")
        configure(
            configured_entry(
                "helper",
                tmp_path / "recorder.py",
                extra_lines=(
                    "inherit_environment = true",
                    'environment = { PYTHONPATH = "from-the-configuration" }',
                ),
            )
        )
        result = invoke("test", "sorting")
        assert result.exit_code == 0, result.stderr
        assert seen.read_text() == "from-the-configuration|inherited"

    def test_a_build_command_sees_it_too(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        marker = tmp_path / "build-saw"
        build = (
            sys.executable,
            "-c",
            f"import os; open({str(marker)!r}, 'w').write(os.environ['BUILD_VARIABLE'])",
        )
        configure(
            configured_entry(
                "built",
                python_sort_executable,
                build_command=build,
                extra_lines=('environment = { BUILD_VARIABLE = "visible" }',),
            )
        )
        result = invoke("debug", "sorting", "--size", "3")
        assert result.exit_code == 0, result.stderr
        assert marker.read_text() == "visible"

    @pytest.fixture
    def sleeper(self, tmp_path: Path, write_sorter: WriteSorter) -> Path:
        return write_sorter(tmp_path / "sleeper.py", sleep_seconds=0.5)

    @pytest.mark.usefixtures("only_first_fixture")
    def test_a_timeout_of_the_implementation_ends_its_runs_early(
        self, invoke: Invoke, configure: Configure, sleeper: Path
    ) -> None:
        configure(configured_entry("sleeper", sleeper, extra_lines=("timeout_seconds = 0.2",)))
        result = invoke("test", "sorting")
        assert_exits_with(result, 1)
        assert "timed out after 0.200s" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_it_replaces_the_timeout_option_for_that_implementation_only(
        self,
        invoke: Invoke,
        configure: Configure,
        sleeper: Path,
        write_sorter: WriteSorter,
        tmp_path: Path,
    ) -> None:
        quick = write_sorter(tmp_path / "quick.py")
        configure(
            configured_entry("patient", sleeper, extra_lines=("timeout_seconds = 30",))
            + configured_entry("impatient", quick),
        )
        result = invoke("test", "sorting", "--timeout", "0.2")
        assert result.exit_code == 0, result.stdout
        assert "patient: 1/1 cases passed" in result.stdout
        assert "impatient: 1/1 cases passed" in result.stdout


class TestConfigurationInParentDirectories:
    @pytest.fixture
    def nested(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        directory = tmp_path / "solutions" / "sorting" / "c"
        directory.mkdir(parents=True)
        monkeypatch.chdir(directory)
        return directory

    @pytest.mark.usefixtures("only_first_fixture")
    def test_a_configuration_above_the_current_directory_is_found(
        self, invoke: Invoke, tmp_path: Path, nested: Path, python_sort_executable: Path
    ) -> None:
        (tmp_path / "algorithm-playground.toml").write_text(
            configured_entry("up-above", python_sort_executable)
        )
        result = invoke("test", "sorting")
        assert result.exit_code == 0, result.stderr
        assert "up-above: 1/1 cases passed" in result.stdout

    def test_list_shows_where_it_found_the_configuration(
        self, invoke: Invoke, tmp_path: Path, nested: Path, python_sort_executable: Path
    ) -> None:
        (tmp_path / "algorithm-playground.toml").write_text(
            configured_entry("up-above", python_sort_executable)
        )
        result = invoke("list")
        assert result.exit_code == 0, result.stderr
        assert "up-above" in result.stdout
        assert "Configured implementations" in result.stdout

    def test_the_search_stops_at_the_root_of_a_repository(
        self, invoke: Invoke, tmp_path: Path, nested: Path, python_sort_executable: Path
    ) -> None:
        (tmp_path / "algorithm-playground.toml").write_text(
            configured_entry("up-above", python_sort_executable)
        )
        (tmp_path / "solutions" / ".git").mkdir()
        result = invoke("test", "sorting")
        assert_exits_with(result, 2)
        assert "No implementation was given for problem 'sorting'" in result.stderr

    @pytest.mark.usefixtures("only_first_fixture")
    def test_an_implementation_runs_in_the_directory_of_its_configuration_file(
        self,
        invoke: Invoke,
        tmp_path: Path,
        nested: Path,
        write_executable: Callable[[Path, str], Path],
    ) -> None:
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
            configured_entry("where", tmp_path / "where.py")
        )
        result = invoke("test", "sorting")
        assert result.exit_code == 0, result.stderr
        assert log.read_text() == str(tmp_path.resolve())


class TestBuildCommands:
    def test_the_build_command_runs_in_the_configuration_directory_before_the_run(
        self,
        invoke: Invoke,
        configure: Configure,
        python_sort_executable: Path,
        tmp_path: Path,
    ) -> None:
        configure(
            configured_entry(
                "built-sorter",
                python_sort_executable,
                build_command=(sys.executable, "-c", BUILD_MARKER),
            ),
        )
        result = invoke("debug", "sorting", "--size", "4")
        assert result.exit_code == 0, result.stdout
        assert "Building built-sorter" in result.stderr
        assert (tmp_path / "built.marker").read_text() == "built"

    def test_no_build_skips_the_build_command(
        self,
        invoke: Invoke,
        configure: Configure,
        python_sort_executable: Path,
        tmp_path: Path,
    ) -> None:
        configure(
            configured_entry(
                "built-sorter",
                python_sort_executable,
                build_command=(sys.executable, "-c", BUILD_MARKER),
            ),
        )
        result = invoke("debug", "sorting", "--size", "4", "--no-build")
        assert result.exit_code == 0, result.stdout
        assert "Building" not in result.stderr
        assert not (tmp_path / "built.marker").exists()

    def test_a_failing_build_exits_with_one_and_shows_its_output(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path
    ) -> None:
        configure(
            configured_entry("broken-build", python_sort_executable, build_command=FAILING_BUILD)
        )
        result = invoke("debug", "sorting", "--size", "4")
        assert_exits_with(result, 1)
        assert "Building broken-build" in result.stderr
        assert result.stderr.count(BUILD_OUTPUT) == 1
        assert "No implementation could be built" in result.stderr
        assert "Output verified" not in result.stdout


class TestBuildFailureIsolation:
    @pytest.fixture
    def run_log(self, tmp_path: Path) -> Path:
        return tmp_path / "runs.log"

    @pytest.fixture
    def mixed(
        self, configure: Configure, tmp_path: Path, write_sorter: WriteSorter, run_log: Path
    ) -> None:
        """A sorter that builds and runs, and one whose build fails (and must never run)."""
        good = write_sorter(tmp_path / "good.py", log_path=run_log, label="good")
        bad = write_sorter(tmp_path / "bad.py", log_path=run_log, label="bad")
        configure(
            configured_entry("good", good),
            configured_entry("bad", bad, build_command=FAILING_BUILD),
        )

    @pytest.mark.usefixtures("mixed", "only_first_fixture")
    def test_the_failed_build_is_marked_in_the_matrix_and_the_other_implementation_runs(
        self, invoke: Invoke, table_rows: TableRows, run_log: Path
    ) -> None:
        result = invoke("test", "sorting")
        assert_exits_with(result, 1)
        header = next(line for line in result.stdout.splitlines() if line.startswith("┃"))
        assert header.index("good") < header.index("bad")
        assert table_rows(result.stdout) == [["fixtures", "1/1", "build failed"]]
        assert "good: 1/1 cases passed" in result.stdout
        assert "bad: build failed, not run" in result.stdout
        assert set(run_log.read_text().split()) == {"good"}

    @pytest.mark.usefixtures("mixed", "only_first_fixture")
    def test_the_build_output_is_printed_once_on_standard_error(self, invoke: Invoke) -> None:
        result = invoke("test", "sorting")
        assert "Building bad" in result.stderr
        assert "Building good" not in result.stderr
        assert result.stderr.count(BUILD_OUTPUT) == 1
        assert BUILD_OUTPUT not in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_a_failed_build_does_not_stop_later_builds(
        self,
        invoke: Invoke,
        configure: Configure,
        python_sort_executable: Path,
        tmp_path: Path,
    ) -> None:
        configure(
            configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD),
            configured_entry(
                "good",
                python_sort_executable,
                build_command=(sys.executable, "-c", BUILD_MARKER),
            ),
        )
        result = invoke("test", "sorting")
        assert result.exit_code == 1
        assert (tmp_path / "built.marker").read_text() == "built"
        assert "good: 1/1 cases passed" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_when_nothing_builds_nothing_runs(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path
    ) -> None:
        configure(configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD))
        result = invoke("test", "sorting")
        assert_exits_with(result, 1)
        assert result.stdout == ""
        assert result.stderr.count(BUILD_OUTPUT) == 1
        assert "No implementation could be built, so nothing was run." in result.stderr

    @pytest.mark.usefixtures("mixed")
    def test_benchmark_shows_the_failed_build_as_a_failed_implementation(
        self, invoke: Invoke, table_rows: TableRows, run_log: Path, tmp_path: Path
    ) -> None:
        json_path = tmp_path / "report.json"
        result = invoke(
            "benchmark",
            "sorting",
            *BENCHMARK_OPTIONS,
            "--no-plot",
            "--json",
            str(json_path),
        )
        assert_exits_with(result, 1)
        rows = table_rows(result.stdout)
        assert [row[0] for row in rows] == ["startup", "4", "8"]
        assert all(row[2] == "failed" for row in rows)
        assert all("failed" not in row[1] and "skipped" not in row[1] for row in rows)
        assert result.stderr.count(BUILD_OUTPUT) == 1
        assert BUILD_OUTPUT not in result.stdout
        assert set(run_log.read_text().split()) == {"good"}

        good, bad = json.loads(json_path.read_text())["implementations"]
        assert (good["name"], good["failures"]) == ("good", [])
        assert [record["size"] for record in good["results"]] == [4, 8]
        assert bad["name"] == "bad"
        assert [failure["stage"] for failure in bad["failures"]] == ["build"]
        assert "compile exploded" in bad["failures"][0]["message"]
        assert bad["startup"] is None
        assert bad["results"] == []

    def test_benchmark_runs_nothing_when_no_implementation_builds(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        configure(configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD))
        json_path = tmp_path / "report.json"
        result = invoke("benchmark", "sorting", *BENCHMARK_OPTIONS, "--json", str(json_path))
        assert_exits_with(result, 1)
        assert result.stdout == ""
        assert "No implementation could be built" in result.stderr
        assert not json_path.exists()

    def test_a_reference_whose_build_failed_leaves_the_other_cells_without_ratios(
        self,
        invoke: Invoke,
        configure: Configure,
        table_rows: TableRows,
        python_sort_executable: Path,
    ) -> None:
        configure(
            configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD),
            configured_entry("good", python_sort_executable),
        )
        result = invoke(
            "benchmark", "sorting", *BENCHMARK_OPTIONS, "--no-plot", "--reference", "bad"
        )
        assert result.exit_code == 1, result.stdout
        assert "ratio to bad" in result.stdout
        rows = table_rows(result.stdout)
        assert all(row[1] == "failed" for row in rows)
        assert all("x)" not in row[2] for row in rows)

    def test_the_default_reference_is_the_first_implementation_that_is_ready(
        self,
        invoke: Invoke,
        configure: Configure,
        table_rows: TableRows,
        python_sort_executable: Path,
    ) -> None:
        configure(
            configured_entry("bad", python_sort_executable, build_command=FAILING_BUILD),
            configured_entry("good", python_sort_executable),
            configured_entry("also-good", python_sort_executable),
        )
        result = invoke("benchmark", "sorting", *BENCHMARK_OPTIONS, "--no-plot")
        assert result.exit_code == 1, result.stdout
        assert "ratio to good" in result.stdout
        assert "ratio to bad" not in result.stdout
        rows = table_rows(result.stdout)
        assert any(RATIO.search(row[3]) for row in rows)


class TestUsageErrors:
    def test_unknown_implementation_name_exits_with_code_2(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path
    ) -> None:
        configure(configured_entry("configured-sorter", python_sort_executable))
        result = invoke("test", "sorting", "no-such-implementation")
        assert_exits_with(result, 2)
        assert "no-such-implementation" in result.stderr
        assert "'configured-sorter'" in result.stderr
        assert result.stdout == ""

    def test_no_implementation_and_no_configuration_exits_with_code_2(
        self, invoke: Invoke, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = invoke("test", "sorting")
        assert_exits_with(result, 2)
        assert "--command" in result.stderr
        assert "algorithm-playground.toml" in result.stderr

    def test_invalid_configuration_exits_with_code_2(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        path = tmp_path / "invalid.toml"
        path.write_text('[[implementations]]\nname = "missing-command"\nproblem = "sorting"\n')
        result = invoke(
            "test", "sorting", str(python_sort_executable), "--configuration", str(path)
        )
        assert_exits_with(result, 2)
        assert "Configuration error" in result.stderr
        assert "missing required key 'command'" in result.stderr

    def test_the_former_build_key_is_rejected_with_a_hint(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        path = tmp_path / "former.toml"
        path.write_text(
            '[[implementations]]\nname = "x"\nproblem = "sorting"\ncommand = "./x"\nbuild = "make"\n'
        )
        result = invoke("test", "sorting", "--configuration", str(path))
        assert result.exit_code == 2
        assert "unknown key(s): build." in result.stderr
        assert "build_command" in result.stderr
        assert "newer algorithm-playground" in result.stderr

    def test_missing_configuration_file_exits_with_code_2(
        self, invoke: Invoke, python_sort_executable: Path, tmp_path: Path
    ) -> None:
        result = invoke(
            "test",
            "sorting",
            str(python_sort_executable),
            "--configuration",
            str(tmp_path / "missing.toml"),
        )
        assert_exits_with(result, 2)
        assert "configuration file not found" in result.stderr

    def test_a_configuration_path_inside_the_current_directory_is_shown_relative(
        self, invoke: Invoke, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "broken.toml").write_text("[[implementations\n")
        monkeypatch.chdir(tmp_path)
        result = invoke("list", "--configuration", str(tmp_path / "broken.toml"))
        assert result.exit_code == 2
        assert result.stderr.startswith("Configuration error: broken.toml: invalid TOML")


class TestListCommand:
    def test_shows_configured_implementations_when_a_configuration_is_given(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path
    ) -> None:
        path = configure(configured_entry("configured-sorter", python_sort_executable))
        result = invoke("list", "--configuration", str(path))
        assert result.exit_code == 0, result.stdout
        assert "Registered problems" in result.stdout
        assert "Configured implementations" in result.stdout
        assert "configured-sorter" in result.stdout

    def test_omits_the_implementation_table_without_a_configuration(
        self, invoke: Invoke, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = invoke("list")
        assert result.exit_code == 0, result.stdout
        assert "Configured implementations" not in result.stdout

    def test_a_configuration_without_implementations_is_a_warning_on_standard_error(
        self, invoke: Invoke, configure: Configure
    ) -> None:
        configure("")
        result = invoke("list")
        assert result.exit_code == 0
        assert "algorithm-playground.toml configures no implementations." in result.stderr
        assert "configures no implementations" not in result.stdout


class TestMarkupInUserText:
    """Names and paths are shown as typed; text that looks like Rich markup is not interpreted."""

    @pytest.fixture(autouse=True)
    def wide_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("COLUMNS", "200")

    @pytest.fixture
    def odd_configuration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, python_sort_executable: Path
    ) -> Path:
        directory = tmp_path / "[b]odd"
        directory.mkdir()
        path = directory / "algorithm-playground.toml"
        path.write_text(configured_entry("[red]odd[/red]", python_sort_executable))
        monkeypatch.chdir(tmp_path)
        return path

    def test_list_shows_the_configuration_path_and_name_literally(
        self, invoke: Invoke, odd_configuration: Path
    ) -> None:
        result = invoke("list", "--configuration", str(odd_configuration))
        assert result.exit_code == 0, result.stderr
        assert "Configured implementations ([b]odd/algorithm-playground.toml)" in result.stdout
        assert "[red]odd[/red]" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_test_shows_the_name_literally_in_the_matrix_and_the_summary(
        self, invoke: Invoke, odd_configuration: Path
    ) -> None:
        result = invoke("test", "sorting", "--configuration", str(odd_configuration))
        assert result.exit_code == 0, result.stderr
        header = next(line for line in result.stdout.splitlines() if line.startswith("┃"))
        assert "[red]odd[/red]" in header
        assert "[red]odd[/red]: 1/1 cases passed" in result.stdout

    @pytest.mark.usefixtures("only_first_fixture")
    def test_a_name_with_markup_is_shown_literally_when_its_build_fails(
        self, invoke: Invoke, configure: Configure, python_sort_executable: Path
    ) -> None:
        configure(
            configured_entry("[red]odd[/red]", python_sort_executable, build_command=FAILING_BUILD)
        )
        result = invoke("test", "sorting")
        assert "Building [red]odd[/red]" in result.stderr
