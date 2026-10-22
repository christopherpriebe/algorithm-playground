"""Tests for the building blocks a problem shrinks its inputs with."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import NamedTuple

import pytest

from algorithm_playground.core import (
    deduplicate_candidates,
    shrink_each,
    shrink_fields,
    shrink_integer,
    shrink_integer_sequence,
    shrink_integers,
    shrink_sequence,
)


@dataclass(frozen=True)
class Query:
    """A dataclass with a sequence field and an integer field to shrink field by field."""

    values: tuple[int, ...]
    target: int


class Edge(NamedTuple):
    """A named tuple to shrink field by field."""

    start: int
    end: int


class PlainValue:
    """A value that is neither a dataclass nor a tuple."""

    size = 3


def generate_endlessly() -> Iterator[list[int]]:
    """Yield the same candidate forever."""
    while True:
        yield [0]


def test_the_halves_come_first_then_smaller_chunks_down_to_single_elements() -> None:
    """Test candidates drop halves first, then smaller chunks, down to single elements."""
    candidates = list(shrink_sequence([1, 2, 3, 4]))

    assert candidates == [
        [3, 4],
        [1, 2],
        [2, 3, 4],
        [1, 3, 4],
        [1, 2, 4],
        [1, 2, 3],
    ]


def test_a_tuple_shrinks_to_tuples() -> None:
    """Test the candidates of a tuple are tuples."""
    assert list(shrink_sequence((1, 2, 3))) == [(2, 3), (1, 3), (1, 2)]


def test_a_list_shrinks_to_lists() -> None:
    """Test the candidates of a list are lists."""
    candidates = list(shrink_sequence([1, 2, 3]))

    assert all(isinstance(candidate, list) for candidate in candidates)


def test_nothing_is_offered_for_an_empty_sequence() -> None:
    """Test an empty sequence has no candidates."""
    assert list(shrink_sequence([])) == []


def test_a_single_element_shrinks_to_the_empty_sequence() -> None:
    """Test a one-element sequence has the empty sequence as its only candidate."""
    assert list(shrink_sequence([7])) == [[]]


@pytest.mark.parametrize(
    ("values", "minimum_length", "expected"),
    [
        ([1, 2, 3, 4], 3, [[2, 3, 4], [1, 3, 4], [1, 2, 4], [1, 2, 3]]),
        ([1, 2], 2, []),
    ],
    ids=["drops-one-element", "already-at-the-minimum"],
)
def test_a_minimum_length_is_respected(
    values: list[int], minimum_length: int, expected: list[list[int]]
) -> None:
    """Test no candidate is shorter than the minimum length."""
    candidates = list(shrink_sequence(values, minimum_length=minimum_length))

    assert candidates == expected


def test_shrinking_a_sequence_leaves_the_original_unchanged() -> None:
    """Test shrinking leaves the sequence it was given untouched."""
    values = [1, 2, 3]

    list(shrink_sequence(values))

    assert values == [1, 2, 3]


def test_a_string_is_not_a_sequence_to_shrink() -> None:
    """Test a string is rejected because only lists and tuples can be shrunk."""
    with pytest.raises(TypeError, match="list or a tuple"):
        list(shrink_sequence("abc"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, []), (1, [0]), (-1, [0]), (8, [0, 4]), (-9, [0, -4]), (2**40, [0, 2**39])],
    ids=["zero", "one", "minus-one", "even", "negative-odd", "large"],
)
def test_zero_comes_first_then_half_rounded_toward_zero(
    value: int, expected: list[int]
) -> None:
    """Test an integer shrinks to zero first and then to half of itself rounded toward zero."""
    assert list(shrink_integer(value)) == expected


def test_all_zero_then_ranks_then_one_value_at_a_time() -> None:
    """Test candidates are all zeros, then ranks, then each value shrunk on its own."""
    candidates = list(shrink_integers([30, 10, 30]))

    assert candidates == [
        [0, 0, 0],
        [1, 0, 1],
        [0, 10, 30],
        [15, 10, 30],
        [30, 0, 30],
        [30, 5, 30],
        [30, 10, 0],
        [30, 10, 15],
    ]


@pytest.mark.parametrize("values", [[0, 0], [0, 1], [3], [], [0, 1, 2]], ids=str)
def test_a_candidate_equal_to_the_input_is_never_offered(values: list[int]) -> None:
    """Test the input itself is not among its candidates."""
    assert values not in list(shrink_integers(values))


def test_it_keeps_the_type() -> None:
    """Test the candidates of a tuple are tuples."""
    candidates = list(shrink_integers((5, 9)))

    assert all(isinstance(candidate, tuple) for candidate in candidates)


def test_elements_are_removed_before_numbers_are_simplified() -> None:
    """Test removing elements is tried before simplifying the numbers."""
    candidates = list(shrink_integer_sequence([5, 4, 3, 2]))

    assert candidates[:2] == [[3, 2], [5, 4]]
    assert candidates.index([0, 0, 0, 0]) > candidates.index([4, 3, 2])
    assert [3, 2, 1, 0] in candidates


@pytest.mark.parametrize("values", [[7, 7, 7, 7], [0, 0], [1], [], [3, 1, 3]], ids=str)
def test_no_candidate_repeats_or_equals_the_input(values: list[int]) -> None:
    """Test every candidate is distinct and none equals the input."""
    candidates = list(shrink_integer_sequence(values))

    assert values not in candidates
    assert len({tuple(candidate) for candidate in candidates}) == len(candidates)


def test_the_type_is_kept() -> None:
    """Test the candidates of a tuple are tuples."""
    candidates = list(shrink_integer_sequence((9, 8)))

    assert all(isinstance(candidate, tuple) for candidate in candidates)


def test_each_element_is_replaced_by_the_candidates_of_its_own_shrinker() -> None:
    """Test each candidate changes one element to a candidate from the shrinker."""
    candidates = list(shrink_each([4, 2], shrink_integer))

    assert candidates == [[0, 2], [2, 2], [4, 0], [4, 1]]


def test_elements_can_be_composite() -> None:
    """Test the shrinker of the elements may itself shrink fields of composite elements."""
    pairs = [(4, 1)]

    def shrink_pair(pair: tuple[int, int]) -> Iterable[tuple[int, int]]:
        return shrink_fields(pair, {0: shrink_integer, 1: shrink_integer})

    assert list(shrink_each(pairs, shrink_pair)) == [[(0, 1)], [(2, 1)], [(4, 0)]]


def test_a_dataclass_is_shrunk_field_by_field_in_the_order_given() -> None:
    """Test the fields of a dataclass are shrunk in the order of the shrinkers given."""
    query = Query((1, 2, 3, 4), 9)

    candidates = list(
        shrink_fields(query, {"values": shrink_sequence, "target": shrink_integer})
    )

    assert candidates[0] == Query((3, 4), 9)
    assert candidates[-2:] == [Query((1, 2, 3, 4), 0), Query((1, 2, 3, 4), 4)]
    assert all(isinstance(candidate, Query) for candidate in candidates)


def test_a_field_that_is_not_named_is_left_alone() -> None:
    """Test a field without a shrinker keeps its value in every candidate."""
    candidates = list(shrink_fields(Query((1, 2), 9), {"target": shrink_integer}))

    assert candidates == [Query((1, 2), 0), Query((1, 2), 4)]


def test_a_named_tuple_is_shrunk_by_field_name() -> None:
    """Test the fields of a named tuple are addressed by name."""
    candidates = list(shrink_fields(Edge(6, 2), {"start": shrink_integer}))

    assert candidates == [Edge(0, 2), Edge(3, 2)]


def test_a_plain_tuple_is_shrunk_by_position() -> None:
    """Test the items of a plain tuple are addressed by position."""
    assert list(shrink_fields((6, 2), {1: shrink_integer})) == [(6, 0), (6, 1)]


def test_shrinking_fields_leaves_the_original_unchanged() -> None:
    """Test shrinking leaves the value it was given untouched."""
    query = Query((1, 2), 5)

    list(shrink_fields(query, {"target": shrink_integer}))

    assert query == Query((1, 2), 5)


def test_an_unknown_field_is_an_error_naming_it() -> None:
    """Test a shrinker for a field that does not exist raises an error naming the field."""
    with pytest.raises(AttributeError, match="size"):
        list(shrink_fields(Query((), 0), {"size": shrink_integer}))


def test_a_value_of_another_kind_cannot_be_shrunk_field_by_field() -> None:
    """Test only dataclasses, named tuples and tuples can be shrunk field by field."""
    with pytest.raises(TypeError, match="dataclass, a named tuple or a tuple"):
        list(shrink_fields(PlainValue(), {"size": shrink_integer}))


def test_a_position_in_a_dataclass_is_an_error() -> None:
    """Test a dataclass cannot be addressed by position."""
    with pytest.raises(TypeError, match="not subscriptable"):
        list(shrink_fields(Query((), 5), {1: shrink_integer}))


def test_each_candidate_is_offered_once_and_the_input_never() -> None:
    """Test repeated candidates and the input itself are filtered out."""
    candidates = [[1], [2], [1], [3], [2]]

    assert list(deduplicate_candidates(candidates, [3])) == [[1], [2]]


def test_it_is_lazy() -> None:
    """Test candidates are produced on demand, so an endless source does not hang."""
    assert next(deduplicate_candidates(generate_endlessly())) == [0]
