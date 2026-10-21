"""Tests for the helpers that shorten values for failure reports."""

from __future__ import annotations

import pytest

from algorithm_playground.core.description import describe_sequence, truncate_text


class TestTruncateText:
    @pytest.mark.parametrize(
        ("text", "limit", "expected"),
        [
            ("short", 10, "short"),
            ("a longer text", 8, "a lon..."),
            ("abcdef", 3, "abc"),
            ("abcdef", 0, ""),
        ],
    )
    def test_cuts_to_the_limit_and_marks_the_cut(
        self, text: str, limit: int, expected: str
    ) -> None:
        assert truncate_text(text, limit) == expected


class TestDescribeSequence:
    def test_a_sequence_that_fits_is_shown_whole(self) -> None:
        assert describe_sequence([3, 1, 2], 100) == "[3, 1, 2]"
        assert describe_sequence([], 100) == "[]"
        assert describe_sequence(("a", "b"), 100) == "['a', 'b']"

    def test_a_longer_one_shows_the_items_that_fit_and_the_count(self) -> None:
        text = describe_sequence(list(range(1000)), 40)
        assert text == "[0, 1, 2, 3, 4, 5, 6, ...] (1000 values)"
        assert len(text) <= 40

    def test_the_result_never_exceeds_the_limit(self) -> None:
        values = [123456789 * (index + 1) for index in range(50)]
        for limit in range(30, 200, 7):
            assert len(describe_sequence(values, limit)) <= limit
            assert len(describe_sequence(values, limit, focus=25)) <= limit

    def test_a_focus_shows_a_window_around_it_and_says_which_indices(self) -> None:
        assert describe_sequence(list(range(1000)), 60, focus=500) == (
            "[..., 499, 500, ...] (1000 values, indices 499 to 500 shown)"
        )
        assert describe_sequence(list(range(1000)), 90, focus=500) == (
            "[..., 496, 497, 498, 499, 500, 501, 502, 503, ...] "
            "(1000 values, indices 496 to 503 shown)"
        )

    def test_a_window_that_reaches_the_start_has_no_leading_ellipsis(self) -> None:
        assert describe_sequence(list(range(1000)), 60, focus=2) == (
            "[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ...] (1000 values)"
        )

    def test_a_window_that_reaches_the_end_has_no_trailing_ellipsis(self) -> None:
        assert describe_sequence(list(range(1000)), 60, focus=999) == (
            "[..., 997, 998, 999] (1000 values, indices 997 to 999 shown)"
        )

    def test_a_single_index_is_named_as_one(self) -> None:
        assert describe_sequence([10**9 + offset for offset in range(30)], 50, focus=29) == (
            "[..., 1000000029] (30 values, index 29 shown)"
        )

    @pytest.mark.parametrize("focus", [-5, 5000])
    def test_a_focus_outside_the_sequence_is_moved_to_the_nearest_end(self, focus: int) -> None:
        text = describe_sequence(list(range(1000)), 60, focus=focus)
        expected = describe_sequence(list(range(1000)), 60, focus=0 if focus < 0 else 999)
        assert text == expected

    def test_a_limit_too_small_for_one_item_cuts_the_text(self) -> None:
        assert describe_sequence([123456789012], 10) == "[123456..."
        assert describe_sequence(list(range(100)), 3) == "[0,"

    def test_a_sequence_that_fits_is_shown_whole_even_with_a_focus(self) -> None:
        assert describe_sequence([1, 2, 3], 50, focus=1) == "[1, 2, 3]"

    def test_a_huge_sequence_is_not_formatted_in_full(self) -> None:
        class Counting(list[int]):
            reads = 0

            def __getitem__(self, position: int) -> int:  # ty: ignore[invalid-method-override]
                Counting.reads += 1
                return super().__getitem__(position)

            def __iter__(self):
                raise AssertionError("the whole sequence must not be iterated")

        values = Counting(range(1_000_000))
        describe_sequence(values, 60, focus=500_000)
        assert Counting.reads < 200
