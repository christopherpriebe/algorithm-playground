"""Serialize benchmark and test results to JSON-compatible dictionaries.

Both reports say what they are (``"report": "benchmark"`` or ``"test"``) and
record the settings, each implementation's command and a SHA-256 fingerprint
of the files the command refers to, the host, and the package version, so a
result can be tied to the code and machine that produced it. The benchmark
report adds the timings per distribution and size with the estimated growth
(exponent and class; and, when counted, the operation counts and their growth).
The test report lists the cases and, for every implementation, each outcome
with the failure details, the shrunk input and where the inputs were saved when
there are any.
"""

from __future__ import annotations

import datetime
import hashlib
import platform
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from algorithm_playground import __version__ as package_version
from algorithm_playground.core.benchmarking import (
    BenchmarkFailure,
    BenchmarkReport,
    ImplementationBenchmark,
    SizeMeasurement,
)
from algorithm_playground.core.cases import Case, CasePlan, FixtureOrigin, GeneratedOrigin
from algorithm_playground.core.implementation import Implementation
from algorithm_playground.core.saved_inputs import SavedInputs
from algorithm_playground.core.single_run import CaseStatus
from algorithm_playground.core.statistics import Growth, TimingSummary
from algorithm_playground.core.testing import CaseOutcome, FailureDetail, TestReport

_READ_CHUNK_BYTES = 64 * 1024

BENCHMARK_FORMAT_VERSION = 6
TEST_FORMAT_VERSION = 2


def benchmark_report_to_json(report: BenchmarkReport) -> dict[str, Any]:
    """Convert ``report`` to a dictionary that :func:`json.dumps` can serialize.

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
    """
    settings = report.settings
    return {
        "report": "benchmark",
        "format_version": BENCHMARK_FORMAT_VERSION,
        "problem": report.problem_name,
        "settings": {
            "seed": settings.seed,
            "sizes": list(settings.sizes),
            "repetitions": settings.repetitions,
            "warmup": settings.warmup,
            "timeout_seconds": settings.timeout_seconds,
            "verify_outputs": settings.verify_outputs,
            "subtract_startup_time": settings.subtract_startup_time,
            "distributions": list(settings.distributions),
            "count_operations": settings.count_operations,
        },
        "implementations": [
            _implementation_record(benchmark, settings.distributions)
            for benchmark in report.implementations
        ],
        "host": _host_record(),
        "metadata": _metadata_record(),
    }


def correctness_report_to_json(
    report: TestReport,
    *,
    implementations: Sequence[Implementation],
    plan: CasePlan | None = None,
    build_failures: Mapping[str, str] | None = None,
    unrunnable: Mapping[str, str] | None = None,
    saved_inputs: SavedInputs | None = None,
) -> dict[str, Any]:
    """Convert a test ``report`` to a dictionary that :func:`json.dumps` can serialize.

    ``implementations`` are all the implementations that were selected, in
    order, and ``plan`` is the case plan the cases came from (``None`` when
    the cases were named one by one). ``build_failures`` maps the names of
    implementations that were not run because their build failed to the build
    output, and ``unrunnable`` those whose command cannot be started to the
    reason; they are listed with no outcomes (``build_failure`` and
    ``cannot_run`` say why). ``saved_inputs`` adds the paths of the saved failing
    inputs to the outcomes. ``format_version`` identifies the layout and changes
    when a key is renamed, removed, or reinterpreted.
    """
    failed_builds = build_failures or {}
    cannot_run = unrunnable or {}
    saved = saved_inputs or SavedInputs()
    records = []
    for implementation in implementations:
        record = _implementation_description(implementation)
        if implementation.name in failed_builds or implementation.name in cannot_run:
            record.update(
                build_failure=failed_builds.get(implementation.name),
                cannot_run=cannot_run.get(implementation.name),
                summary={"passed": 0, "failed": 0, "errors": 0},
                outcomes=[],
            )
        else:
            record.update(_tested_implementation_record(report, implementation.name, saved))
        records.append(record)
    return {
        "report": "test",
        "format_version": TEST_FORMAT_VERSION,
        "problem": report.problem_name,
        "passed": report.passed and not failed_builds and not cannot_run,
        "settings": _test_settings_record(report, plan),
        "cases": [_case_record(case) for case in report.cases],
        "implementations": records,
        "host": _host_record(),
        "metadata": _metadata_record(),
    }


def _test_settings_record(report: TestReport, plan: CasePlan | None) -> dict[str, Any]:
    settings = report.settings
    return {
        "cases": "explicit" if plan is None else "planned",
        "seed": None if plan is None else plan.seed,
        "random_cases": None if plan is None else plan.random_case_count,
        "maximum_size": None if plan is None else plan.maximum_size,
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


def _host_record() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version,
    }


def _metadata_record() -> dict[str, Any]:
    return {
        "algorithm_playground_version": package_version,
        "generated_at": datetime.datetime.now(tz=datetime.UTC).isoformat(),
    }


def _case_record(case: Case[Any]) -> dict[str, Any]:
    origin = case.origin
    if isinstance(origin, FixtureOrigin):
        return {"identifier": case.identifier, "kind": "fixture", "fixture": origin.name}
    if isinstance(origin, GeneratedOrigin):
        return {
            "identifier": case.identifier,
            "kind": "generated",
            "distribution": origin.generator_name,
            "size": origin.size,
            "seed": origin.seed,
        }
    return {"identifier": case.identifier, "kind": "shrunk"}


def _tested_implementation_record(
    report: TestReport, name: str, saved: SavedInputs
) -> dict[str, Any]:
    outcomes = report.outcomes_for(name)
    return {
        "build_failure": None,
        "cannot_run": None,
        "summary": {
            "passed": sum(outcome.status is CaseStatus.PASSED for outcome in outcomes),
            "failed": sum(outcome.status is CaseStatus.FAILED for outcome in outcomes),
            "errors": sum(outcome.status is CaseStatus.ERROR for outcome in outcomes),
        },
        "outcomes": [_outcome_record(outcome, saved) for outcome in outcomes],
    }


def _outcome_record(outcome: CaseOutcome, saved: SavedInputs) -> dict[str, Any]:
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


def _path_or_none(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _detail_record(detail: FailureDetail | None) -> dict[str, Any] | None:
    if detail is None:
        return None
    return {
        "input": detail.input_text,
        "expected": detail.expected_text,
        "actual": detail.actual_text,
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


def _implementation_description(implementation: Implementation) -> dict[str, Any]:
    """Describe how an implementation is run, with a fingerprint of the files it names."""
    working_directory = implementation.working_directory
    return {
        "name": implementation.name,
        "command": list(implementation.command),
        "working_directory": str(working_directory) if working_directory is not None else None,
        "inherit_environment": implementation.inherit_environment,
        "timeout_seconds": implementation.timeout_seconds,
        "files": [
            {"path": str(path), "sha256": _sha256_or_none(path)}
            for path in implementation.referenced_files()
        ],
    }


def _implementation_record(
    benchmark: ImplementationBenchmark, distributions: tuple[str, ...]
) -> dict[str, Any]:
    return {
        **_implementation_description(benchmark.implementation),
        "failures": [_failure_record(failure) for failure in benchmark.failures],
        "startup": _summary_fields(benchmark.startup) if benchmark.startup is not None else None,
        "results": [_measurement_record(measurement) for measurement in benchmark.measurements],
        "time_growth": {
            name: _growth_record(
                benchmark.growth(name), reliable=benchmark.growth_is_reliable(name)
            )
            for name in distributions
        },
        "operation_growth": {
            name: {
                operation: _growth_record(growth)
                for operation, growth in benchmark.operation_growth(name).items()
            }
            for name in distributions
        },
    }


def _growth_record(growth: Growth | None, *, reliable: bool | None = None) -> dict[str, Any] | None:
    if growth is None:
        return None
    record: dict[str, Any] = {"exponent": growth.exponent, "class": growth.growth_class}
    if reliable is not None:
        record["reliable"] = reliable
    return record


def _failure_record(failure: BenchmarkFailure) -> dict[str, Any]:
    return {
        "stage": failure.stage.value,
        "distribution": failure.distribution,
        "size": failure.size,
        "message": failure.message,
    }


def _measurement_record(measurement: SizeMeasurement) -> dict[str, Any]:
    # The summary fields describe the reported samples (startup subtracted when
    # requested, sorted); raw_samples_seconds holds the unadjusted wall times in run order.
    return {
        "distribution": measurement.distribution,
        "size": measurement.size,
        "case_identifier": measurement.case_identifier,
        "operation_counts": (
            None if measurement.operation_counts is None else dict(measurement.operation_counts)
        ),
        "operation_issue": (
            None
            if measurement.operation_issue is None
            else {
                "kind": measurement.operation_issue.kind.value,
                "message": measurement.operation_issue.message,
            }
        ),
        **_summary_fields(measurement.summary),
        "raw_samples_seconds": list(measurement.raw_samples),
    }


def _summary_fields(summary: TimingSummary) -> dict[str, Any]:
    return {
        "samples_seconds": list(summary.samples),
        "minimum_seconds": summary.minimum,
        "median_seconds": summary.median,
        "mean_seconds": summary.mean,
        "standard_deviation_seconds": summary.standard_deviation,
    }
