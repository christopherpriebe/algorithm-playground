"""Tests for the outcomes, progress, and report of the test engine."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from typing_extensions import override

from algorithm_playground.core import (
    Case,
    CaseOutcome,
    CasePhase,
    CaseProgress,
    CaseStatus,
    FixtureOrigin,
    Implementation,
    Problem,
    RunnerLike,
    ShrinkOptions,
    TemporaryFilePolicy,
    TestReport,
    TestRunOptions,
    resolve_case,
    run_tests,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    crash,
    drop_last_above_five,
    sort_correctly,
)

LARGE_GENERATED = "generated:uniform:size=12:seed=5"


SMALL_GENERATED = "generated:uniform:size=4:seed=6"


class UnwritableInputProblem(SortingProblem):
    """Sorting whose input hook raises."""

    @override
    def serialize_input(self, data: list[int], path: Path) -> None:
        message = "disk on fire"
        raise RuntimeError(message)


class IterationCountingTuple(tuple[CaseOutcome, ...]):
    """A tuple of outcomes that counts how often it is iterated."""

    __slots__ = ()

    iterations: ClassVar[int] = 0

    @override
    def __iter__(self) -> Iterator[CaseOutcome]:
        IterationCountingTuple.iterations += 1
        return super().__iter__()


def resolve_cases(*identifiers: str) -> list[Case[Any]]:
    """Resolve case identifiers of the sorting problem into cases."""
    problem = SortingProblem()
    return [resolve_case(problem, identifier) for identifier in identifiers]


def run_with_fake_runners(
    behaviors: dict[str, Any],
    identifiers: list[str],
    *,
    options: TestRunOptions | None = None,
    on_progress: Callable[[CaseProgress], None] | None = None,
) -> tuple[TestReport, FakeRunners]:
    """Test fake implementations on cases and return the report with the runners it used."""
    runners = FakeRunners(behaviors)
    report = run_tests(
        SortingProblem(),
        build_named_implementations(*behaviors),
        resolve_cases(*identifiers),
        options=options,
        runner_factory=runners,
        on_progress=on_progress,
    )
    return report, runners


@pytest.fixture
def mixed_report() -> TestReport:
    """The report of a correct and a wrong implementation on three cases."""
    report, _ = run_with_fake_runners(
        {"good": sort_correctly, "bad": drop_last_above_five},
        ["fixture:empty", SMALL_GENERATED, LARGE_GENERATED],
    )
    return report


def test_correct_implementation_passes_every_case() -> None:
    """Test a correct implementation passes every case with no message and no detail."""
    report, _ = run_with_fake_runners(
        {"a": sort_correctly}, ["fixture:empty", LARGE_GENERATED]
    )

    assert report.has_passed
    assert report.failures() == ()
    assert all(outcome.status is CaseStatus.PASSED for outcome in report.outcomes)
    assert all(
        outcome.message == "" and outcome.detail is None for outcome in report.outcomes
    )


def test_the_report_names_the_problem_the_implementations_and_the_cases() -> None:
    """Test the report records the problem, the implementation names and the case identifiers."""
    report, _ = run_with_fake_runners(
        {"a": sort_correctly}, ["fixture:empty", LARGE_GENERATED]
    )

    assert report.problem_name == "sorting"
    assert report.implementation_names == ("a",)
    assert report.case_identifiers == ("fixture:empty", LARGE_GENERATED)


def test_a_wrong_implementation_does_not_make_the_report_pass(
    mixed_report: TestReport,
) -> None:
    """Test a report with a failing outcome has not passed."""
    assert not mixed_report.has_passed


def test_a_wrong_implementation_does_not_affect_the_correct_one(
    mixed_report: TestReport,
) -> None:
    """Test the correct implementation passes every case next to a wrong one."""
    statuses = [outcome.status for outcome in mixed_report.outcomes_for("good")]

    assert statuses == [CaseStatus.PASSED] * 3


def test_a_wrong_implementation_fails_only_the_cases_it_gets_wrong(
    mixed_report: TestReport,
) -> None:
    """Test the wrong implementation fails only the case that has more than five values."""
    statuses = [outcome.status for outcome in mixed_report.outcomes_for("bad")]

    assert statuses == [CaseStatus.PASSED, CaseStatus.PASSED, CaseStatus.FAILED]


def test_a_failed_outcome_carries_the_message_of_the_verifier(
    mixed_report: TestReport,
) -> None:
    """Test a failed outcome holds the message of the verifier."""
    failed = mixed_report.outcome(LARGE_GENERATED, "bad")

    assert "Output length 11 does not match input length 12" in failed.message


def test_outcomes_are_ordered_by_case_then_implementation() -> None:
    """Test outcomes list every implementation for one case before the next case."""
    report, _ = run_with_fake_runners(
        {"a": sort_correctly, "b": sort_correctly},
        ["fixture:single", SMALL_GENERATED],
    )

    pairs = [
        (outcome.case_identifier, outcome.implementation_name)
        for outcome in report.outcomes
    ]

    assert pairs == [
        ("fixture:single", "a"),
        ("fixture:single", "b"),
        (SMALL_GENERATED, "a"),
        (SMALL_GENERATED, "b"),
    ]


def test_failures_lists_only_non_passing_outcomes() -> None:
    """Test the failures of a report are exactly the outcomes that did not pass."""
    report, _ = run_with_fake_runners(
        {"good": sort_correctly, "bad": drop_last_above_five},
        ["fixture:empty", LARGE_GENERATED],
    )

    failures = [
        (outcome.implementation_name, outcome.case_identifier)
        for outcome in report.failures()
    ]

    assert failures == [("bad", LARGE_GENERATED)]


def test_a_runner_error_is_an_error_outcome_with_the_full_message() -> None:
    """Test a runner error gives an error outcome that holds the whole error message."""
    report, _ = run_with_fake_runners({"crash": crash}, ["fixture:single"])

    outcome = report.outcomes[0]

    assert outcome.status is CaseStatus.ERROR
    assert "exited with code 3" in outcome.message
    assert "kaboom" in outcome.message


def test_an_exception_in_verification_is_an_error_outcome(
    exploding_problem: SortingProblem,
) -> None:
    """Test a verifier that raises gives an error outcome with the exception and the output."""
    report = run_tests(
        exploding_problem,
        build_named_implementations("a"),
        resolve_cases("fixture:single"),
        runner_factory=FakeRunners({"a": sort_correctly}),
    )

    outcome = report.outcomes[0]

    assert outcome.status is CaseStatus.ERROR
    assert outcome.message == "Verification raised RuntimeError: verifier exploded"
    assert outcome.detail is not None
    assert outcome.detail.actual_text == "[42]"


def test_the_factory_receives_the_problem_and_each_implementation() -> None:
    """Test the runner factory is called once per implementation with the problem."""
    received: list[tuple[str, str]] = []
    runners = FakeRunners({"a": sort_correctly})

    def factory(
        problem: Problem[Any, Any, Any], implementation: Implementation
    ) -> RunnerLike:
        received.append((problem.name, implementation.name))
        return runners(problem, implementation)

    run_tests(
        SortingProblem(),
        build_named_implementations("a"),
        resolve_cases("fixture:empty"),
        runner_factory=factory,
    )

    assert received == [("sorting", "a")]


def test_rejects_duplicate_case_identifiers() -> None:
    """Test two cases with the same identifier raise a ValueError."""
    with pytest.raises(ValueError, match="unique"):
        run_with_fake_runners({"a": sort_correctly}, ["fixture:empty", "fixture:empty"])


def test_rejects_no_cases() -> None:
    """Test an empty list of cases raises a ValueError."""
    with pytest.raises(ValueError, match="At least one case"):
        run_with_fake_runners({"a": sort_correctly}, [])


def test_rejects_duplicate_implementation_names() -> None:
    """Test two implementations with the same name raise a ValueError."""
    with pytest.raises(ValueError, match="Duplicate implementation name"):
        run_tests(
            SortingProblem(),
            build_named_implementations("a", "a"),
            resolve_cases("fixture:empty"),
        )


def test_rejects_an_empty_implementation_list() -> None:
    """Test an empty list of implementations raises a ValueError."""
    with pytest.raises(ValueError, match="At least one implementation"):
        run_tests(SortingProblem(), [], resolve_cases("fixture:empty"))


def test_events_follow_each_run_and_end_with_the_completed_outcome() -> None:
    """Test each run reports that it is running and then that it completed with its outcome."""
    events: list[CaseProgress] = []

    report, _ = run_with_fake_runners(
        {"a": sort_correctly, "b": sort_correctly},
        ["fixture:empty"],
        on_progress=events.append,
    )

    assert [(event.implementation_name, event.phase) for event in events] == [
        ("a", CasePhase.RUNNING),
        ("a", CasePhase.COMPLETED),
        ("b", CasePhase.RUNNING),
        ("b", CasePhase.COMPLETED),
    ]
    assert {event.case_identifier for event in events} == {"fixture:empty"}
    assert [
        event.outcome for event in events if event.phase is CasePhase.COMPLETED
    ] == list(report.outcomes)
    assert all(
        event.outcome is None
        for event in events
        if event.phase is not CasePhase.COMPLETED
    )


def test_shrinking_is_announced_before_the_outcome_completes() -> None:
    """Test a failing generated case reports a shrinking phase between running and completion."""
    events: list[CaseProgress] = []

    run_with_fake_runners(
        {"bad": drop_last_above_five}, [LARGE_GENERATED], on_progress=events.append
    )

    assert [event.phase for event in events] == [
        CasePhase.RUNNING,
        CasePhase.SHRINKING,
        CasePhase.COMPLETED,
    ]
    completed = events[-1].outcome
    assert completed is not None
    assert completed.shrunk is not None


@pytest.fixture(scope="module")
def correct_and_unsorted_report(
    python_sort_executable: Path, unsorted_output_executable: Path
) -> TestReport:
    """The report of a correct and an unsorted implementation run as real processes."""
    implementations = [
        Implementation.from_executable(python_sort_executable, name="correct"),
        Implementation.from_executable(unsorted_output_executable, name="unsorted"),
    ]
    return run_tests(
        SortingProblem(),
        implementations,
        resolve_cases("fixture:single", "fixture:two_unsorted"),
    )


def test_a_correct_implementation_passes(
    correct_and_unsorted_report: TestReport,
) -> None:
    """Test a real correct implementation passes every case."""
    statuses = [
        outcome.status
        for outcome in correct_and_unsorted_report.outcomes_for("correct")
    ]

    assert statuses == [CaseStatus.PASSED] * 2


def test_a_wrong_implementation_fails_only_the_unsorted_case(
    correct_and_unsorted_report: TestReport,
) -> None:
    """Test a real implementation that copies its input fails only the unsorted input."""
    statuses = [
        outcome.status
        for outcome in correct_and_unsorted_report.outcomes_for("unsorted")
    ]

    assert statuses == [CaseStatus.PASSED, CaseStatus.FAILED]


def test_a_wrong_implementation_has_a_message_and_the_actual_output(
    correct_and_unsorted_report: TestReport,
) -> None:
    """Test the failure of a real implementation holds the message and the output it wrote."""
    failed = correct_and_unsorted_report.outcome("fixture:two_unsorted", "unsorted")

    assert "not sorted ascending" in failed.message
    assert failed.detail is not None
    assert failed.detail.actual_text == "[2, 1]"


def test_shrinking_runs_the_real_implementation(
    unsorted_output_executable: Path,
) -> None:
    """Test a failing generated case is shrunk by running the real implementation."""
    unsorted = Implementation.from_executable(
        unsorted_output_executable, name="unsorted"
    )

    report = run_tests(
        SortingProblem(),
        [unsorted],
        resolve_cases("generated:uniform:size=4:seed=3"),
    )

    shrunk = report.outcomes[0].shrunk
    assert shrunk is not None
    assert len(shrunk.case.input_data) == 2


def test_a_crash_is_an_error_with_the_standard_error(crashing_executable: Path) -> None:
    """Test an implementation that crashes gives an error outcome holding its standard error."""
    crashing = Implementation.from_executable(crashing_executable, name="crashing")

    report = run_tests(SortingProblem(), [crashing], resolve_cases("fixture:single"))

    outcome = report.outcomes[0]
    assert outcome.status is CaseStatus.ERROR
    assert "exited with code 3" in outcome.message
    assert "kaboom" in outcome.message


def test_a_missing_command_is_an_error_not_an_exception() -> None:
    """Test a command that does not exist gives an error outcome instead of raising."""
    ghost = Implementation(
        name="ghost", command=("algorithm-playground-no-such-command",)
    )

    report = run_tests(SortingProblem(), [ghost], resolve_cases("fixture:single"))

    assert report.outcomes[0].status is CaseStatus.ERROR


@pytest.mark.usefixtures("scratch_root")
def test_kept_temporary_files_are_named_in_error_messages(
    crashing_executable: Path,
) -> None:
    """Test the message of an error names the directory of the kept temporary files."""
    crashing = Implementation.from_executable(crashing_executable, name="crashing")

    report = run_tests(
        SortingProblem(),
        [crashing],
        resolve_cases("fixture:single"),
        options=TestRunOptions(temporary_files=TemporaryFilePolicy.KEEP),
    )

    assert "Temporary files were kept in " in report.outcomes[0].message


@pytest.mark.usefixtures("scratch_root")
def test_kept_temporary_files_are_named_in_failure_messages(
    unsorted_output_executable: Path,
) -> None:
    """Test the message of a failure ends with the directory of the kept temporary files."""
    unsorted = Implementation.from_executable(
        unsorted_output_executable, name="unsorted"
    )

    report = run_tests(
        SortingProblem(),
        [unsorted],
        resolve_cases("fixture:reverse_sorted"),
        options=TestRunOptions(temporary_files=TemporaryFilePolicy.KEEP),
    )

    message = report.outcomes[0].message
    assert "not sorted ascending" in message
    assert message.splitlines()[-1].startswith("Temporary files were kept in ")


def test_messages_do_not_mention_temporary_files_that_were_deleted(
    crashing_executable: Path,
) -> None:
    """Test the message of an error mentions no temporary files when they were deleted."""
    crashing = Implementation.from_executable(crashing_executable, name="crashing")

    report = run_tests(SortingProblem(), [crashing], resolve_cases("fixture:single"))

    assert "Temporary files" not in report.outcomes[0].message


def test_a_problem_that_cannot_write_an_input_gives_an_error_naming_the_hook(
    python_sort_executable: Path,
) -> None:
    """Test an input hook that raises gives an error outcome naming the hook and the cause."""
    implementation = Implementation.from_executable(
        python_sort_executable, name="sorter"
    )

    report = run_tests(
        UnwritableInputProblem(), [implementation], resolve_cases("fixture:single")
    )

    outcome = report.outcomes[0]
    assert outcome.status is CaseStatus.ERROR
    assert "serialize_input" in outcome.message
    assert "RuntimeError: disk on fire" in outcome.message
    assert outcome.shrunk is None


@pytest.fixture
def sample_report() -> TestReport:
    """A report of one passing and one failing implementation on a single fixture case."""
    case = Case(FixtureOrigin("case"), [])
    outcomes = (
        CaseOutcome(case, "a", CaseStatus.PASSED, ""),
        CaseOutcome(case, "b", CaseStatus.FAILED, "wrong"),
    )
    return TestReport("sorting", ("a", "b"), (case,), outcomes)


def test_outcome_lookup(sample_report: TestReport) -> None:
    """Test an outcome is found by case identifier and implementation name."""
    outcome = sample_report.outcome("fixture:case", "b")

    assert outcome.message == "wrong"


def test_lookups_do_not_scan_the_outcomes() -> None:
    """Test looking up outcomes repeatedly iterates over the outcomes at most once."""
    case = Case(FixtureOrigin("case"), [])
    outcomes = IterationCountingTuple(
        CaseOutcome(case, name, CaseStatus.PASSED, "") for name in ("a", "b", "c")
    )
    IterationCountingTuple.iterations = 0
    report = TestReport("sorting", ("a", "b", "c"), (case,), outcomes)

    for _ in range(100):
        assert report.outcome("fixture:case", "c").implementation_name == "c"

    assert IterationCountingTuple.iterations <= 1


def test_the_settings_of_a_run_are_recorded() -> None:
    """Test the report records the timeout and the shrink limits of the run."""
    report, _ = run_with_fake_runners(
        {"a": sort_correctly},
        ["fixture:single"],
        options=TestRunOptions(
            timeout_seconds=12.5,
            shrinking=ShrinkOptions(
                maximum_shrunk_cases=4, maximum_runs=30, time_budget_seconds=7.0
            ),
        ),
    )

    settings = report.settings

    assert (
        settings.timeout_seconds,
        settings.shrink,
        settings.maximum_shrunk_cases,
    ) == (
        12.5,
        True,
        4,
    )
    assert (settings.maximum_shrink_runs, settings.shrink_time_budget_seconds) == (
        30,
        7.0,
    )


def test_a_run_without_shrinking_records_that_shrinking_was_off() -> None:
    """Test the report records that shrinking was off along with the timeout."""
    report, _ = run_with_fake_runners(
        {"a": sort_correctly},
        ["fixture:single"],
        options=TestRunOptions(timeout_seconds=12.5, shrinking=None),
    )

    assert (report.settings.timeout_seconds, report.settings.shrink) == (
        12.5,
        False,
    )


def test_outcome_lookup_of_unknown_pair_raises(sample_report: TestReport) -> None:
    """Test looking up a pair without an outcome raises a KeyError naming the pair."""
    with pytest.raises(
        KeyError, match=r"No outcome for case 'fixture:case' and implementation 'c'"
    ):
        sample_report.outcome("fixture:case", "c")


def test_outcomes_for_one_implementation(sample_report: TestReport) -> None:
    """Test the outcomes of one implementation are selected by name."""
    outcomes = sample_report.outcomes_for("a")

    assert [outcome.status for outcome in outcomes] == [CaseStatus.PASSED]


def test_case_identifiers_follow_the_cases(sample_report: TestReport) -> None:
    """Test the case identifiers of a report are those of its cases."""
    assert sample_report.case_identifiers == ("fixture:case",)


def test_pytest_does_not_collect_the_report_class() -> None:
    """Test the report class is marked so that pytest does not collect it as a test class."""
    assert TestReport.__test__ is False
