"""Tests for the JSON benchmark report."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from fakes import (
    FakeRunners,
    TraceFailure,
    crash,
    drop_last_above_five,
    insertion_sort_trace,
    named,
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
from algorithm_playground.core.testing import run_tests
from algorithm_playground.problems.sorting import SortingProblem

SETTINGS = BenchmarkSettings(
    seed=7,
    sizes=(5, 10),
    repetitions=2,
    warmup=0,
    timeout_seconds=30.0,
    verify_outputs=True,
    subtract_startup_time=False,
)


@pytest.fixture(scope="module")
def good_directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("report")


@pytest.fixture(scope="module")
def document(good_directory: Path) -> dict[str, Any]:
    """The report of a good and a crashing implementation; the commands are never run."""
    script = good_directory / "good.py"
    script.write_text("#!/usr/bin/env python3\n")
    good = Implementation(name="good", command=(str(script),), working_directory=good_directory)
    broken = Implementation(name="broken", command=("./broken",))
    report = run_benchmark(
        SortingProblem(),
        [good, broken],
        SETTINGS,
        runner_factory=FakeRunners({"good": sort_correctly, "broken": crash}),
    )
    return benchmark_report_to_json(report)


class TestBenchmarkReportToJson:
    def test_is_json_serializable(self, document: dict[str, Any]) -> None:
        assert json.loads(json.dumps(document)) == document

    def test_top_level_shape(self, document: dict[str, Any]) -> None:
        assert set(document) == {
            "report",
            "format_version",
            "problem",
            "settings",
            "implementations",
            "host",
            "metadata",
        }
        assert document["report"] == "benchmark"
        assert document["format_version"] == BENCHMARK_FORMAT_VERSION == 6
        assert document["problem"] == "sorting"
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
        assert document["host"]["system"]
        assert document["metadata"]["algorithm_playground_version"]
        assert document["metadata"]["generated_at"]

    def test_successful_implementation_record(
        self, document: dict[str, Any], good_directory: Path
    ) -> None:
        good = document["implementations"][0]
        script = good_directory / "good.py"
        assert good["name"] == "good"
        assert good["command"] == [str(script)]
        assert good["working_directory"] == str(good_directory)
        assert good["failures"] == []
        assert good["inherit_environment"] is False
        assert good["timeout_seconds"] is None
        assert good["files"] == [
            {
                "path": str(script.resolve()),
                "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            }
        ]
        assert set(good["startup"]) == {
            "samples_seconds",
            "minimum_seconds",
            "median_seconds",
            "mean_seconds",
            "standard_deviation_seconds",
        }
        assert [record["size"] for record in good["results"]] == [5, 10]
        assert [record["distribution"] for record in good["results"]] == ["uniform", "uniform"]
        assert [record["case_identifier"] for record in good["results"]] == [
            "generated:uniform:size=5:seed=7",
            "generated:uniform:size=10:seed=7",
        ]
        assert good["time_growth"] == {"uniform": None}
        assert "growth" not in good
        assert good["operation_growth"] == {"uniform": {}}
        assert all(record["operation_counts"] is None for record in good["results"])
        for record in good["results"]:
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

    def test_failed_implementation_record(self, document: dict[str, Any]) -> None:
        broken = document["implementations"][1]
        assert broken["name"] == "broken"
        (failure,) = broken["failures"]
        assert failure["stage"] == "startup"
        assert (failure["distribution"], failure["size"]) == (None, None)
        assert "exited with code 3" in failure["message"]
        assert broken["startup"] is None
        assert broken["results"] == []
        assert broken["time_growth"] == {"uniform": None}
        assert broken["working_directory"] is None

    def test_a_failure_in_one_distribution_names_it(self) -> None:
        implementation = Implementation(name="a", command=("./a",))
        report = BenchmarkReport(
            problem_name="sorting",
            settings=SETTINGS,
            implementations=(
                ImplementationBenchmark(
                    implementation,
                    None,
                    (),
                    (BenchmarkFailure(FailureStage.MEASUREMENT, "it broke", "sorted", 10),),
                ),
            ),
        )
        record = benchmark_report_to_json(report)["implementations"][0]
        assert record["failures"] == [
            {"stage": "measurement", "distribution": "sorted", "size": 10, "message": "it broke"}
        ]

    def test_the_effective_settings_of_an_implementation_are_recorded(self) -> None:
        implementation = Implementation(
            name="a", command=("./a",), inherit_environment=True, timeout_seconds=5.0
        )
        report = BenchmarkReport(
            "sorting", SETTINGS, (ImplementationBenchmark(implementation, None, ()),)
        )
        record = benchmark_report_to_json(report)["implementations"][0]
        assert (record["inherit_environment"], record["timeout_seconds"]) == (True, 5.0)

    def test_reported_samples_reflect_startup_subtraction(self) -> None:
        ticks = itertools.count(1)
        settings = BenchmarkSettings(
            seed=0,
            sizes=(5,),
            repetitions=2,
            warmup=0,
            timeout_seconds=30.0,
            verify_outputs=True,
            subtract_startup_time=True,
        )
        report = run_benchmark(
            SortingProblem(),
            named("a"),
            settings,
            runner_factory=FakeRunners(
                {"a": sort_correctly}, durations={"a": lambda values: next(ticks) / 100}
            ),
        )
        record = benchmark_report_to_json(report)["implementations"][0]
        startup_mean = record["startup"]["mean_seconds"]
        expected = sorted(raw - startup_mean for raw in record["results"][0]["raw_samples_seconds"])
        assert record["results"][0]["samples_seconds"] == pytest.approx(expected)

    def test_raw_samples_are_reported_in_run_order(self) -> None:
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
    def document(self) -> dict[str, Any]:
        def quadratic(values: list[int]) -> float:
            return 1e-7 * len(values) ** 2

        settings = BenchmarkSettings(
            seed=2,
            sizes=(100, 200, 400),
            repetitions=1,
            warmup=0,
            timeout_seconds=30.0,
            verify_outputs=True,
            subtract_startup_time=False,
            distributions=("uniform", "sorted"),
        )
        report = run_benchmark(
            SortingProblem(),
            named("quadratic", "broken"),
            settings,
            runner_factory=FakeRunners(
                {"quadratic": sort_correctly, "broken": crash},
                durations={"quadratic": quadratic},
            ),
        )
        return json.loads(json.dumps(benchmark_report_to_json(report)))

    def test_the_settings_list_the_distributions(self, document: dict[str, Any]) -> None:
        assert document["settings"]["distributions"] == ["uniform", "sorted"]

    def test_each_result_names_its_distribution_and_case(self, document: dict[str, Any]) -> None:
        results = document["implementations"][0]["results"]
        assert [(record["distribution"], record["size"]) for record in results] == [
            ("uniform", 100),
            ("uniform", 200),
            ("uniform", 400),
            ("sorted", 100),
            ("sorted", 200),
            ("sorted", 400),
        ]
        assert results[3]["case_identifier"] == "generated:sorted:size=100:seed=2"
        assert "case_name" not in results[0]

    def test_growth_has_an_exponent_and_a_class_per_distribution(
        self, document: dict[str, Any]
    ) -> None:
        growth = document["implementations"][0]["time_growth"]
        assert set(growth) == {"uniform", "sorted"}
        for distribution in ("uniform", "sorted"):
            assert set(growth[distribution]) == {"exponent", "class", "reliable"}
            assert growth[distribution]["exponent"] == pytest.approx(2.0)
            assert growth[distribution]["class"] == "n^2"

    def test_an_implementation_without_measurements_has_null_growth(
        self, document: dict[str, Any]
    ) -> None:
        assert document["implementations"][1]["time_growth"] == {"uniform": None, "sorted": None}


class TestUnreliableGrowthInTheBenchmarkJson:
    def test_a_series_that_is_mostly_startup_says_so(self) -> None:
        settings = BenchmarkSettings(
            seed=1,
            sizes=(100, 200, 400),
            repetitions=1,
            warmup=0,
            timeout_seconds=30.0,
            verify_outputs=True,
            subtract_startup_time=False,
        )
        report = run_benchmark(
            SortingProblem(),
            named("quick"),
            settings,
            runner_factory=FakeRunners(
                {"quick": sort_correctly},
                durations={"quick": lambda values: 0.01 + 1e-9 * len(values)},
            ),
        )
        growth = benchmark_report_to_json(report)["implementations"][0]["time_growth"]["uniform"]
        assert growth["reliable"] is False
        assert growth["class"] is not None


class TestOperationCountsInTheBenchmarkJson:
    @pytest.fixture(scope="class")
    def document(self) -> dict[str, Any]:
        settings = BenchmarkSettings(
            seed=2,
            sizes=(8, 16, 32),
            repetitions=1,
            warmup=0,
            timeout_seconds=30.0,
            verify_outputs=True,
            subtract_startup_time=False,
            distributions=("reversed",),
            count_operations=True,
        )
        report = run_benchmark(
            SortingProblem(),
            named("insertion", "silent"),
            settings,
            runner_factory=FakeRunners(
                {"insertion": sort_correctly, "silent": sort_correctly},
                traces={"insertion": insertion_sort_trace},
            ),
        )
        return json.loads(json.dumps(benchmark_report_to_json(report)))

    def test_the_settings_say_that_operations_were_counted(self, document: dict[str, Any]) -> None:
        assert document["settings"]["count_operations"] is True

    def test_each_result_has_its_counts_or_null(self, document: dict[str, Any]) -> None:
        insertion, silent = document["implementations"]
        assert [record["operation_counts"] for record in insertion["results"]] == [
            {"compares": size * (size - 1) // 2, "swaps": size * (size - 1) // 2, "writes": 0}
            for size in (8, 16, 32)
        ]
        assert [record["operation_counts"] for record in silent["results"]] == [None] * 3
        assert [record["operation_issue"] for record in insertion["results"]] == [None] * 3

    def test_growth_maps_each_distribution_to_the_growth_of_each_operation(
        self, document: dict[str, Any]
    ) -> None:
        insertion, silent = document["implementations"]
        growth = insertion["operation_growth"]["reversed"]
        assert set(growth) == {"compares", "swaps", "writes"}
        assert growth["compares"]["exponent"] == pytest.approx(2.0, abs=0.2)
        assert growth["compares"]["class"] == "n^2"
        assert "reliable" not in growth["compares"]
        assert growth["writes"] is None
        assert silent["operation_growth"] == {"reversed": {}}


class TestMalformedTraceInTheBenchmarkJson:
    def test_the_measurement_records_why_it_has_no_counts(self) -> None:
        settings = BenchmarkSettings(
            seed=2,
            sizes=(8,),
            repetitions=1,
            warmup=0,
            timeout_seconds=30.0,
            verify_outputs=True,
            subtract_startup_time=False,
            count_operations=True,
        )
        report = run_benchmark(
            SortingProblem(),
            named("a"),
            settings,
            runner_factory=FakeRunners(
                {"a": sort_correctly}, traces={"a": lambda values: TraceFailure("bad kind 7")}
            ),
        )
        (record,) = benchmark_report_to_json(report)["implementations"][0]["results"]
        assert record["operation_counts"] is None
        assert record["operation_issue"] == {"kind": "malformed trace", "message": "bad kind 7"}


PLAN = CasePlan(random_case_count=1, maximum_size=12, generator_names=("uniform", "sorted"), seed=4)


class TestTestingReportToJson:
    @pytest.fixture(scope="class")
    def implementations(self, tmp_path_factory: pytest.TempPathFactory) -> list[Implementation]:
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
    def document(self, implementations: list[Implementation]) -> dict[str, Any]:
        problem = SortingProblem()
        cases = [
            resolve_case(problem, identifier)
            for identifier in ("fixture:single", "generated:uniform:size=12:seed=5")
        ]
        report = run_tests(
            problem,
            implementations[:2],
            cases,
            timeout_seconds=7.0,
            shrink_time_budget_seconds=12.0,
            runner_factory=FakeRunners({"good": sort_correctly, "bad": drop_last_above_five}),
        )
        document = correctness_report_to_json(
            report,
            implementations=implementations,
            plan=PLAN,
            build_failures={"unbuilt": "make: error"},
        )
        return json.loads(json.dumps(document))

    def test_top_level_keys_and_versions(self, document: dict[str, Any]) -> None:
        assert set(document) == {
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
        assert document["report"] == "test"
        assert document["format_version"] == TEST_FORMAT_VERSION == 2
        assert document["problem"] == "sorting"

    def test_the_settings_record_the_plan_the_shrink_limits_and_the_timeout(
        self, document: dict[str, Any]
    ) -> None:
        assert document["settings"] == {
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

    def test_explicit_cases_have_no_plan(self, implementations: list[Implementation]) -> None:
        problem = SortingProblem()
        report = run_tests(
            problem,
            implementations[:1],
            [resolve_case(problem, "fixture:single")],
            shrink=False,
            runner_factory=FakeRunners({"good": sort_correctly}),
        )
        settings = correctness_report_to_json(report, implementations=implementations[:1])[
            "settings"
        ]
        assert settings["cases"] == "explicit"
        assert [settings[key] for key in ("seed", "random_cases", "maximum_size")] == [None] * 3
        assert settings["distributions"] is None and settings["include_fixtures"] is None
        assert settings["shrink"]["enabled"] is False

    def test_every_implementation_is_described_like_in_the_benchmark_report(
        self, document: dict[str, Any], implementations: list[Implementation]
    ) -> None:
        good, bad, unbuilt = document["implementations"]
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
        assert bad["command"] == ["./bad"] and bad["files"] == []
        assert unbuilt["command"] == ["./unbuilt"]

    def test_a_build_failure_means_not_passed_even_when_every_run_passed(self) -> None:
        problem = SortingProblem()
        report = run_tests(
            problem,
            named("good"),
            [resolve_case(problem, "fixture:single")],
            runner_factory=FakeRunners({"good": sort_correctly}),
        )
        implementations = named("good", "x")
        assert correctness_report_to_json(report, implementations=implementations[:1])["passed"]
        failed_build = correctness_report_to_json(
            report, implementations=implementations, build_failures={"x": "boom"}
        )
        assert failed_build["passed"] is False

    def test_an_implementation_that_cannot_run_is_listed_with_the_reason_and_no_outcomes(
        self,
    ) -> None:
        problem = SortingProblem()
        report = run_tests(
            problem,
            named("good"),
            [resolve_case(problem, "fixture:single")],
            runner_factory=FakeRunners({"good": sort_correctly}),
        )
        document = correctness_report_to_json(
            report,
            implementations=named("good", "missing"),
            unrunnable={"missing": "command not found: ./missing"},
        )
        good, missing = document["implementations"]
        assert (good["cannot_run"], good["build_failure"]) == (None, None)
        assert missing["cannot_run"] == "command not found: ./missing"
        assert missing["build_failure"] is None and missing["outcomes"] == []
        assert document["passed"] is False

    def test_saved_inputs_are_recorded_on_the_failing_outcomes(
        self, tmp_path: Path, implementations: list[Implementation]
    ) -> None:
        problem = SortingProblem()
        report = run_tests(
            problem,
            implementations[:2],
            [resolve_case(problem, "generated:uniform:size=12:seed=5")],
            runner_factory=FakeRunners({"good": sort_correctly, "bad": drop_last_above_five}),
        )
        saved = save_failing_inputs(problem, report, tmp_path / "failures")
        document = correctness_report_to_json(
            report, implementations=implementations[:2], saved_inputs=saved
        )
        good, bad = document["implementations"]
        (outcome,) = bad["outcomes"]
        assert outcome["saved_input"] == str(saved.inputs[("bad", outcome["case"])])
        assert outcome["saved_shrunk_input"] == str(saved.shrunk_inputs[("bad", outcome["case"])])
        assert outcome["category"] == "wrong length"
        assert good["outcomes"][0]["saved_input"] is None

    def test_cases_describe_their_origin(self, document: dict[str, Any]) -> None:
        assert [case["kind"] for case in document["cases"]] == ["fixture", "generated"]
        assert document["cases"][1] == {
            "identifier": "generated:uniform:size=12:seed=5",
            "kind": "generated",
            "distribution": "uniform",
            "size": 12,
            "seed": 5,
        }

    def test_implementations_have_summaries_and_outcomes_in_case_order(
        self, document: dict[str, Any]
    ) -> None:
        good, bad, unbuilt = document["implementations"]
        assert (good["name"], good["summary"]) == ("good", {"passed": 2, "failed": 0, "errors": 0})
        assert bad["summary"] == {"passed": 1, "failed": 1, "errors": 0}
        assert [outcome["case"] for outcome in bad["outcomes"]] == [
            "fixture:single",
            "generated:uniform:size=12:seed=5",
        ]
        assert good["build_failure"] is None
        assert unbuilt["build_failure"] == "make: error"
        assert unbuilt["summary"] == {"passed": 0, "failed": 0, "errors": 0}
        assert unbuilt["outcomes"] == []

    def test_a_failing_outcome_carries_the_detail_and_the_shrunk_input(
        self, document: dict[str, Any]
    ) -> None:
        passing, failing = document["implementations"][1]["outcomes"]
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
        assert failing["status"] == "failed"
        assert failing["message"] == "Output length 11 does not match input length 12"
        assert set(failing["failure"]) == {"input", "expected", "actual"}
        assert failing["shrunk"] == {
            "case": "shrunk:generated:uniform:size=12:seed=5",
            "message": "Output length 5 does not match input length 6",
            "input": "[0, 0, 0, 0, 0, 0]",
            "expected": "[0, 0, 0, 0, 0, 0]",
            "actual": "[0, 0, 0, 0, 0]",
        }
