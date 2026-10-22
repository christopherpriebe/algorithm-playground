"""Tests for the JSON report of a test run."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from algorithm_playground.core import (
    TEST_FORMAT_VERSION,
    CasePlan,
    Implementation,
    ShrinkOptions,
    Size,
    TestReport,
    TestRunOptions,
    convert_correctness_report_to_json,
    resolve_case,
    run_tests,
    save_failing_inputs,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    drop_last_above_five,
    sort_correctly,
)

PLAN = CasePlan(
    random_case_count=1,
    maximum_size=Size(size=12),
    generator_names=("uniform", "sorted"),
    seed=4,
)


GENERATED_CASE = "generated:uniform:size=12:seed=5"


@pytest.fixture(scope="module")
def implementations(tmp_path_factory: pytest.TempPathFactory) -> list[Implementation]:
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


@pytest.fixture(scope="module")
def testing_document(implementations: list[Implementation]) -> dict[str, Any]:
    """The report of testing the good and bad implementations; the third failed to build."""
    problem = SortingProblem()
    cases = [
        resolve_case(problem, identifier)
        for identifier in ("fixture:single", GENERATED_CASE)
    ]
    report = run_tests(
        problem,
        implementations[:2],
        cases,
        options=TestRunOptions(
            timeout_seconds=7.0, shrinking=ShrinkOptions(time_budget_seconds=12.0)
        ),
        runner_factory=FakeRunners(
            {"good": sort_correctly, "bad": drop_last_above_five}
        ),
    )
    document = convert_correctness_report_to_json(
        report,
        implementations=implementations,
        plan=PLAN,
        build_failures={"unbuilt": "make: error"},
    )
    return json.loads(json.dumps(document))


@pytest.fixture
def single_good_report() -> TestReport:
    """The report of the good implementation passing one fixture."""
    problem = SortingProblem()
    return run_tests(
        problem,
        build_named_implementations("good"),
        [resolve_case(problem, "fixture:single")],
        runner_factory=FakeRunners({"good": sort_correctly}),
    )


def test_the_correctness_report_has_exactly_the_documented_top_level_keys(
    testing_document: dict[str, Any],
) -> None:
    """Test the document has exactly the documented top-level keys."""
    assert set(testing_document) == {
        "report",
        "format_version",
        "problem",
        "passed",
        "settings",
        "dimensions",
        "cases",
        "implementations",
        "host",
        "metadata",
    }


def test_the_correctness_report_names_its_kind_version_and_problem(
    testing_document: dict[str, Any],
) -> None:
    """Test the document names its kind, its format version and the problem."""
    assert testing_document["report"] == "test"
    assert testing_document["format_version"] == TEST_FORMAT_VERSION == 3
    assert testing_document["problem"] == "sorting"


def test_the_settings_record_the_plan_the_shrink_limits_and_the_timeout(
    testing_document: dict[str, Any],
) -> None:
    """Test the settings hold the case plan, the shrink limits and the run timeout."""
    assert testing_document["settings"] == {
        "cases": "planned",
        "seed": 4,
        "random_cases": 1,
        "maximum_size": {"size": 12},
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
def explicit_settings(implementations: list[Implementation]) -> dict[str, Any]:
    """The settings of a report for one explicit fixture run without shrinking."""
    problem = SortingProblem()
    report = run_tests(
        problem,
        implementations[:1],
        [resolve_case(problem, "fixture:single")],
        options=TestRunOptions(shrinking=None),
        runner_factory=FakeRunners({"good": sort_correctly}),
    )
    return convert_correctness_report_to_json(
        report, implementations=implementations[:1]
    )["settings"]


def test_explicit_cases_have_no_plan(explicit_settings: dict[str, Any]) -> None:
    """Test a run of explicit cases records the plan settings as null."""
    assert explicit_settings["cases"] == "explicit"
    assert [
        explicit_settings[key] for key in ("seed", "random_cases", "maximum_size")
    ] == [None] * 3
    assert explicit_settings["distributions"] is None
    assert explicit_settings["include_fixtures"] is None


def test_disabled_shrinking_is_recorded(explicit_settings: dict[str, Any]) -> None:
    """Test a run without shrinking records the shrink setting as disabled."""
    assert explicit_settings["shrink"]["enabled"] is False


def test_an_implementation_is_described_like_in_the_benchmark_report(
    testing_document: dict[str, Any], implementations: list[Implementation]
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
    testing_document: dict[str, Any],
) -> None:
    """Test an implementation that runs a missing command lists its command and no files."""
    _, bad, unbuilt = testing_document["implementations"]

    assert bad["command"] == ["./bad"]
    assert bad["files"] == []
    assert unbuilt["command"] == ["./unbuilt"]


def test_a_report_without_build_failures_has_passed(
    single_good_report: TestReport,
) -> None:
    """Test a report in which every run passed and nothing failed to build has passed."""
    implementations = build_named_implementations("good")

    document = convert_correctness_report_to_json(
        single_good_report, implementations=implementations
    )

    assert document["passed"] is True


def test_a_build_failure_means_not_passed_even_when_every_run_passed(
    single_good_report: TestReport,
) -> None:
    """Test an implementation that failed to build makes the report not passed."""
    implementations = build_named_implementations("good", "x")

    document = convert_correctness_report_to_json(
        single_good_report,
        implementations=implementations,
        build_failures={"x": "boom"},
    )

    assert document["passed"] is False


def test_an_implementation_that_cannot_run_is_listed_with_the_reason_and_no_outcomes(
    single_good_report: TestReport,
) -> None:
    """Test an unrunnable implementation records why, and has no build failure or outcomes."""
    document = convert_correctness_report_to_json(
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
    single_good_report: TestReport,
) -> None:
    """Test an implementation that cannot run makes the report not passed."""
    document = convert_correctness_report_to_json(
        single_good_report,
        implementations=build_named_implementations("good", "missing"),
        unrunnable={"missing": "command not found: ./missing"},
    )

    assert document["passed"] is False


def test_saved_inputs_are_recorded_on_the_failing_outcomes(
    tmp_path: Path, implementations: list[Implementation]
) -> None:
    """Test a failing outcome holds the paths of its saved input and its shrunk input."""
    problem = SortingProblem()
    report = run_tests(
        problem,
        implementations[:2],
        [resolve_case(problem, GENERATED_CASE)],
        runner_factory=FakeRunners(
            {"good": sort_correctly, "bad": drop_last_above_five}
        ),
    )
    saved = save_failing_inputs(problem, report, tmp_path / "failures")

    document = convert_correctness_report_to_json(
        report, implementations=implementations[:2], saved_inputs=saved
    )

    (outcome,) = document["implementations"][1]["outcomes"]
    assert outcome["saved_input"] == str(saved.inputs[("bad", outcome["case"])])
    assert outcome["saved_shrunk_input"] == str(
        saved.shrunk_inputs[("bad", outcome["case"])]
    )


def test_a_passing_outcome_has_no_saved_input(
    tmp_path: Path, implementations: list[Implementation]
) -> None:
    """Test an outcome that passed has no saved input even when others were saved."""
    problem = SortingProblem()
    report = run_tests(
        problem,
        implementations[:2],
        [resolve_case(problem, GENERATED_CASE)],
        runner_factory=FakeRunners(
            {"good": sort_correctly, "bad": drop_last_above_five}
        ),
    )
    saved = save_failing_inputs(problem, report, tmp_path / "failures")

    document = convert_correctness_report_to_json(
        report, implementations=implementations[:2], saved_inputs=saved
    )

    good = document["implementations"][0]
    assert good["outcomes"][0]["saved_input"] is None


def test_cases_describe_their_origin(testing_document: dict[str, Any]) -> None:
    """Test each case names its kind, and a generated case its distribution, size and seed."""
    assert [case["kind"] for case in testing_document["cases"]] == [
        "fixture",
        "generated",
    ]
    assert testing_document["cases"][1] == {
        "identifier": GENERATED_CASE,
        "kind": "generated",
        "distribution": "uniform",
        "size": {"size": 12},
        "seed": 5,
    }


def test_implementations_have_summaries_in_run_order(
    testing_document: dict[str, Any],
) -> None:
    """Test each implementation summarizes how many cases passed, failed and errored."""
    good, bad, unbuilt = testing_document["implementations"]

    assert (good["name"], good["summary"]) == (
        "good",
        {"passed": 2, "failed": 0, "errors": 0},
    )
    assert bad["summary"] == {"passed": 1, "failed": 1, "errors": 0}
    assert unbuilt["summary"] == {"passed": 0, "failed": 0, "errors": 0}


def test_outcomes_follow_the_case_order(testing_document: dict[str, Any]) -> None:
    """Test the outcomes of an implementation are listed in the order of the cases."""
    bad = testing_document["implementations"][1]

    assert [outcome["case"] for outcome in bad["outcomes"]] == [
        "fixture:single",
        GENERATED_CASE,
    ]


def test_a_build_failure_is_recorded_with_its_message_and_no_outcomes(
    testing_document: dict[str, Any],
) -> None:
    """Test an implementation that failed to build records the message and has no outcomes."""
    good, _, unbuilt = testing_document["implementations"]

    assert good["build_failure"] is None
    assert unbuilt["build_failure"] == "make: error"
    assert unbuilt["outcomes"] == []


def test_a_passing_outcome_has_no_failure_detail(
    testing_document: dict[str, Any],
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
    testing_document: dict[str, Any],
) -> None:
    """Test a failed outcome holds its status, category, message and the failing input."""
    _, failing = testing_document["implementations"][1]["outcomes"]

    assert failing["status"] == "failed"
    assert failing["category"] == "wrong length"
    assert failing["message"] == "Output length 11 does not match input length 12"
    assert set(failing["failure"]) == {"input", "expected", "actual"}


def test_a_failing_outcome_carries_the_shrunk_input(
    testing_document: dict[str, Any],
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


def test_the_report_lists_the_dimensions_of_the_problem(
    testing_document: dict[str, Any],
) -> None:
    """Test the report names the dimensions of the problem with their minimums."""
    assert testing_document["dimensions"] == [{"name": "size", "minimum": 0}]


def test_a_plan_without_a_maximum_records_the_default_maximum(
    single_good_report: TestReport,
) -> None:
    """Test a plan that names no maximum size records the default maximum of each dimension."""
    document = convert_correctness_report_to_json(
        single_good_report,
        implementations=build_named_implementations("good"),
        plan=CasePlan(),
    )

    assert document["settings"]["maximum_size"] == {"size": 100}
