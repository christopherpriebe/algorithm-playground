"""Fixtures shared by the sorting problem tests."""

import pytest

from algorithm_playground.problems.sorting import SortingProblem


@pytest.fixture
def problem() -> SortingProblem:
    """A fresh sorting problem."""
    return SortingProblem()
