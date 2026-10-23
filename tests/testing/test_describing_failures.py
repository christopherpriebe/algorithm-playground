"""Tests for how inputs, outputs, errors, and failures are described."""

import re
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from hypothesis import given, strategies
from typing_extensions import override

from algorithm_playground.core import (
    Case,
    CaseProgress,
    CaseStatus,
    TestReport,
    TestRunOptions,
    VerificationResult,
    describe_error,
    describe_sequence,
    resolve_case,
    run_tests,
    truncate_text,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    crash,
    drop_last_above_five,
    sort_correctly,
)


class ReadCountingList(list[int]):
    """A list that counts how often its items are read and refuses to be iterated."""

    def __init__(self, values: range) -> None:
        super().__init__(values)
        self.reads = 0

    @override
    def __getitem__(self, position: int) -> int:  # ty: ignore[invalid-method-override]  list stand-in that counts item reads, so the signature differs on purpose
        self.reads += 1
        return super().__getitem__(position)

    @override
    def __iter__(self) -> Iterator[int]:
        message = "the whole sequence must not be iterated"
        raise AssertionError(message)


LARGE_GENERATED = "generated:uniform:size=12:seed=5"


NO_SHRINKING = TestRunOptions(shrinking=None)


class UnknownExpectedProblem(SortingProblem):
    """Sorting without an expected output, as for a problem with many valid answers."""

    @override
    def expected_output(self, input_data: list[int]) -> list[int] | None:  # ty: ignore[invalid-method-override]  the test double returns None to model a problem without a reference output
        return None


class ExplodingHooksProblem(SortingProblem):
    """Sorting whose describe and shrink hooks raise."""

    @override
    def describe_input(self, input_data: list[int], *, limit: int) -> str:
        message = "cannot describe"
        raise RuntimeError(message)

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        message = "shrink exploded"
        raise RuntimeError(message)


class RecordingDescriptionsProblem(SortingProblem):
    """Sorting that records the focus each describe_output call received."""

    def __init__(self) -> None:
        self.focuses: list[object] = []

    @override
    def describe_output(
        self, output: list[int], *, limit: int, focus: object | None = None
    ) -> str:
        self.focuses.append(focus)
        return super().describe_output(output, limit=limit, focus=focus)


EDGE_FOCUS = ("vertex 2", "vertex 5")


class EdgeFocusProblem(RecordingDescriptionsProblem):
    """Sorting whose verifier names a failure by something other than a position."""

    @override
    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        verification = super().verify(input_data, output)
        if verification.passed:
            return verification
        return VerificationResult(False, message=verification.message, focus=EDGE_FOCUS)


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


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (KeyError("section"), "KeyError: 'section'"),
        (ValueError("bad value"), "ValueError: bad value"),
    ],
    ids=["key-error", "value-error"],
)
def test_names_the_type_and_the_message_of_the_error(
    error: Exception, expected: str
) -> None:
    """Test the description holds the type name of the error and its message."""
    assert describe_error(error) == expected


def test_an_error_without_a_message_still_names_its_type() -> None:
    """Test an error with no message is described by its type alone."""
    assert describe_error(RuntimeError()) == "RuntimeError: "


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("short", 10, "short"),
        ("a longer text", 8, "a lon..."),
        ("abcdef", 3, "abc"),
        ("abcdef", 0, ""),
    ],
    ids=["fits", "cut-with-marker", "limit-below-marker", "zero-limit"],
)
def test_truncate_text_cuts_to_the_limit_and_marks_the_cut(
    text: str, limit: int, expected: str
) -> None:
    """Test text longer than the limit is cut to the limit and ends with a marker."""
    assert truncate_text(text, limit) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([3, 1, 2], "[3, 1, 2]"),
        ([], "[]"),
        (("a", "b"), "['a', 'b']"),
    ],
    ids=["integers", "empty", "strings"],
)
def test_a_sequence_that_fits_is_shown_whole(
    values: Sequence[object], expected: str
) -> None:
    """Test a sequence that fits within the limit is written out in full."""
    assert describe_sequence(values, 100) == expected


def test_a_longer_one_shows_the_items_that_fit_and_the_count() -> None:
    """Test a sequence over the limit shows the leading items that fit and the total count."""
    text = describe_sequence(list(range(1000)), 40)

    assert text == "[0, 1, 2, 3, 4, 5, 6, ...] (1000 values)"
    assert len(text) <= 40


@pytest.mark.parametrize("limit", range(30, 200, 7))
def test_the_result_never_exceeds_the_limit(limit: int) -> None:
    """Test the description fits the limit, with or without a focus."""
    values = [123456789 * (index + 1) for index in range(50)]

    assert len(describe_sequence(values, limit)) <= limit
    assert len(describe_sequence(values, limit, focus=25)) <= limit


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (60, "[..., 499, 500, ...] (1000 values, indices 499 to 500 shown)"),
        (
            90,
            (
                "[..., 496, 497, 498, 499, 500, 501, 502, 503, ...] "
                "(1000 values, indices 496 to 503 shown)"
            ),
        ),
    ],
    ids=["narrow-limit", "wide-limit"],
)
def test_a_focus_shows_a_window_around_it_and_says_which_indices(
    limit: int, expected: str
) -> None:
    """Test a focus shows a window of items around it and names the indices shown."""
    assert describe_sequence(list(range(1000)), limit, focus=500) == expected


def test_a_window_that_reaches_the_start_has_no_leading_ellipsis() -> None:
    """Test a window that includes the first item starts the list without an ellipsis."""
    text = describe_sequence(list(range(1000)), 60, focus=2)

    assert text == "[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ...] (1000 values)"


def test_a_window_that_reaches_the_end_has_no_trailing_ellipsis() -> None:
    """Test a window that includes the last item ends the list without an ellipsis."""
    text = describe_sequence(list(range(1000)), 60, focus=999)

    assert text == "[..., 997, 998, 999] (1000 values, indices 997 to 999 shown)"


def test_a_single_index_is_named_as_one() -> None:
    """Test a window of one item says 'index' in the singular."""
    text = describe_sequence([10**9 + offset for offset in range(30)], 50, focus=29)

    assert text == "[..., 1000000029] (30 values, index 29 shown)"


@pytest.mark.parametrize(
    ("focus", "nearest_end"),
    [(-5, 0), (5000, 999)],
    ids=["before-the-start", "past-the-end"],
)
def test_a_focus_outside_the_sequence_is_moved_to_the_nearest_end(
    focus: int, nearest_end: int
) -> None:
    """Test a focus outside the sequence behaves like a focus on the nearest end."""
    values = list(range(1000))

    text = describe_sequence(values, 60, focus=focus)

    assert text == describe_sequence(values, 60, focus=nearest_end)


@pytest.mark.parametrize(
    ("values", "limit", "expected"),
    [([123456789012], 10, "[123456..."), (list(range(100)), 3, "[0,")],
    ids=["one-long-item", "tiny-limit"],
)
def test_a_limit_too_small_for_one_item_cuts_the_text(
    values: list[int], limit: int, expected: str
) -> None:
    """Test a limit that cannot hold even one item cuts the written text instead."""
    assert describe_sequence(values, limit) == expected


def test_a_sequence_that_fits_is_shown_whole_even_with_a_focus() -> None:
    """Test a focus changes nothing for a sequence that fits within the limit."""
    assert describe_sequence([1, 2, 3], 50, focus=1) == "[1, 2, 3]"


def test_a_huge_sequence_is_not_formatted_in_full() -> None:
    """Test describing a huge sequence reads only a few of its items."""
    values = ReadCountingList(range(1_000_000))

    describe_sequence(values, 60, focus=500_000)

    assert values.reads < 200


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("short", 10, "short"),
        ("exactly ten", 11, "exactly ten"),
        ("a longer text", 8, "a lon..."),
        ("abcdef", 3, "abc"),
        ("abcdef", 0, ""),
    ],
    ids=[
        "fits",
        "exactly-the-limit",
        "cut-with-marker",
        "limit-below-marker",
        "zero-limit",
    ],
)
def test_truncate_text_cuts_at_each_limit_and_marks_the_cut(
    text: str, limit: int, expected: str
) -> None:
    """Test text longer than the limit is cut to the limit and ends with a marker."""
    assert truncate_text(text, limit) == expected


def test_a_failure_carries_the_input_the_expected_and_the_actual_output() -> None:
    """Test a failure holds the description of the input, the expected and the actual output."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five}, [LARGE_GENERATED], options=NO_SHRINKING
    )
    problem = SortingProblem()
    data = resolve_case(problem, LARGE_GENERATED).input_data

    detail = report.outcomes[0].detail

    assert detail is not None
    assert detail.input_text == problem.describe_input(data, limit=300)
    assert detail.expected_text == problem.describe_output(sorted(data), limit=300)
    assert detail.actual_text == problem.describe_output(sorted(data)[:-1], limit=300)


def test_descriptions_are_shortened_to_the_limit() -> None:
    """Test a long input description is cut to the description limit."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five},
        [LARGE_GENERATED],
        options=TestRunOptions(shrinking=None, description_limit=40),
    )

    detail = report.outcomes[0].detail

    assert detail is not None
    assert "(12 values)" in detail.input_text
    assert len(detail.input_text) <= 40


def test_a_runner_error_has_no_actual_output() -> None:
    """Test a run that crashed has the input and the expected output but no actual output."""
    report, _ = run_with_fake_runners({"crash": crash}, ["fixture:two_unsorted"])

    detail = report.outcomes[0].detail

    assert detail is not None
    assert detail.input_text == "[2, 1]"
    assert detail.expected_text == "[1, 2]"
    assert detail.actual_text is None


def test_a_problem_without_expected_output_reports_none() -> None:
    """Test a problem that cannot name the expected output leaves it out of the detail."""
    report = run_tests(
        UnknownExpectedProblem(),
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        runner_factory=FakeRunners({"bad": drop_last_above_five}),
        options=NO_SHRINKING,
    )

    detail = report.outcomes[0].detail

    assert detail is not None
    assert detail.expected_text is None
    assert detail.actual_text is not None


def test_a_describe_hook_that_raises_does_not_break_the_report() -> None:
    """Test a describe hook that raises is replaced by a description of the error."""
    report = run_tests(
        ExplodingHooksProblem(),
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        runner_factory=FakeRunners({"bad": drop_last_above_five}),
    )

    detail = report.outcomes[0].detail

    assert detail is not None
    assert detail.input_text == "(could not describe: RuntimeError: cannot describe)"
    assert detail.actual_text is not None


def test_the_position_the_verifier_names_is_passed_to_the_describe_hook() -> None:
    """Test the describe hook receives the position of the first difference as its focus."""
    problem = RecordingDescriptionsProblem()

    run_tests(
        problem,
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        options=NO_SHRINKING,
        runner_factory=FakeRunners({"bad": drop_last_above_five}),
    )

    # The expected output and the actual output of the one failure, both at the
    # first difference (the missing last element).
    assert problem.focuses == [11, 11]


def test_a_failure_without_a_position_describes_the_outputs_without_one() -> None:
    """Test the describe hook receives no focus when the failure names no position."""
    problem = RecordingDescriptionsProblem()

    run_tests(
        problem,
        build_named_implementations("crash"),
        resolve_cases("fixture:two_unsorted"),
        runner_factory=FakeRunners({"crash": crash}),
    )

    assert problem.focuses == [None]


def test_a_focus_that_is_not_a_position_reaches_the_describe_hook_unchanged() -> None:
    """Test the describe hook receives the verifier's focus as given, whatever its kind."""
    problem = EdgeFocusProblem()

    report = run_tests(
        problem,
        build_named_implementations("bad"),
        resolve_cases(LARGE_GENERATED),
        options=NO_SHRINKING,
        runner_factory=FakeRunners({"bad": drop_last_above_five}),
    )

    detail = report.outcomes[0].detail
    assert problem.focuses == [EDGE_FOCUS, EDGE_FOCUS]
    assert detail is not None
    assert detail.actual_text is not None
    assert detail.actual_text.startswith("[")


def test_the_window_around_the_difference_is_in_the_description() -> None:
    """Test a short description shows the window around the first difference."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five},
        [LARGE_GENERATED],
        options=TestRunOptions(shrinking=None, description_limit=45),
    )

    detail = report.outcomes[0].detail

    assert detail is not None
    assert detail.expected_text is not None
    assert detail.actual_text is not None
    assert detail.expected_text.startswith("[..., ")
    assert "index 11 shown" in detail.expected_text
    assert detail.actual_text.startswith("[..., ")
    assert "index 10 shown" in detail.actual_text


@pytest.mark.parametrize(
    ("name", "status", "category"),
    [
        ("bad", CaseStatus.FAILED, "wrong length"),
        ("crashing", CaseStatus.ERROR, "error"),
    ],
    ids=["wrong-output", "runner-error"],
)
def test_a_failure_records_its_category(
    name: str, status: CaseStatus, category: str
) -> None:
    """Test a failing outcome records its status and the category of the failure."""
    report, _ = run_with_fake_runners(
        {"bad": drop_last_above_five, "crashing": crash}, ["fixture:duplicates"]
    )

    outcome = report.outcome("fixture:duplicates", name)

    assert outcome.category == category
    assert outcome.status is status


def test_a_passing_outcome_has_no_category() -> None:
    """Test an outcome that passed has an empty category."""
    report, _ = run_with_fake_runners({"a": sort_correctly}, ["fixture:empty"])

    assert report.outcomes[0].category == ""


def test_shrinking_keeps_the_category_the_verifier_named() -> None:
    """Test a shrink stops at inputs that fail with the same category as the original."""

    def short_when_long_else_unsorted(values: list[int]) -> list[int]:
        return values[:-1] if len(values) > 5 else sorted(values, reverse=True)

    report, _ = run_with_fake_runners(
        {"mixed": short_when_long_else_unsorted}, [LARGE_GENERATED]
    )

    outcome = report.outcomes[0]

    assert outcome.category == "wrong length"
    # Inputs of five values or fewer fail too, as "not sorted": not the same way.
    assert outcome.shrunk is not None
    assert len(outcome.shrunk.case.input_data) == 6


@given(strategies.text(), strategies.integers(-5, 100))
def test_truncated_text_fits_the_limit_and_keeps_the_start(
    text: str, limit: int
) -> None:
    """Test truncate_text never exceeds the limit and returns the start of the text."""
    marker = "..."
    shortened = truncate_text(text, limit)

    assert len(shortened) <= max(limit, 0)
    if len(text) <= limit:
        assert shortened == text
    else:
        start = shortened.removesuffix(marker) if limit > len(marker) else shortened
        assert text.startswith(start)


@given(
    strategies.lists(strategies.integers()),
    strategies.integers(0, 120),
    strategies.one_of(strategies.none(), strategies.integers(-5, 300)),
)
def test_a_described_sequence_fits_the_limit(
    values: list[int], limit: int, focus: int | None
) -> None:
    """Test describe_sequence never writes more than the limit, and shows a fitting sequence whole."""
    text = describe_sequence(values, limit, focus)
    whole = f"[{', '.join(repr(value) for value in values)}]"

    assert len(text) <= limit
    if len(whole) <= limit:
        assert text == whole


@given(
    strategies.lists(strategies.integers(), min_size=1),
    strategies.integers(0, 120),
    strategies.integers(-5, 300),
)
def test_a_described_window_contains_the_focus(
    values: list[int], limit: int, focus: int
) -> None:
    """Test the indices a window says it shows include the focus, moved into the sequence."""
    text = describe_sequence(values, limit, focus)
    shown = re.search(r"indices (\d+) to (\d+) shown", text)

    if shown is not None:
        position = min(max(focus, 0), len(values) - 1)
        assert int(shown.group(1)) <= position <= int(shown.group(2))
