"""Central registry of available `Problem` implementations.

Concrete problems decorate their class with `@register_problem` at import
time, which adds them to the module-level `REGISTRY`. The CLI populates the
registry by importing :mod:`algorithm_playground.problems`, which in turn
imports each built-in problem subpackage so all decorators fire.
"""

from __future__ import annotations

from typing import TypeVar

from algorithm_playground.core.problem import Problem

REGISTRY: dict[str, type[Problem]] = {}

ProblemSubclass = TypeVar("ProblemSubclass", bound=Problem)


class ProblemRegistrationError(ValueError):
    """Raised when a `Problem` subclass cannot be registered."""


def register_problem(cls: type[ProblemSubclass]) -> type[ProblemSubclass]:
    """Decorator: add a `Problem` subclass to the central registry.

    The class must define a non-empty ``name`` class attribute. The decorator
    returns the class unchanged so it can be used as ``@register_problem``.
    """
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not name:
        raise ProblemRegistrationError(
            f"{cls.__name__} must define a non-empty 'name' class attribute"
        )
    if name in REGISTRY and REGISTRY[name] is not cls:
        raise ProblemRegistrationError(
            f"Problem name '{name}' is already registered by "
            f"{REGISTRY[name].__module__}.{REGISTRY[name].__name__}"
        )
    REGISTRY[name] = cls
    return cls


def get_problem(name: str) -> Problem:
    """Instantiate and return the registered problem with the given name."""
    try:
        problem_class = REGISTRY[name]
    except KeyError as error:
        available = ", ".join(sorted(REGISTRY)) or "(none)"
        raise KeyError(f"Unknown problem '{name}'. Registered problems: {available}") from error
    return problem_class()


def list_problems() -> list[str]:
    """Return the sorted list of registered problem names."""
    return sorted(REGISTRY)
