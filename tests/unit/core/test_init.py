"""Tests for the public surface of the core package."""

import pytest

from algorithm_playground import core
from algorithm_playground.core import truncate_text


class TestTruncateText:
    @pytest.mark.parametrize(
        ("text", "limit", "expected"),
        [
            ("short", 10, "short"),
            ("exactly ten", 11, "exactly ten"),
            ("a longer text", 8, "a lon..."),
            ("abcdef", 3, "abc"),
            ("abcdef", 0, ""),
        ],
        ids=["fits", "exactly-the-limit", "cut-with-marker", "limit-below-marker", "zero-limit"],
    )
    def test_cuts_to_the_limit_and_marks_the_cut(
        self, text: str, limit: int, expected: str
    ) -> None:
        """Test text longer than the limit is cut to the limit and ends with a marker."""
        assert truncate_text(text, limit) == expected


class TestPublicApi:
    def test_every_exported_name_exists(self) -> None:
        """Test every name listed in the package's exports is defined."""
        missing = [name for name in core.__all__ if not hasattr(core, name)]

        assert missing == []

    @pytest.mark.parametrize(
        "name",
        [
            "Problem",
            "Fixture",
            "InputGenerator",
            "Case",
            "CasePlan",
            "VerificationResult",
            "register_problem",
            "BinaryFormatError",
            "write_u64",
            "read_u64",
            "write_i32_array",
            "read_i32_array",
            "assert_valid_problem",
            "validate_problem",
        ],
    )
    def test_a_problem_author_needs_only_the_core_package(self, name: str) -> None:
        """Test the package exports the names a problem author needs."""
        assert name in core.__all__
