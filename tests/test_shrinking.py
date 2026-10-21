"""Tests for the building blocks of a shrink hook."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple

import pytest

from algorithm_playground.core.shrinking import (
    distinct,
    shrink_each,
    shrink_fields,
    shrink_integer,
    shrink_integer_sequence,
    shrink_integers,
    shrink_sequence,
)


class TestShrinkSequence:
    def test_the_halves_come_first_then_smaller_chunks_down_to_single_elements(self) -> None:
        assert list(shrink_sequence([1, 2, 3, 4])) == [
            [3, 4],
            [1, 2],
            [2, 3, 4],
            [1, 3, 4],
            [1, 2, 4],
            [1, 2, 3],
        ]

    def test_the_type_of_the_sequence_is_kept(self) -> None:
        assert list(shrink_sequence((1, 2, 3))) == [(2, 3), (1, 3), (1, 2)]
        assert all(isinstance(candidate, list) for candidate in shrink_sequence([1, 2, 3]))

    def test_nothing_is_offered_for_an_empty_sequence(self) -> None:
        assert list(shrink_sequence([])) == []

    def test_a_single_element_shrinks_to_the_empty_sequence(self) -> None:
        assert list(shrink_sequence([7])) == [[]]

    def test_a_minimum_length_is_respected(self) -> None:
        candidates = list(shrink_sequence([1, 2, 3, 4], minimum_length=3))
        assert candidates == [[2, 3, 4], [1, 3, 4], [1, 2, 4], [1, 2, 3]]
        assert list(shrink_sequence([1, 2], minimum_length=2)) == []

    def test_the_original_is_not_changed(self) -> None:
        values = [1, 2, 3]
        list(shrink_sequence(values))
        assert values == [1, 2, 3]

    def test_a_string_is_not_a_sequence_to_shrink(self) -> None:
        with pytest.raises(TypeError, match="list or a tuple"):
            list(shrink_sequence("abc"))


class TestShrinkInteger:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0, []), (1, [0]), (-1, [0]), (8, [0, 4]), (-9, [0, -4]), (2**40, [0, 2**39])],
    )
    def test_zero_comes_first_then_half_rounded_toward_zero(
        self, value: int, expected: list[int]
    ) -> None:
        assert list(shrink_integer(value)) == expected


class TestShrinkIntegers:
    def test_all_zero_then_ranks_then_one_value_at_a_time(self) -> None:
        assert list(shrink_integers([30, 10, 30])) == [
            [0, 0, 0],
            [1, 0, 1],
            [0, 10, 30],
            [15, 10, 30],
            [30, 0, 30],
            [30, 5, 30],
            [30, 10, 0],
            [30, 10, 15],
        ]

    def test_a_candidate_equal_to_the_input_is_never_offered(self) -> None:
        for values in ([0, 0], [0, 1], [3], [], [0, 1, 2]):
            assert values not in list(shrink_integers(values))

    def test_it_keeps_the_type(self) -> None:
        assert all(isinstance(candidate, tuple) for candidate in shrink_integers((5, 9)))


class TestShrinkIntegerSequence:
    def test_elements_are_removed_before_numbers_are_simplified(self) -> None:
        candidates = list(shrink_integer_sequence([5, 4, 3, 2]))
        assert candidates[:2] == [[3, 2], [5, 4]]
        assert candidates.index([0, 0, 0, 0]) > candidates.index([4, 3, 2])
        assert [3, 2, 1, 0] in candidates

    def test_no_candidate_repeats_or_equals_the_input(self) -> None:
        for values in ([7, 7, 7, 7], [0, 0], [1], [], [3, 1, 3]):
            candidates = list(shrink_integer_sequence(values))
            assert values not in candidates
            assert len({tuple(candidate) for candidate in candidates}) == len(candidates)

    def test_the_type_is_kept(self) -> None:
        assert all(isinstance(candidate, tuple) for candidate in shrink_integer_sequence((9, 8)))


class TestShrinkEach:
    def test_each_element_is_replaced_by_the_candidates_of_its_own_shrinker(self) -> None:
        assert list(shrink_each([4, 2], shrink_integer)) == [[0, 2], [2, 2], [4, 0], [4, 1]]

    def test_elements_can_be_composite(self) -> None:
        pairs = [(4, 1)]

        def shrink_pair(pair: tuple[int, int]) -> Iterable[tuple[int, int]]:
            return shrink_fields(pair, {0: shrink_integer, 1: shrink_integer})

        assert list(shrink_each(pairs, shrink_pair)) == [[(0, 1)], [(2, 1)], [(4, 0)]]


@dataclass(frozen=True)
class Query:
    values: tuple[int, ...]
    target: int


class Edge(NamedTuple):
    start: int
    end: int


class TestShrinkFields:
    def test_a_dataclass_is_shrunk_field_by_field_in_the_order_given(self) -> None:
        query = Query((1, 2, 3, 4), 9)
        candidates = list(
            shrink_fields(query, {"values": shrink_sequence, "target": shrink_integer})
        )
        assert candidates[0] == Query((3, 4), 9)
        assert candidates[-2:] == [Query((1, 2, 3, 4), 0), Query((1, 2, 3, 4), 4)]
        assert all(isinstance(candidate, Query) for candidate in candidates)

    def test_a_field_that_is_not_named_is_left_alone(self) -> None:
        candidates = list(shrink_fields(Query((1, 2), 9), {"target": shrink_integer}))
        assert candidates == [Query((1, 2), 0), Query((1, 2), 4)]

    def test_a_named_tuple_is_shrunk_by_field_name(self) -> None:
        assert list(shrink_fields(Edge(6, 2), {"start": shrink_integer})) == [
            Edge(0, 2),
            Edge(3, 2),
        ]

    def test_a_plain_tuple_is_shrunk_by_position(self) -> None:
        assert list(shrink_fields((6, 2), {1: shrink_integer})) == [(6, 0), (6, 1)]

    def test_the_original_is_not_changed(self) -> None:
        query = Query((1, 2), 5)
        list(shrink_fields(query, {"target": shrink_integer}))
        assert query == Query((1, 2), 5)

    def test_an_unknown_field_is_an_error_naming_it(self) -> None:
        with pytest.raises(AttributeError, match="size"):
            list(shrink_fields(Query((), 0), {"size": shrink_integer}))

    def test_a_value_of_another_kind_cannot_be_shrunk_field_by_field(self) -> None:
        class Plain:
            size = 3

        with pytest.raises(TypeError, match="dataclass, a named tuple or a tuple"):
            list(shrink_fields(Plain(), {"size": shrink_integer}))

    def test_a_position_in_a_dataclass_is_an_error(self) -> None:
        with pytest.raises(TypeError):
            list(shrink_fields(Query((), 5), {1: shrink_integer}))


class TestDistinct:
    def test_each_candidate_is_offered_once_and_the_input_never(self) -> None:
        candidates = [[1], [2], [1], [3], [2]]
        assert list(distinct(candidates, [3])) == [[1], [2]]

    def test_it_is_lazy(self) -> None:
        def endless():
            while True:
                yield [0]

        assert next(distinct(endless())) == [0]
