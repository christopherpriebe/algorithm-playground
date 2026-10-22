"""Serialize benchmark and test results to JSON-compatible dictionaries.

Both reports say what they are (``"report": "benchmark"`` or ``"test"``) and
record the settings, each implementation's command and a SHA-256 fingerprint
of the files the command refers to, the host, and the package version, so a
result can be tied to the code and machine that produced it. The benchmark
report adds the timings per distribution and size with the estimated growth
(exponent and class; and, when counted, the operation counts and their growth).
Both reports list the ``dimensions`` of the problem (a ``name`` and a
``minimum`` each), and a size is always an object with one integer per
dimension, such as ``{"vertices": 2, "edges": 3}``; the benchmark report also
names the ``growth_dimension`` that its growth is fitted against.
The test report records the largest size it generated in ``maximum_size``:
the one asked for, else the default maximum of every dimension. It lists the cases and, for every implementation, each outcome
with the failure details, the shrunk input and where the inputs were saved when
there are any.
When the problem scores outputs, both reports name the score in a top-level
``score_name`` (``null`` otherwise). In the test report every outcome has a
``score`` (``null`` without one) and every implementation's ``summary`` counts
the ``scored`` outcomes and gives their ``mean_score`` (``null`` when there
are none). In the benchmark report every result has a ``scores`` list, the
scores of its verified timed repetitions in run order (empty when there are
none).
"""

import datetime as dt
import hashlib
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from algorithm_playground import __version__ as package_version
from algorithm_playground.core._benchmarking import (
    BenchmarkFailure,
    BenchmarkReport,
    ImplementationBenchmark,
    SizeMeasurement,
)
from algorithm_playground.core._cases import (
    AnyCase,
    CasePlan,
    FixtureOrigin,
    GeneratedOrigin,
)
from algorithm_playground.core._dimensions import Dimension, Size
from algorithm_playground.core._implementation import Implementation
from algorithm_playground.core._saved_inputs import SavedInputs
from algorithm_playground.core._single_run import CaseStatus
from algorithm_playground.core._statistics import Growth, TimingSummary
from algorithm_playground.core._testing import CaseOutcome, FailureDetail, TestReport

__all__ = [
    "BENCHMARK_FORMAT_VERSION",
    "TEST_FORMAT_VERSION",
    "JsonObject",
    "convert_benchmark_report_to_json",
    "convert_correctness_report_to_json",
]

_READ_CHUNK_BYTES = 64 * 1024

BENCHMARK_FORMAT_VERSION = 8
TEST_FORMAT_VERSION = 4

# A JSON document: the objects of a report mix text, numbers, booleans, lists and nested objects.
JsonObject = dict[str, Any]


def _size_record(size: Size | None) -> JsonObject | None:
    return None if size is None else dict(size)


def _dimensions_record(dimensions: Sequence[Dimension]) -> list[JsonObject]:
    return [
        {"name": dimension.name, "minimum": dimension.minimum}
        for dimension in dimensions
    ]


def _effective_maximum_size(report: TestReport, plan: CasePlan | None) -> Size | None:
    if plan is None:
        return None
    if plan.maximum_size is not None:
        return plan.maximum_size
    return Size(
        **{dimension.name: dimension.default_maximum for dimension in report.dimensions}
    )


def _test_settings_record(report: TestReport, plan: CasePlan | None) -> JsonObject:
    settings = report.settings
    return {
        "cases": "explicit" if plan is None else "planned",
        "seed": None if plan is None else plan.seed,
        "random_cases": None if plan is None else plan.random_case_count,
        "maximum_size": _size_record(_effective_maximum_size(report, plan)),
        "distributions": None if plan is None else list(plan.generator_names),
        "include_fixtures": None if plan is None else plan.include_fixtures,
        "shrink": {
            "enabled": settings.shrink,
            "maximum_shrunk_cases": settings.maximum_shrunk_cases,
            "maximum_runs": settings.maximum_shrink_runs,
            "time_budget_seconds": settings.shrink_time_budget_seconds,
        },
        "timeout_seconds": settings.timeout_seconds,
    }


def _host_record() -> JsonObject:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version,
    }


def _metadata_record() -> JsonObject:
    return {
        "algorithm_playground_version": package_version,
        "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(),
    }


def _case_record(case: AnyCase) -> JsonObject:
    origin = case.origin
    if isinstance(origin, FixtureOrigin):
        return {
            "identifier": case.identifier,
            "kind": "fixture",
            "fixture": origin.name,
        }
    if isinstance(origin, GeneratedOrigin):
        return {
            "identifier": case.identifier,
            "kind": "generated",
            "distribution": origin.generator_name,
            "size": _size_record(origin.size),
            "seed": origin.seed,
        }
    return {"identifier": case.identifier, "kind": "shrunk"}


def _path_or_none(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _detail_record(detail: FailureDetail | None) -> JsonObject | None:
    if detail is None:
        return None
    return {
        "input": detail.input_text,
        "expected": detail.expected_text,
        "actual": detail.actual_text,
    }


def _outcome_record(outcome: CaseOutcome, saved: SavedInputs) -> JsonObject:
    shrunk = outcome.shrunk
    key = (outcome.implementation_name, outcome.case_identifier)
    return {
        "case": outcome.case_identifier,
        "status": outcome.status.value,
        "category": outcome.category,
        "message": outcome.message,
        "failure": _detail_record(outcome.detail),
        "saved_input": _path_or_none(saved.inputs.get(key)),
        "saved_shrunk_input": _path_or_none(saved.shrunk_inputs.get(key)),
        "shrink_note": outcome.shrink_note,
        "score": outcome.score,
        "shrunk": (
            None
            if shrunk is None
            else {
                "case": shrunk.case.identifier,
                "message": shrunk.message,
                **(_detail_record(shrunk.detail) or {}),
            }
        ),
    }


def _tested_implementation_record(
    report: TestReport, name: str, saved: SavedInputs
) -> JsonObject:
    outcomes = report.outcomes_for(name)
    scores = [outcome.score for outcome in outcomes if outcome.score is not None]
    return {
        "build_failure": None,
        "cannot_run": None,
        "summary": {
            "passed": sum(outcome.status is CaseStatus.PASSED for outcome in outcomes),
            "failed": sum(outcome.status is CaseStatus.FAILED for outcome in outcomes),
            "errors": sum(outcome.status is CaseStatus.ERROR for outcome in outcomes),
            "scored": len(scores),
            "mean_score": sum(scores) / len(scores) if scores else None,
        },
        "outcomes": [_outcome_record(outcome, saved) for outcome in outcomes],
    }


def _sha256_or_none(path: Path) -> str | None:
    """Return the hexadecimal SHA-256 digest of the file at ``path``, or ``None`` if unreadable."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_READ_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _implementation_description(implementation: Implementation) -> JsonObject:
    """Describe how an implementation is run.

    Returns:
        The command and environment settings, with a fingerprint of each file
        the command names.
    """
    working_directory = implementation.working_directory
    return {
        "name": implementation.name,
        "command": list(implementation.command),
        "working_directory": str(working_directory)
        if working_directory is not None
        else None,
        "inherit_environment": implementation.inherit_environment,
        "timeout_seconds": implementation.timeout_seconds,
        "files": [
            {"path": str(path), "sha256": _sha256_or_none(path)}
            for path in implementation.referenced_files()
        ],
    }


def _implementation_test_record(
    report: TestReport,
    implementation: Implementation,
    saved: SavedInputs,
    *,
    build_failures: Mapping[str, str],
    unrunnable: Mapping[str, str],
) -> JsonObject:
    """Describe one implementation of a test report, including one never run.

    Returns:
        The implementation description with its outcomes, or the reason it
        produced none.
    """
    record = _implementation_description(implementation)
    name = implementation.name
    if name in build_failures or name in unrunnable:
        record.update(
            build_failure=build_failures.get(name),
            cannot_run=unrunnable.get(name),
            summary={
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "scored": 0,
                "mean_score": None,
            },
            outcomes=[],
        )
    else:
        record.update(_tested_implementation_record(report, name, saved))
    return record


def _growth_record(growth: Growth | None) -> JsonObject | None:
    if growth is None:
        return None
    return {"exponent": growth.exponent, "class": growth.growth_class}


def _time_growth_record(
    benchmark: ImplementationBenchmark, distribution: str
) -> JsonObject | None:
    """Describe the time growth of one distribution.

    Returns:
        The growth record with whether the medians allow trusting it, or
        ``None`` when there is no growth estimate.
    """
    record = _growth_record(benchmark.growth(distribution))
    if record is not None:
        record["reliable"] = benchmark.is_growth_reliable(distribution)
    return record


def _failure_record(failure: BenchmarkFailure) -> JsonObject:
    return {
        "stage": failure.stage.value,
        "distribution": failure.distribution,
        "size": _size_record(failure.size),
        "message": failure.message,
    }


def _summary_fields(summary: TimingSummary) -> JsonObject:
    return {
        "samples_seconds": list(summary.samples),
        "minimum_seconds": summary.minimum,
        "median_seconds": summary.median,
        "mean_seconds": summary.mean,
        "standard_deviation_seconds": summary.standard_deviation,
    }


def _measurement_record(measurement: SizeMeasurement) -> JsonObject:
    # The summary fields describe the reported samples (startup subtracted when
    # requested, sorted); raw_samples_seconds holds the unadjusted wall times in run order.
    return {
        "distribution": measurement.distribution,
        "size": _size_record(measurement.size),
        "case_identifier": measurement.case_identifier,
        "operation_counts": (
            None
            if measurement.operation_counts is None
            else dict(measurement.operation_counts)
        ),
        "operation_issue": (
            None
            if measurement.operation_issue is None
            else {
                "kind": measurement.operation_issue.kind.value,
                "message": measurement.operation_issue.message,
            }
        ),
        "scores": list(measurement.scores),
        **_summary_fields(measurement.summary),
        "raw_samples_seconds": list(measurement.raw_samples),
    }


def _implementation_record(
    benchmark: ImplementationBenchmark, distributions: tuple[str, ...]
) -> JsonObject:
    return {
        **_implementation_description(benchmark.implementation),
        "failures": [_failure_record(failure) for failure in benchmark.failures],
        "startup": _summary_fields(benchmark.startup)
        if benchmark.startup is not None
        else None,
        "results": [
            _measurement_record(measurement) for measurement in benchmark.measurements
        ],
        "time_growth": {
            name: _time_growth_record(benchmark, name) for name in distributions
        },
        "operation_growth": {
            name: {
                operation: _growth_record(growth)
                for operation, growth in benchmark.operation_growth(name).items()
            }
            for name in distributions
        },
    }


def convert_benchmark_report_to_json(report: BenchmarkReport) -> JsonObject:
    """Convert a benchmark report to a dictionary that :func:`json.dumps` can serialize.

    ``format_version`` identifies the layout of the dictionary and changes
    when a key is renamed, removed, or reinterpreted. Each implementation has a
    ``time_growth`` object that maps every measured distribution to the growth
    of the median time (minus the median startup time) against the size, or
    ``null`` when there are fewer than three positive startup-adjusted medians,
    and a ``failures`` list. A growth is an object with
    the fitted ``exponent``, the best-fitting ``class`` (``"1"``, ``"log n"``,
    ``"n"``, ``"n log n"``, ``"n^2"`` or ``"n^3"``; ``null`` when too few
    points could be compared) and, for time only, ``reliable``, which is false
    when the medians are too close to the startup time to tell. With operation
    counting, every result has an ``operation_counts`` object (``null`` when the
    implementation reported none) and an ``operation_issue`` saying why when it
    could not, and every implementation an ``operation_growth`` object that maps
    each distribution to the growth of every reported operation count.

    Args:
        report: The benchmark report to convert.

    Returns:
        The report as a JSON document.
    """
    settings = report.settings
    return {
        "report": "benchmark",
        "format_version": BENCHMARK_FORMAT_VERSION,
        "problem": report.problem_name,
        "settings": {
            "seed": settings.seed,
            "sizes": [_size_record(size) for size in settings.sizes],
            "repetitions": settings.repetitions,
            "warmup": settings.warmup,
            "timeout_seconds": settings.timeout_seconds,
            "verify_outputs": settings.verify_outputs,
            "subtract_startup_time": settings.subtract_startup_time,
            "distributions": list(settings.distributions),
            "count_operations": settings.count_operations,
        },
        "dimensions": _dimensions_record(report.dimensions),
        "growth_dimension": report.growth_dimension,
        "score_name": report.score_name,
        "implementations": [
            _implementation_record(benchmark, settings.distributions)
            for benchmark in report.implementations
        ],
        "host": _host_record(),
        "metadata": _metadata_record(),
    }


def convert_correctness_report_to_json(  # noqa: PLR0913  one keyword-only option per optional report section
    report: TestReport,
    *,
    implementations: Sequence[Implementation],
    plan: CasePlan | None = None,
    build_failures: Mapping[str, str] | None = None,
    unrunnable: Mapping[str, str] | None = None,
    saved_inputs: SavedInputs | None = None,
) -> JsonObject:
    """Convert a test report to a dictionary that :func:`json.dumps` can serialize.

    ``format_version`` changes when a key is renamed, removed, or reinterpreted.

    Args:
        report: The test report to convert.
        implementations: All the implementations that were selected, in order.
        plan: The case plan the cases came from, or ``None`` if named one by one.
        build_failures: The build output of each implementation that was not
            run because its build failed, keyed by name (listed as
            ``build_failure``, with no outcomes).
        unrunnable: The reason for each implementation whose command cannot be
            started, keyed by name (listed as ``cannot_run``, with no outcomes).
        saved_inputs: The saved failing inputs, whose paths join the outcomes.

    Returns:
        The report as a JSON document.
    """
    failed_builds = build_failures or {}
    cannot_run = unrunnable or {}
    saved = saved_inputs or SavedInputs()
    return {
        "report": "test",
        "format_version": TEST_FORMAT_VERSION,
        "problem": report.problem_name,
        "passed": report.has_passed and not failed_builds and not cannot_run,
        "settings": _test_settings_record(report, plan),
        "dimensions": _dimensions_record(report.dimensions),
        "score_name": report.score_name,
        "cases": [_case_record(case) for case in report.cases],
        "implementations": [
            _implementation_test_record(
                report,
                implementation,
                saved,
                build_failures=failed_builds,
                unrunnable=cannot_run,
            )
            for implementation in implementations
        ],
        "host": _host_record(),
        "metadata": _metadata_record(),
    }
