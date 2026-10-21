"""Helpers that register problems for a test.

Registrations are undone after each test by the autouse ``_isolate_problem_loading`` fixture.
"""

from algorithm_playground.core import registry
from algorithm_playground.problems.sorting import SortingProblem
from helpers.misbehaving import PROBLEM_NAME, build_faulty_problem_class


def register_other_problem(name: str) -> None:
    """Register a copy of the sorting problem under another name.

    Args:
        name: The name to register the copy under.
    """
    registry.register_problem(type("OtherProblem", (SortingProblem,), {"name": name}))


def register_faulty_problem(fault: str = "") -> str:
    """Register the problem in which the hook called ``fault`` raises.

    Args:
        fault: The name of the hook that raises; empty for a problem that does not misbehave.

    Returns:
        The name the problem is registered under.
    """
    registry.register_problem(build_faulty_problem_class(fault))
    return PROBLEM_NAME
