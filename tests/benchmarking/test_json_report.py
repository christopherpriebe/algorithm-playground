"""Tests for the JSON report of a benchmark run."""

import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from algorithm_playground.core import (
    BENCHMARK_FORMAT_VERSION,
    BenchmarkFailure,
    BenchmarkReport,
    BenchmarkSettings,
    FailureStage,
    Implementation,
    ImplementationBenchmark,
    SizeMeasurement,
    convert_benchmark_report_to_json,
    run_benchmark,
    summarize,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    TraceFailure,
    build_insertion_sort_trace,
    build_named_implementations,
    crash,
    sort_correctly,
)


def build_settings(  # noqa: PLR0913  keyword-only options mirror the fields of BenchmarkSettings
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
    return json.loads(json.dumps(convert_benchmark_report_to_json(report)))


SETTINGS = build_settings(seed=7, sizes=(5, 10), repetitions=2)


@pytest.fixture(scope="module")
def good_directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The working directory of the good implementation, holding its script."""
    directory = tmp_path_factory.mktemp("report")
    (directory / "good.py").write_text("#!/usr/bin/env python3\n")
    return directory


@pytest.fixture(scope="module")
def document(good_directory: Path) -> dict[str, Any]:
    """The report of a good and a crashing implementation; the commands are never run."""
    script = good_directory / "good.py"
    good = Implementation(
        name="good", command=(str(script),), working_directory=good_directory
    )
    broken = Implementation(name="broken", command=("./broken",))
    report = run_benchmark(
        SortingProblem(),
        [good, broken],
        SETTINGS,
        runner_factory=FakeRunners({"good": sort_correctly, "broken": crash}),
    )
    return convert_benchmark_report_to_json(report)


def test_is_json_serializable(document: dict[str, Any]) -> None:
    """Test the document survives a round trip through JSON text."""
    assert json.loads(json.dumps(document)) == document


def test_the_benchmark_report_has_exactly_the_documented_top_level_keys(
    document: dict[str, Any],
) -> None:
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


def test_the_benchmark_report_names_its_kind_version_and_problem(
    document: dict[str, Any],
) -> None:
    """Test the document names its kind, its format version and the problem."""
    assert document["report"] == "benchmark"
    assert document["format_version"] == BENCHMARK_FORMAT_VERSION == 6
    assert document["problem"] == "sorting"


def test_settings_record_every_benchmark_parameter(document: dict[str, Any]) -> None:
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


def test_host_and_metadata_are_filled_in(document: dict[str, Any]) -> None:
    """Test the host system, the tool version and the generation time are recorded."""
    assert document["host"]["system"]
    assert document["metadata"]["algorithm_playground_version"]
    assert document["metadata"]["generated_at"]


def test_successful_implementation_record_describes_its_configuration(
    document: dict[str, Any], good_directory: Path
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
    document: dict[str, Any], good_directory: Path
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
    document: dict[str, Any],
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
    document: dict[str, Any],
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
    document: dict[str, Any],
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
    document: dict[str, Any],
) -> None:
    """Test results hold no operation counts and the operation growth is empty."""
    good = document["implementations"][0]

    assert all(record["operation_counts"] is None for record in good["results"])
    assert good["operation_growth"] == {"uniform": {}}


def test_two_sizes_are_too_few_for_a_time_growth_estimate(
    document: dict[str, Any],
) -> None:
    """Test the time growth is null per distribution and there is no legacy growth key."""
    good = document["implementations"][0]

    assert good["time_growth"] == {"uniform": None}
    assert "growth" not in good


def test_failed_implementation_record(document: dict[str, Any]) -> None:
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


def test_a_failure_in_one_distribution_names_it() -> None:
    """Test a measurement failure records its stage, distribution, size and message."""
    implementation = Implementation(name="a", command=("./a",))
    failure = BenchmarkFailure(
        stage=FailureStage.MEASUREMENT,
        message="it broke",
        distribution="sorted",
        size=10,
    )
    report = BenchmarkReport(
        problem_name="sorting",
        settings=SETTINGS,
        implementations=(
            ImplementationBenchmark(
                implementation=implementation,
                startup=None,
                measurements=(),
                failures=(failure,),
            ),
        ),
    )

    record = convert_benchmark_report_to_json(report)["implementations"][0]

    assert record["failures"] == [
        {
            "stage": "measurement",
            "distribution": "sorted",
            "size": 10,
            "message": "it broke",
        }
    ]


def test_the_effective_settings_of_an_implementation_are_recorded() -> None:
    """Test the environment policy and timeout of an implementation appear in its record."""
    implementation = Implementation(
        name="a", command=("./a",), inherit_environment=True, timeout_seconds=5.0
    )
    report = BenchmarkReport(
        problem_name="sorting",
        settings=SETTINGS,
        implementations=(
            ImplementationBenchmark(
                implementation=implementation, startup=None, measurements=()
            ),
        ),
    )

    record = convert_benchmark_report_to_json(report)["implementations"][0]

    assert (record["inherit_environment"], record["timeout_seconds"]) == (True, 5.0)


def test_reported_samples_reflect_startup_subtraction() -> None:
    """Test the samples are the raw samples minus the mean startup time."""
    ticks = itertools.count(1)
    settings = build_settings(repetitions=2, subtract_startup_time=True)
    runners = FakeRunners(
        {"a": sort_correctly}, durations={"a": lambda _: next(ticks) / 100}
    )

    document = build_benchmark_json(settings, runners, "a")

    record = document["implementations"][0]
    startup_mean = record["startup"]["mean_seconds"]
    expected = sorted(
        raw - startup_mean for raw in record["results"][0]["raw_samples_seconds"]
    )
    assert record["results"][0]["samples_seconds"] == pytest.approx(expected)


def test_raw_samples_are_reported_in_run_order() -> None:
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
        implementations=(
            ImplementationBenchmark(
                implementation=implementation, startup=None, measurements=(measurement,)
            ),
        ),
    )

    record = convert_benchmark_report_to_json(report)["implementations"][0]["results"][
        0
    ]

    assert record["raw_samples_seconds"] == [0.3, 0.1, 0.2]
    assert record["samples_seconds"] == [0.1, 0.2, 0.3]


@pytest.fixture(scope="module")
def distributions_document() -> dict[str, Any]:
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
    distributions_document: dict[str, Any],
) -> None:
    """Test the settings name the measured distributions in order."""
    assert distributions_document["settings"]["distributions"] == [
        "uniform",
        "sorted",
    ]


def test_each_result_names_its_distribution_and_size(
    distributions_document: dict[str, Any],
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
    distributions_document: dict[str, Any],
) -> None:
    """Test a result identifies the generated case and has no legacy case name."""
    results = distributions_document["implementations"][0]["results"]

    assert results[3]["case_identifier"] == "generated:sorted:size=100:seed=2"
    assert "case_name" not in results[0]


def test_growth_is_reported_for_each_distribution(
    distributions_document: dict[str, Any],
) -> None:
    """Test the time growth has one entry per measured distribution."""
    growth = distributions_document["implementations"][0]["time_growth"]

    assert set(growth) == {"uniform", "sorted"}


@pytest.mark.parametrize("distribution", ["uniform", "sorted"])
def test_growth_has_an_exponent_and_a_class_per_distribution(
    distributions_document: dict[str, Any], distribution: str
) -> None:
    """Test the growth of a distribution holds the exponent, class and reliability."""
    growth = distributions_document["implementations"][0]["time_growth"][distribution]

    assert set(growth) == {"exponent", "class", "reliable"}
    assert growth["exponent"] == pytest.approx(2.0)
    assert growth["class"] == "n^2"


def test_an_implementation_without_measurements_has_null_growth(
    distributions_document: dict[str, Any],
) -> None:
    """Test an implementation that failed has a null growth for every distribution."""
    broken = distributions_document["implementations"][1]

    assert broken["time_growth"] == {"uniform": None, "sorted": None}


def test_a_series_that_is_mostly_startup_says_so() -> None:
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


@pytest.fixture(scope="module")
def operations_document() -> dict[str, Any]:
    """The report of an implementation with a trace and one without, counting operations."""
    settings = build_settings(
        seed=2,
        sizes=(8, 16, 32),
        distributions=("reversed",),
        count_operations=True,
    )
    runners = FakeRunners(
        {"insertion": sort_correctly, "silent": sort_correctly},
        traces={"insertion": build_insertion_sort_trace},
    )
    return build_benchmark_json(settings, runners, "insertion", "silent")


def test_the_settings_say_that_operations_were_counted(
    operations_document: dict[str, Any],
) -> None:
    """Test the settings record that operation counting was on."""
    assert operations_document["settings"]["count_operations"] is True


def test_each_result_has_the_counts_of_its_trace(
    operations_document: dict[str, Any],
) -> None:
    """Test every result of a traced implementation holds the operation counts of its sort."""
    insertion = operations_document["implementations"][0]

    assert [record["operation_counts"] for record in insertion["results"]] == [
        {
            "compares": size * (size - 1) // 2,
            "swaps": size * (size - 1) // 2,
            "writes": 0,
        }
        for size in (8, 16, 32)
    ]
    assert [record["operation_issue"] for record in insertion["results"]] == [None] * 3


def test_an_implementation_without_a_trace_has_null_counts(
    operations_document: dict[str, Any],
) -> None:
    """Test every result of an implementation that writes no trace has null counts."""
    silent = operations_document["implementations"][1]

    assert [record["operation_counts"] for record in silent["results"]] == [None] * 3


def test_growth_maps_each_distribution_to_the_growth_of_each_operation(
    operations_document: dict[str, Any],
) -> None:
    """Test the operation growth names every operation and fits compares to n squared."""
    growth = operations_document["implementations"][0]["operation_growth"]["reversed"]

    assert set(growth) == {"compares", "swaps", "writes"}
    assert growth["compares"]["exponent"] == pytest.approx(2.0, abs=0.2)
    assert growth["compares"]["class"] == "n^2"
    assert "reliable" not in growth["compares"]


def test_an_operation_that_is_never_counted_has_null_growth(
    operations_document: dict[str, Any],
) -> None:
    """Test an operation whose count is always zero has no growth."""
    growth = operations_document["implementations"][0]["operation_growth"]["reversed"]

    assert growth["writes"] is None


def test_an_implementation_without_a_trace_has_no_operation_growth(
    operations_document: dict[str, Any],
) -> None:
    """Test the operation growth of an implementation that writes no trace is empty."""
    silent = operations_document["implementations"][1]

    assert silent["operation_growth"] == {"reversed": {}}


def test_the_measurement_records_why_it_has_no_counts() -> None:
    """Test a trace that cannot be decoded leaves no counts and records the issue."""
    settings = build_settings(seed=2, sizes=(8,), count_operations=True)
    runners = FakeRunners(
        {"a": sort_correctly},
        traces={"a": lambda _: TraceFailure("bad kind 7")},
    )

    document = build_benchmark_json(settings, runners, "a")

    (record,) = document["implementations"][0]["results"]
    assert record["operation_counts"] is None
    assert record["operation_issue"] == {
        "kind": "malformed trace",
        "message": "bad kind 7",
    }
