"""Tests for the sorting problem's cases, failure reports, shrinking, and verification."""

import pytest

from algorithm_playground.core import (
    CaseError,
    assert_valid_problem,
    build_startup_case,
    generate_case,
    get_default_generator,
)
from algorithm_playground.problems.sorting import (
    I32_MAX,
    I32_MIN,
    EventLog,
    SortingProblem,
    SortingTrace,
)


def test_the_default_generator_is_uniform(problem: SortingProblem) -> None:
    """Test the first generator of the problem is the uniform one."""
    assert problem.generators()[0].name == "uniform"


def test_generated_cases_are_deterministic(problem: SortingProblem) -> None:
    """Test generating a case twice with the same seed gives the same input."""
    generator = get_default_generator(problem)

    first = generate_case(generator, size=64, seed=123)
    second = generate_case(generator, size=64, seed=123)

    assert first.input_data == second.input_data


def test_generated_cases_have_the_requested_size(problem: SortingProblem) -> None:
    """Test a generated case has as many values as requested."""
    case = generate_case(get_default_generator(problem), size=64, seed=123)

    assert len(case.input_data) == 64


def test_generated_values_fit_in_i32(problem: SortingProblem) -> None:
    """Test every value of a generated case fits in a 32-bit signed integer."""
    case = generate_case(get_default_generator(problem), size=64, seed=123)

    assert all(I32_MIN <= value <= I32_MAX for value in case.input_data)


def test_generated_cases_with_different_seeds_differ(problem: SortingProblem) -> None:
    """Test generating cases with different seeds gives different inputs."""
    generator = get_default_generator(problem)

    first = generate_case(generator, size=64, seed=1)
    second = generate_case(generator, size=64, seed=2)

    assert first.input_data != second.input_data


def test_startup_case_is_empty(problem: SortingProblem) -> None:
    """Test the startup case has no values because the minimum size is zero."""
    assert problem.minimum_size == 0
    assert build_startup_case(problem, seed=5).input_data == []


def test_debug_pictures_draw_from_a_distribution_with_few_values(
    problem: SortingProblem,
) -> None:
    """Test the debug generator is the small-range distribution the problem defines."""
    assert problem.debug_generator == "small_range"
    assert problem.debug_generator in {
        generator.name for generator in problem.generators()
    }


def test_the_operation_names_are_the_keys_of_the_counts(
    problem: SortingProblem,
) -> None:
    """Test the operation counts of a trace are keyed by the operation names."""
    trace = SortingTrace((), events=EventLog.from_events([]))

    counts = problem.operation_counts([], [], trace)

    assert tuple(counts or ()) == problem.operation_names


def test_negative_size_rejected(problem: SortingProblem) -> None:
    """Test generating a case of negative size is rejected."""
    with pytest.raises(CaseError, match="must not be negative"):
        generate_case(get_default_generator(problem), size=-1, seed=0)


def test_satisfies_the_problem_interface(problem: SortingProblem) -> None:
    """Test the sorting problem passes the validation of the problem interface."""
    assert_valid_problem(problem)


def test_expected_output_is_the_sorted_input(problem: SortingProblem) -> None:
    """Test the expected output is the input in sorted order."""
    assert problem.expected_output([3, 1, 2]) == [1, 2, 3]


def test_a_short_input_is_described_in_full(problem: SortingProblem) -> None:
    """Test an input shorter than the limit is described in full."""
    assert problem.describe_input([3, 1, 2], limit=100) == "[3, 1, 2]"


def test_a_short_output_is_described_in_full(problem: SortingProblem) -> None:
    """Test an output shorter than the limit is described in full."""
    assert problem.describe_output([1, 2, 3], limit=100) == "[1, 2, 3]"


def test_long_values_are_cut_to_the_limit_with_their_count(
    problem: SortingProblem,
) -> None:
    """Test a long input is cut to the limit and followed by its number of values."""
    text = problem.describe_input(list(range(1000, 1100)), limit=40)

    assert text.startswith("[1000, 1001, ")
    assert text.endswith(", ...] (100 values)")
    assert len(text) <= 40


def test_a_focus_shows_a_window_around_the_first_difference(
    problem: SortingProblem,
) -> None:
    """Test a focus index makes the description show a window around that index."""
    text = problem.describe_output(list(range(1000, 2000)), limit=60, focus=700)

    assert text.startswith("[..., ")
    assert "1700" in text
    assert text.endswith(" shown)")


def test_the_input_is_described_from_its_start(problem: SortingProblem) -> None:
    """Test an input without a focus is described from its first value."""
    text = problem.describe_input(list(range(100)), limit=30)

    assert text.startswith("[0, 1, 2, ")


def test_a_limit_too_small_for_one_value_still_returns_text(
    problem: SortingProblem,
) -> None:
    """Test a limit smaller than one value cuts the text of the value."""
    assert problem.describe_input([123456789], limit=3) == "[12"


def test_a_tiny_limit_is_never_exceeded(problem: SortingProblem) -> None:
    """Test a description is never longer than a tiny limit."""
    assert len(problem.describe_input(list(range(50)), limit=10)) <= 10


def collect_candidates(problem: SortingProblem, values: list[int]) -> list[list[int]]:
    """Collect every candidate the problem shrinks the values to."""
    return list(problem.shrink(values))


def test_nothing_shrinks_an_empty_input(problem: SortingProblem) -> None:
    """Test an empty input has no shrink candidates."""
    assert collect_candidates(problem, []) == []


def test_a_single_element_shrinks_to_empty_and_to_zero(problem: SortingProblem) -> None:
    """Test a single value shrinks to nothing, to zero, and to half of itself."""
    assert collect_candidates(problem, [8]) == [[], [0], [4]]


def test_larger_chunks_are_dropped_before_single_elements(
    problem: SortingProblem,
) -> None:
    """Test candidates drop large chunks of values before single values."""
    candidates = collect_candidates(problem, [5, 4, 3, 2])

    assert candidates[:2] == [[3, 2], [5, 4]]
    assert [4, 3, 2] in candidates


def test_values_are_simplified_after_the_elements(problem: SortingProblem) -> None:
    """Test candidates simplify the values only after dropping elements."""
    candidates = collect_candidates(problem, [5, 4, 3, 2])

    assert candidates.index([0, 0, 0, 0]) > candidates.index([4, 3, 2])


def test_a_candidate_replaces_every_value_by_its_rank(problem: SortingProblem) -> None:
    """Test one candidate replaces every value by its rank among the distinct values."""
    candidates = collect_candidates(problem, [5, 4, 3, 2])

    assert [3, 2, 1, 0] in candidates


def test_no_candidate_equals_the_input(problem: SortingProblem) -> None:
    """Test no shrink candidate equals the input."""
    values = [I32_MAX, 0, I32_MIN, 7, 7]

    candidates = collect_candidates(problem, values)

    assert all(candidate != values for candidate in candidates)


def test_every_candidate_fits_in_i32(problem: SortingProblem) -> None:
    """Test every value of every shrink candidate fits in a 32-bit signed integer."""
    values = [I32_MAX, 0, I32_MIN, 7, 7]

    candidates = collect_candidates(problem, values)

    assert all(
        I32_MIN <= value <= I32_MAX for candidate in candidates for value in candidate
    )


def test_correct_output_passes(problem: SortingProblem) -> None:
    """Test a correctly sorted output passes with an empty message."""
    result = problem.verify([3, 1, 2], [1, 2, 3])

    assert result.passed
    assert result.message == ""


def test_length_mismatch_fails(problem: SortingProblem) -> None:
    """Test an output of another length than the input fails with a message about length."""
    result = problem.verify([3, 1, 2], [1, 2])

    assert not result.passed
    assert "length" in result.message.lower()


def test_unsorted_output_fails_with_index(problem: SortingProblem) -> None:
    """Test an unsorted output fails with a message naming the first wrong index."""
    result = problem.verify([3, 1, 2], [1, 3, 2])

    assert not result.passed
    assert "index 1" in result.message


def test_a_wrong_length_names_the_first_difference_and_its_category(
    problem: SortingProblem,
) -> None:
    """Test a wrong length reports the first difference and the wrong length category."""
    result = problem.verify([3, 1, 2], [1, 2])

    assert (result.focus, result.category) == (2, "wrong length")


def test_a_wrong_order_names_the_first_difference_and_its_category(
    problem: SortingProblem,
) -> None:
    """Test a wrong order reports the first difference and the not sorted category."""
    result = problem.verify([3, 1, 2], [1, 3, 2])

    assert (result.focus, result.category) == (1, "not sorted")


def test_a_length_difference_in_the_middle_is_found_there(
    problem: SortingProblem,
) -> None:
    """Test a length difference reports the first position where the outputs differ."""
    result = problem.verify([1, 2, 3, 4], [1, 5])

    assert result.focus == 1


def test_a_pass_names_neither(problem: SortingProblem) -> None:
    """Test a passing verification has no focus and no category."""
    result = problem.verify([3, 1, 2], [1, 2, 3])

    assert (result.focus, result.category) == (None, "")
