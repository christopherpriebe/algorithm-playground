"""Tests for the JSON benchmark report."""

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from helpers.fakes import (
    FakeRunners,
    TraceFailure,
    build_insertion_sort_trace,
    build_named_implementations,
    crash,
    drop_last_above_five,
    sort_correctly,
)

from algorithm_playground.core.benchmarking import (
    BenchmarkFailure,
    BenchmarkReport,
    BenchmarkSettings,
    FailureStage,
    ImplementationBenchmark,
    SizeMeasurement,
    run_benchmark,
)
from algorithm_playground.core.cases import CasePlan, resolve_case
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.report import (
    BENCHMARK_FORMAT_VERSION,
    TEST_FORMAT_VERSION,
    benchmark_report_to_json,
    correctness_report_to_json,
)
from algorithm_playground.core.saved_inputs import save_failing_inputs
from algorithm_playground.core.statistics import summarize
from algorithm_playground.core.testing import (
    ShrinkOptions,
    TestReport,
    TestRunOptions,
    run_tests,
)
from algorithm_playground.problems.sorting import SortingProblem

PLAN = CasePlan(random_case_count=1, maximum_size=12, generator_names=("uniform", "sorted"), seed=4)
GENERATED_CASE = "generated:uniform:size=12:seed=5"


def build_settings(
    *,
    seed: int = 0,
    sizes: tuple[int, ...] = (5,),
    repetitions: int = 1,
    timeout_seconds: float = 30.0,
    subtract_startup_time: bool = False,
    distributions: tuple[str, ...] = (),
    count_operations: bool = False,
) -> BenchmarkSettings:
    """Build benchmark settings that verify outputs and skip warmup runs."""
    return BenchmarkSettings(
        seed=seed,
        sizes=sizes,
        repetitions=repetitions,
        warmup=0,
        timeout_seconds=timeout_seconds,
        verify_outputs=True,
        subtract_startup_time=subtract_startup_time,
        distributions=distributions,
        count_operations=count_operations,
    )


def compute_quadratic_seconds(values: list[int]) -> float:
    """Compute a duration that grows with the square of the input length."""
    return 1e-7 * len(values) ** 2


def build_benchmark_json(
    settings: BenchmarkSettings, runners: FakeRunners, *names: str
) -> dict[str, Any]:
    """Benchmark implementations with the given names and return the report as parsed JSON."""
    report = run_benchmark(
        SortingProblem(),
        build_named_implementations(*names),
        settings,
        runner_factory=runners,
    )
    return json.loads(json.dumps(benchmark_report_to_json(report)))


SETTINGS = build_settings(seed=7, sizes=(5, 10), repetitions=2)


class TestBenchmarkReportToJson:
    @pytest.fixture(scope="class")
    def good_directory(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        """The working directory of the good implementation, holding its script."""
        directory = tmp_path_factory.mktemp("report")
        (directory / "good.py").write_text("#!/usr/bin/env python3\n")
        return directory

    @pytest.fixture(scope="class")
    def document(self, good_directory: Path) -> dict[str, Any]:
        """The report of a good and a crashing implementation; the commands are never run."""
        script = good_directory / "good.py"
        good = Implementation(name="good", command=(str(script),), working_directory=good_directory)
        broken = Implementation(name="broken", command=("./broken",))
        report = run_benchmark(
            SortingProblem(),
            [good, broken],
            SETTINGS,
            runner_factory=FakeRunners({"good": sort_correctly, "broken": crash}),
        )
        return benchmark_report_to_json(report)

    def test_is_json_serializable(self, document: dict[str, Any]) -> None:
        """Test the document survives a round trip through JSON text."""
        assert json.loads(json.dumps(document)) == document

    def test_top_level_keys(self, document: dict[str, Any]) -> None:
        """Test the document has exactly the documented top-level keys."""
        assert set(document) == {
            "report",
            "format_version",
            "problem",
            "settings",
            "implementations",
            "host",
            "metadata",
        }

    def test_identifies_the_report_kind_version_and_problem(self, document: dict[str, Any]) -> None:
        """Test the document names its kind, its format version and the problem."""
        assert document["report"] == "benchmark"
        assert document["format_version"] == BENCHMARK_FORMAT_VERSION == 6
        assert document["problem"] == "sorting"

    def test_settings_record_every_benchmark_parameter(self, document: dict[str, Any]) -> None:
        """Test the settings hold the parameters of the benchmark, with the default distribution."""
        assert document["settings"] == {
            "seed": 7,
            "sizes": [5, 10],
            "repetitions": 2,
            "warmup": 0,
            "timeout_seconds": 30.0,
            "verify_outputs": True,
            "subtract_startup_time": False,
            "distributions": ["uniform"],
            "count_operations": False,
        }

    def test_host_and_metadata_are_filled_in(self, document: dict[str, Any]) -> None:
        """Test the host system, the tool version and the generation time are recorded."""
        assert document["host"]["system"]
        assert document["metadata"]["algorithm_playground_version"]
        assert document["metadata"]["generated_at"]

    def test_successful_implementation_record_describes_its_configuration(
        self, document: dict[str, Any], good_directory: Path
    ) -> None:
        """Test a successful implementation is recorded with its command and no failures."""
        good = document["implementations"][0]
        script = good_directory / "good.py"

        assert good["name"] == "good"
        assert good["command"] == [str(script)]
        assert good["working_directory"] == str(good_directory)
        assert good["failures"] == []
        assert good["inherit_environment"] is False
        assert good["timeout_seconds"] is None

    def test_successful_implementation_record_lists_the_hashed_script(
        self, document: dict[str, Any], good_directory: Path
    ) -> None:
        """Test the files of an implementation hold the resolved script path and its SHA-256."""
        good = document["implementations"][0]
        script = good_directory / "good.py"

        assert good["files"] == [
            {
                "path": str(script.resolve()),
                "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            }
        ]

    def test_successful_implementation_record_has_startup_statistics(
        self, document: dict[str, Any]
    ) -> None:
        """Test the startup record holds the samples and their summary statistics."""
        good = document["implementations"][0]

        assert set(good["startup"]) == {
            "samples_seconds",
            "minimum_seconds",
            "median_seconds",
            "mean_seconds",
            "standard_deviation_seconds",
        }

    def test_successful_implementation_has_one_result_per_size(
        self, document: dict[str, Any]
    ) -> None:
        """Test each size has a result that names its distribution and generated case."""
        results = document["implementations"][0]["results"]

        assert [record["size"] for record in results] == [5, 10]
        assert [record["distribution"] for record in results] == ["uniform", "uniform"]
        assert [record["case_identifier"] for record in results] == [
            "generated:uniform:size=5:seed=7",
            "generated:uniform:size=10:seed=7",
        ]

    def test_successful_implementation_results_have_the_documented_keys_and_sorted_samples(
        self, document: dict[str, Any]
    ) -> None:
        """Test each result has the documented keys and lists its samples in ascending order."""
        results = document["implementations"][0]["results"]

        for record in results:
            assert set(record) == {
                "distribution",
                "size",
                "case_identifier",
                "operation_counts",
                "operation_issue",
                "samples_seconds",
                "raw_samples_seconds",
                "minimum_seconds",
                "median_seconds",
                "mean_seconds",
                "standard_deviation_seconds",
            }
            assert len(record["samples_seconds"]) == 2
            assert record["samples_seconds"] == sorted(record["samples_seconds"])

    def test_a_benchmark_without_operation_counting_has_no_counts_or_operation_growth(
        self, document: dict[str, Any]
    ) -> None:
        """Test results hold no operation counts and the operation growth is empty."""
        good = document["implementations"][0]

        assert all(record["operation_counts"] is None for record in good["results"])
        assert good["operation_growth"] == {"uniform": {}}

    def test_two_sizes_are_too_few_for_a_time_growth_estimate(
        self, document: dict[str, Any]
    ) -> None:
        """Test the time growth is null per distribution and there is no legacy growth key."""
        good = document["implementations"][0]

        assert good["time_growth"] == {"uniform": None}
        assert "growth" not in good

    def test_failed_implementation_record(self, document: dict[str, Any]) -> None:
        """Test a crashing implementation is recorded with a startup failure and no results."""
        broken = document["implementations"][1]

        (failure,) = broken["failures"]
        assert broken["name"] == "broken"
        assert failure["stage"] == "startup"
        assert (failure["distribution"], failure["size"]) == (None, None)
        assert "exited with code 3" in failure["message"]
        assert broken["startup"] is None
        assert broken["results"] == []
        assert broken["time_growth"] == {"uniform": None}
        assert broken["working_directory"] is None

    def test_a_failure_in_one_distribution_names_it(self) -> None:
        """Test a measurement failure records its stage, distribution, size and message."""
        implementation = Implementation(name="a", command=("./a",))
        failure = BenchmarkFailure(FailureStage.MEASUREMENT, "it broke", "sorted", 10)
        report = BenchmarkReport(
            problem_name="sorting",
            settings=SETTINGS,
            implementations=(ImplementationBenchmark(implementation, None, (), (failure,)),),
        )

        record = benchmark_report_to_json(report)["implementations"][0]

        assert record["failures"] == [
            {"stage": "measurement", "distribution": "sorted", "size": 10, "message": "it broke"}
        ]

    def test_the_effective_settings_of_an_implementation_are_recorded(self) -> None:
        """Test the environment policy and timeout of an implementation appear in its record."""
        implementation = Implementation(
            name="a", command=("./a",), inherit_environment=True, timeout_seconds=5.0
        )
        report = BenchmarkReport(
            "sorting", SETTINGS, (ImplementationBenchmark(implementation, None, ()),)
        )

        record = benchmark_report_to_json(report)["implementations"][0]

        assert (record["inherit_environment"], record["timeout_seconds"]) == (True, 5.0)

    def test_reported_samples_reflect_startup_subtraction(self) -> None:
        """Test the samples are the raw samples minus the mean startup time."""
        ticks = itertools.count(1)
        settings = build_settings(repetitions=2, subtract_startup_time=True)
        runners = FakeRunners(
            {"a": sort_correctly}, durations={"a": lambda values: next(ticks) / 100}
        )

        document = build_benchmark_json(settings, runners, "a")

        record = document["implementations"][0]
        startup_mean = record["startup"]["mean_seconds"]
        expected = sorted(raw - startup_mean for raw in record["results"][0]["raw_samples_seconds"])
        assert record["results"][0]["samples_seconds"] == pytest.approx(expected)

    def test_raw_samples_are_reported_in_run_order(self) -> None:
        """Test the raw samples keep the run order while the samples are sorted."""
        implementation = Implementation(name="a", command=("./a",))
        measurement = SizeMeasurement(
            distribution="uniform",
            size=5,
            case_identifier="generated:uniform:size=5:seed=7",
            raw_samples=(0.3, 0.1, 0.2),
            summary=summarize([0.3, 0.1, 0.2]),
        )
        report = BenchmarkReport(
            problem_name="sorting",
            settings=SETTINGS,
            implementations=(ImplementationBenchmark(implementation, None, (measurement,)),),
        )

        record = benchmark_report_to_json(report)["implementations"][0]["results"][0]

        assert record["raw_samples_seconds"] == [0.3, 0.1, 0.2]
        assert record["samples_seconds"] == [0.1, 0.2, 0.3]


class TestDistributionsInTheBenchmarkJson:
    @pytest.fixture(scope="class")
    def distributions_document(self) -> dict[str, Any]:
        """The report of a quadratic and a crashing implementation over two distributions."""
        settings = build_settings(
            seed=2, sizes=(100, 200, 400), distributions=("uniform", "sorted")
        )
        runners = FakeRunners(
            {"quadratic": sort_correctly, "broken": crash},
            durations={"quadratic": compute_quadratic_seconds},
        )
        return build_benchmark_json(settings, runners, "quadratic", "broken")

    def test_the_settings_list_the_distributions(
        self, distributions_document: dict[str, Any]
    ) -> None:
        """Test the settings name the measured distributions in order."""
        assert distributions_document["settings"]["distributions"] == ["uniform", "sorted"]

    def test_each_result_names_its_distribution_and_size(
        self, distributions_document: dict[str, Any]
    ) -> None:
        """Test results run through every size of one distribution before the next."""
        results = distributions_document["implementations"][0]["results"]

        assert [(record["distribution"], record["size"]) for record in results] == [
            ("uniform", 100),
            ("uniform", 200),
            ("uniform", 400),
            ("sorted", 100),
            ("sorted", 200),
            ("sorted", 400),
        ]

    def test_each_result_names_its_generated_case(
        self, distributions_document: dict[str, Any]
    ) -> None:
        """Test a result identifies the generated case and has no legacy case name."""
        results = distributions_document["implementations"][0]["results"]

        assert results[3]["case_identifier"] == "generated:sorted:size=100:seed=2"
        assert "case_name" not in results[0]

    def test_growth_is_reported_for_each_distribution(
        self, distributions_document: dict[str, Any]
    ) -> None:
        """Test the time growth has one entry per measured distribution."""
        growth = distributions_document["implementations"][0]["time_growth"]

        assert set(growth) == {"uniform", "sorted"}

    @pytest.mark.parametrize("distribution", ["uniform", "sorted"])
    def test_growth_has_an_exponent_and_a_class_per_distribution(
        self, distributions_document: dict[str, Any], distribution: str
    ) -> None:
        """Test the growth of a distribution holds the exponent, class and reliability."""
        growth = distributions_document["implementations"][0]["time_growth"][distribution]

        assert set(growth) == {"exponent", "class", "reliable"}
        assert growth["exponent"] == pytest.approx(2.0)
        assert growth["class"] == "n^2"

    def test_an_implementation_without_measurements_has_null_growth(
        self, distributions_document: dict[str, Any]
    ) -> None:
        """Test an implementation that failed has a null growth for every distribution."""
        broken = distributions_document["implementations"][1]

        assert broken["time_growth"] == {"uniform": None, "sorted": None}


class TestUnreliableGrowthInTheBenchmarkJson:
    def test_a_series_that_is_mostly_startup_says_so(self) -> None:
        """Test growth fitted to costs that barely change with the size is marked unreliable."""
        settings = build_settings(seed=1, sizes=(100, 200, 400))
        runners = FakeRunners(
            {"quick": sort_correctly},
            durations={"quick": lambda values: 0.01 + 1e-9 * len(values)},
        )

        document = build_benchmark_json(settings, runners, "quick")

        growth = document["implementations"][0]["time_growth"]["uniform"]
        assert growth["reliable"] is False
        assert growth["class"] is not None


class TestOperationCountsInTheBenchmarkJson:
    @pytest.fixture(scope="class")
    def operations_document(self) -> dict[str, Any]:
        """The report of an implementation with a trace and one without, counting operations."""
        settings = build_settings(
            seed=2, sizes=(8, 16, 32), distributions=("reversed",), count_operations=True
        )
        runners = FakeRunners(
            {"insertion": sort_correctly, "silent": sort_correctly},
            traces={"insertion": build_insertion_sort_trace},
        )
        return build_benchmark_json(settings, runners, "insertion", "silent")

    def test_the_settings_say_that_operations_were_counted(
        self, operations_document: dict[str, Any]
    ) -> None:
        """Test the settings record that operation counting was on."""
        assert operations_document["settings"]["count_operations"] is True

    def test_each_result_has_the_counts_of_its_trace(
        self, operations_document: dict[str, Any]
    ) -> None:
        """Test every result of a traced implementation holds the operation counts of its sort."""
        insertion = operations_document["implementations"][0]

        assert [record["operation_counts"] for record in insertion["results"]] == [
            {"compares": size * (size - 1) // 2, "swaps": size * (size - 1) // 2, "writes": 0}
            for size in (8, 16, 32)
        ]
        assert [record["operation_issue"] for record in insertion["results"]] == [None] * 3

    def test_an_implementation_without_a_trace_has_null_counts(
        self, operations_document: dict[str, Any]
    ) -> None:
        """Test every result of an implementation that writes no trace has null counts."""
        silent = operations_document["implementations"][1]

        assert [record["operation_counts"] for record in silent["results"]] == [None] * 3

    def test_growth_maps_each_distribution_to_the_growth_of_each_operation(
        self, operations_document: dict[str, Any]
    ) -> None:
        """Test the operation growth names every operation and fits compares to n squared."""
        growth = operations_document["implementations"][0]["operation_growth"]["reversed"]

        assert set(growth) == {"compares", "swaps", "writes"}
        assert growth["compares"]["exponent"] == pytest.approx(2.0, abs=0.2)
        assert growth["compares"]["class"] == "n^2"
        assert "reliable" not in growth["compares"]

    def test_an_operation_that_is_never_counted_has_null_growth(
        self, operations_document: dict[str, Any]
    ) -> None:
        """Test an operation whose count is always zero has no growth."""
        growth = operations_document["implementations"][0]["operation_growth"]["reversed"]

        assert growth["writes"] is None

    def test_an_implementation_without_a_trace_has_no_operation_growth(
        self, operations_document: dict[str, Any]
    ) -> None:
        """Test the operation growth of an implementation that writes no trace is empty."""
        silent = operations_document["implementations"][1]

        assert silent["operation_growth"] == {"reversed": {}}


class TestMalformedTraceInTheBenchmarkJson:
    def test_the_measurement_records_why_it_has_no_counts(self) -> None:
        """Test a trace that cannot be decoded leaves no counts and records the issue."""
        settings = build_settings(seed=2, sizes=(8,), count_operations=True)
        runners = FakeRunners(
            {"a": sort_correctly}, traces={"a": lambda values: TraceFailure("bad kind 7")}
        )

        document = build_benchmark_json(settings, runners, "a")

        (record,) = document["implementations"][0]["results"]
        assert record["operation_counts"] is None
        assert record["operation_issue"] == {"kind": "malformed trace", "message": "bad kind 7"}


class TestTestingReportToJson:
    @pytest.fixture(scope="class")
    def implementations(self, tmp_path_factory: pytest.TempPathFactory) -> list[Implementation]:
        """A good implementation with a script, a bad one and one that was never built."""
        directory = tmp_path_factory.mktemp("tested")
        script = directory / "good.py"
        script.write_text("#!/usr/bin/env python3\n")
        return [
            Implementation(
                name="good",
                command=(str(script),),
                working_directory=directory,
                timeout_seconds=9.0,
            ),
            Implementation(name="bad", command=("./bad",)),
            Implementation(name="unbuilt", command=("./unbuilt",)),
        ]

    @pytest.fixture(scope="class")
    def testing_document(self, implementations: list[Implementation]) -> dict[str, Any]:
        """The report of testing the good and bad implementations; the third failed to build."""
        problem = SortingProblem()
        cases = [
            resolve_case(problem, identifier) for identifier in ("fixture:single", GENERATED_CASE)
        ]
        report = run_tests(
            problem,
            implementations[:2],
            cases,
            options=TestRunOptions(
                timeout_seconds=7.0, shrinking=ShrinkOptions(time_budget_seconds=12.0)
            ),
            runner_factory=FakeRunners({"good": sort_correctly, "bad": drop_last_above_five}),
        )
        document = correctness_report_to_json(
            report,
            implementations=implementations,
            plan=PLAN,
            build_failures={"unbuilt": "make: error"},
        )
        return json.loads(json.dumps(document))

    @pytest.fixture
    def single_good_report(self) -> TestReport:
        """The report of the good implementation passing one fixture."""
        problem = SortingProblem()
        return run_tests(
            problem,
            build_named_implementations("good"),
            [resolve_case(problem, "fixture:single")],
            runner_factory=FakeRunners({"good": sort_correctly}),
        )

    def test_top_level_keys(self, testing_document: dict[str, Any]) -> None:
        """Test the document has exactly the documented top-level keys."""
        assert set(testing_document) == {
            "report",
            "format_version",
            "problem",
            "passed",
            "settings",
            "cases",
            "implementations",
            "host",
            "metadata",
        }

    def test_identifies_the_report_kind_version_and_problem(
        self, testing_document: dict[str, Any]
    ) -> None:
        """Test the document names its kind, its format version and the problem."""
        assert testing_document["report"] == "test"
        assert testing_document["format_version"] == TEST_FORMAT_VERSION == 2
        assert testing_document["problem"] == "sorting"

    def test_the_settings_record_the_plan_the_shrink_limits_and_the_timeout(
        self, testing_document: dict[str, Any]
    ) -> None:
        """Test the settings hold the case plan, the shrink limits and the run timeout."""
        assert testing_document["settings"] == {
            "cases": "planned",
            "seed": 4,
            "random_cases": 1,
            "maximum_size": 12,
            "distributions": ["uniform", "sorted"],
            "include_fixtures": True,
            "shrink": {
                "enabled": True,
                "maximum_shrunk_cases": 3,
                "maximum_runs": 200,
                "time_budget_seconds": 12.0,
            },
            "timeout_seconds": 7.0,
        }

    @pytest.fixture
    def explicit_settings(self, implementations: list[Implementation]) -> dict[str, Any]:
        """The settings of a report for one explicit fixture run without shrinking."""
        problem = SortingProblem()
        report = run_tests(
            problem,
            implementations[:1],
            [resolve_case(problem, "fixture:single")],
            options=TestRunOptions(shrinking=None),
            runner_factory=FakeRunners({"good": sort_correctly}),
        )
        return correctness_report_to_json(report, implementations=implementations[:1])["settings"]

    def test_explicit_cases_have_no_plan(self, explicit_settings: dict[str, Any]) -> None:
        """Test a run of explicit cases records the plan settings as null."""
        assert explicit_settings["cases"] == "explicit"
        assert [explicit_settings[key] for key in ("seed", "random_cases", "maximum_size")] == [
            None
        ] * 3
        assert explicit_settings["distributions"] is None
        assert explicit_settings["include_fixtures"] is None

    def test_disabled_shrinking_is_recorded(self, explicit_settings: dict[str, Any]) -> None:
        """Test a run without shrinking records the shrink setting as disabled."""
        assert explicit_settings["shrink"]["enabled"] is False

    def test_an_implementation_is_described_like_in_the_benchmark_report(
        self, testing_document: dict[str, Any], implementations: list[Implementation]
    ) -> None:
        """Test an implementation record holds its command, directory, hashed files and limits."""
        good = testing_document["implementations"][0]
        script = Path(implementations[0].command[0])

        assert good["command"] == [str(script)]
        assert good["working_directory"] == str(script.parent)
        assert good["files"] == [
            {
                "path": str(script.resolve()),
                "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            }
        ]
        assert (good["inherit_environment"], good["timeout_seconds"]) == (False, 9.0)

    def test_implementations_without_a_script_have_no_files(
        self, testing_document: dict[str, Any]
    ) -> None:
        """Test an implementation that runs a missing command lists its command and no files."""
        _, bad, unbuilt = testing_document["implementations"]

        assert bad["command"] == ["./bad"]
        assert bad["files"] == []
        assert unbuilt["command"] == ["./unbuilt"]

    def test_a_report_without_build_failures_has_passed(
        self, single_good_report: TestReport
    ) -> None:
        """Test a report in which every run passed and nothing failed to build has passed."""
        implementations = build_named_implementations("good")

        document = correctness_report_to_json(single_good_report, implementations=implementations)

        assert document["passed"] is True

    def test_a_build_failure_means_not_passed_even_when_every_run_passed(
        self, single_good_report: TestReport
    ) -> None:
        """Test an implementation that failed to build makes the report not passed."""
        implementations = build_named_implementations("good", "x")

        document = correctness_report_to_json(
            single_good_report, implementations=implementations, build_failures={"x": "boom"}
        )

        assert document["passed"] is False

    def test_an_implementation_that_cannot_run_is_listed_with_the_reason_and_no_outcomes(
        self, single_good_report: TestReport
    ) -> None:
        """Test an unrunnable implementation records why, and has no build failure or outcomes."""
        document = correctness_report_to_json(
            single_good_report,
            implementations=build_named_implementations("good", "missing"),
            unrunnable={"missing": "command not found: ./missing"},
        )

        good, missing = document["implementations"]
        assert (good["cannot_run"], good["build_failure"]) == (None, None)
        assert missing["cannot_run"] == "command not found: ./missing"
        assert missing["build_failure"] is None
        assert missing["outcomes"] == []

    def test_an_implementation_that_cannot_run_means_not_passed(
        self, single_good_report: TestReport
    ) -> None:
        """Test an implementation that cannot run makes the report not passed."""
        document = correctness_report_to_json(
            single_good_report,
            implementations=build_named_implementations("good", "missing"),
            unrunnable={"missing": "command not found: ./missing"},
        )

        assert document["passed"] is False

    def test_saved_inputs_are_recorded_on_the_failing_outcomes(
        self, tmp_path: Path, implementations: list[Implementation]
    ) -> None:
        """Test a failing outcome holds the paths of its saved input and its shrunk input."""
        problem = SortingProblem()
        report = run_tests(
            problem,
            implementations[:2],
            [resolve_case(problem, GENERATED_CASE)],
            runner_factory=FakeRunners({"good": sort_correctly, "bad": drop_last_above_five}),
        )
        saved = save_failing_inputs(problem, report, tmp_path / "failures")

        document = correctness_report_to_json(
            report, implementations=implementations[:2], saved_inputs=saved
        )

        (outcome,) = document["implementations"][1]["outcomes"]
        assert outcome["saved_input"] == str(saved.inputs[("bad", outcome["case"])])
        assert outcome["saved_shrunk_input"] == str(saved.shrunk_inputs[("bad", outcome["case"])])

    def test_a_passing_outcome_has_no_saved_input(
        self, tmp_path: Path, implementations: list[Implementation]
    ) -> None:
        """Test an outcome that passed has no saved input even when others were saved."""
        problem = SortingProblem()
        report = run_tests(
            problem,
            implementations[:2],
            [resolve_case(problem, GENERATED_CASE)],
            runner_factory=FakeRunners({"good": sort_correctly, "bad": drop_last_above_five}),
        )
        saved = save_failing_inputs(problem, report, tmp_path / "failures")

        document = correctness_report_to_json(
            report, implementations=implementations[:2], saved_inputs=saved
        )

        good = document["implementations"][0]
        assert good["outcomes"][0]["saved_input"] is None

    def test_cases_describe_their_origin(self, testing_document: dict[str, Any]) -> None:
        """Test each case names its kind, and a generated case its distribution, size and seed."""
        assert [case["kind"] for case in testing_document["cases"]] == ["fixture", "generated"]
        assert testing_document["cases"][1] == {
            "identifier": GENERATED_CASE,
            "kind": "generated",
            "distribution": "uniform",
            "size": 12,
            "seed": 5,
        }

    def test_implementations_have_summaries_in_run_order(
        self, testing_document: dict[str, Any]
    ) -> None:
        """Test each implementation summarizes how many cases passed, failed and errored."""
        good, bad, unbuilt = testing_document["implementations"]

        assert (good["name"], good["summary"]) == ("good", {"passed": 2, "failed": 0, "errors": 0})
        assert bad["summary"] == {"passed": 1, "failed": 1, "errors": 0}
        assert unbuilt["summary"] == {"passed": 0, "failed": 0, "errors": 0}

    def test_outcomes_follow_the_case_order(self, testing_document: dict[str, Any]) -> None:
        """Test the outcomes of an implementation are listed in the order of the cases."""
        bad = testing_document["implementations"][1]

        assert [outcome["case"] for outcome in bad["outcomes"]] == [
            "fixture:single",
            GENERATED_CASE,
        ]

    def test_a_build_failure_is_recorded_with_its_message_and_no_outcomes(
        self, testing_document: dict[str, Any]
    ) -> None:
        """Test an implementation that failed to build records the message and has no outcomes."""
        good, _, unbuilt = testing_document["implementations"]

        assert good["build_failure"] is None
        assert unbuilt["build_failure"] == "make: error"
        assert unbuilt["outcomes"] == []

    def test_a_passing_outcome_has_no_failure_detail(
        self, testing_document: dict[str, Any]
    ) -> None:
        """Test an outcome that passed has empty failure fields."""
        passing, _ = testing_document["implementations"][1]["outcomes"]

        assert passing == {
            "case": "fixture:single",
            "status": "passed",
            "category": "",
            "message": "",
            "failure": None,
            "saved_input": None,
            "saved_shrunk_input": None,
            "shrink_note": None,
            "shrunk": None,
        }

    def test_a_failing_outcome_carries_the_detail_of_the_failure(
        self, testing_document: dict[str, Any]
    ) -> None:
        """Test a failed outcome holds its status, category, message and the failing input."""
        _, failing = testing_document["implementations"][1]["outcomes"]

        assert failing["status"] == "failed"
        assert failing["category"] == "wrong length"
        assert failing["message"] == "Output length 11 does not match input length 12"
        assert set(failing["failure"]) == {"input", "expected", "actual"}

    def test_a_failing_outcome_carries_the_shrunk_input(
        self, testing_document: dict[str, Any]
    ) -> None:
        """Test a failed generated case holds the smallest input that still fails."""
        _, failing = testing_document["implementations"][1]["outcomes"]

        assert failing["shrunk"] == {
            "case": f"shrunk:{GENERATED_CASE}",
            "message": "Output length 5 does not match input length 6",
            "input": "[0, 0, 0, 0, 0, 0]",
            "expected": "[0, 0, 0, 0, 0, 0]",
            "actual": "[0, 0, 0, 0, 0]",
        }
