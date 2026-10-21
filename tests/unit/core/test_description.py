"""Tests for the helpers that shorten values for failure reports."""

from collections.abc import Iterator, Sequence

import pytest

from algorithm_playground.core.description import describe_error, describe_sequence, truncate_text


class ReadCountingList(list[int]):
    """A list that counts how often its items are read and refuses to be iterated."""

    def __init__(self, values: range) -> None:
        super().__init__(values)
        self.reads = 0

    def __getitem__(self, position: int) -> int:  # ty: ignore[invalid-method-override]
        self.reads += 1
        return super().__getitem__(position)

    def __iter__(self) -> Iterator[int]:
        raise AssertionError("the whole sequence must not be iterated")


class TestDescribeError:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (KeyError("section"), "KeyError: 'section'"),
            (ValueError("bad value"), "ValueError: bad value"),
        ],
        ids=["key-error", "value-error"],
    )
    def test_names_the_type_and_the_message_of_the_error(
        self, error: Exception, expected: str
    ) -> None:
        """Test the description holds the type name of the error and its message."""
        assert describe_error(error) == expected

    def test_an_error_without_a_message_still_names_its_type(self) -> None:
        """Test an error with no message is described by its type alone."""
        assert describe_error(RuntimeError()) == "RuntimeError: "


class TestTruncateText:
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
    def test_cuts_to_the_limit_and_marks_the_cut(
        self, text: str, limit: int, expected: str
    ) -> None:
        """Test text longer than the limit is cut to the limit and ends with a marker."""
        assert truncate_text(text, limit) == expected


class TestDescribeSequence:
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
        self, values: Sequence[object], expected: str
    ) -> None:
        """Test a sequence that fits within the limit is written out in full."""
        assert describe_sequence(values, 100) == expected

    def test_a_longer_one_shows_the_items_that_fit_and_the_count(self) -> None:
        """Test a sequence over the limit shows the leading items that fit and the total count."""
        text = describe_sequence(list(range(1000)), 40)

        assert text == "[0, 1, 2, 3, 4, 5, 6, ...] (1000 values)"
        assert len(text) <= 40

    @pytest.mark.parametrize("limit", range(30, 200, 7))
    def test_the_result_never_exceeds_the_limit(self, limit: int) -> None:
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
                "[..., 496, 497, 498, 499, 500, 501, 502, 503, ...] "
                "(1000 values, indices 496 to 503 shown)",
            ),
        ],
        ids=["narrow-limit", "wide-limit"],
    )
    def test_a_focus_shows_a_window_around_it_and_says_which_indices(
        self, limit: int, expected: str
    ) -> None:
        """Test a focus shows a window of items around it and names the indices shown."""
        assert describe_sequence(list(range(1000)), limit, focus=500) == expected

    def test_a_window_that_reaches_the_start_has_no_leading_ellipsis(self) -> None:
        """Test a window that includes the first item starts the list without an ellipsis."""
        text = describe_sequence(list(range(1000)), 60, focus=2)

        assert text == "[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, ...] (1000 values)"

    def test_a_window_that_reaches_the_end_has_no_trailing_ellipsis(self) -> None:
        """Test a window that includes the last item ends the list without an ellipsis."""
        text = describe_sequence(list(range(1000)), 60, focus=999)

        assert text == "[..., 997, 998, 999] (1000 values, indices 997 to 999 shown)"

    def test_a_single_index_is_named_as_one(self) -> None:
        """Test a window of one item says 'index' in the singular."""
        text = describe_sequence([10**9 + offset for offset in range(30)], 50, focus=29)

        assert text == "[..., 1000000029] (30 values, index 29 shown)"

    @pytest.mark.parametrize(
        ("focus", "nearest_end"), [(-5, 0), (5000, 999)], ids=["before-the-start", "past-the-end"]
    )
    def test_a_focus_outside_the_sequence_is_moved_to_the_nearest_end(
        self, focus: int, nearest_end: int
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
        self, values: list[int], limit: int, expected: str
    ) -> None:
        """Test a limit that cannot hold even one item cuts the written text instead."""
        assert describe_sequence(values, limit) == expected

    def test_a_sequence_that_fits_is_shown_whole_even_with_a_focus(self) -> None:
        """Test a focus changes nothing for a sequence that fits within the limit."""
        assert describe_sequence([1, 2, 3], 50, focus=1) == "[1, 2, 3]"

    def test_a_huge_sequence_is_not_formatted_in_full(self) -> None:
        """Test describing a huge sequence reads only a few of its items."""
        values = ReadCountingList(range(1_000_000))

        describe_sequence(values, 60, focus=500_000)

        assert values.reads < 200
