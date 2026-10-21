"""Tests for the sorting verifier."""

from algorithm_playground.problems.sorting import SortingProblem


class TestVerification:
    def test_correct_output_passes(self, problem: SortingProblem) -> None:
        """Test a correctly sorted output passes with an empty message."""
        result = problem.verify([3, 1, 2], [1, 2, 3])

        assert result.passed
        assert result.message == ""

    def test_length_mismatch_fails(self, problem: SortingProblem) -> None:
        """Test an output of another length than the input fails with a message about length."""
        result = problem.verify([3, 1, 2], [1, 2])

        assert not result.passed
        assert "length" in result.message.lower()

    def test_unsorted_output_fails_with_index(self, problem: SortingProblem) -> None:
        """Test an unsorted output fails with a message naming the first wrong index."""
        result = problem.verify([3, 1, 2], [1, 3, 2])

        assert not result.passed
        assert "index 1" in result.message


class TestVerificationDetails:
    def test_a_wrong_length_names_the_first_difference_and_its_category(
        self, problem: SortingProblem
    ) -> None:
        """Test a wrong length reports the first difference and the wrong length category."""
        result = problem.verify([3, 1, 2], [1, 2])

        assert (result.focus, result.category) == (2, "wrong length")

    def test_a_wrong_order_names_the_first_difference_and_its_category(
        self, problem: SortingProblem
    ) -> None:
        """Test a wrong order reports the first difference and the not sorted category."""
        result = problem.verify([3, 1, 2], [1, 3, 2])

        assert (result.focus, result.category) == (1, "not sorted")

    def test_a_length_difference_in_the_middle_is_found_there(
        self, problem: SortingProblem
    ) -> None:
        """Test a length difference reports the first position where the outputs differ."""
        result = problem.verify([1, 2, 3, 4], [1, 5])

        assert result.focus == 1

    def test_a_pass_names_neither(self, problem: SortingProblem) -> None:
        """Test a passing verification has no focus and no category."""
        result = problem.verify([3, 1, 2], [1, 2, 3])

        assert (result.focus, result.category) == (None, "")
