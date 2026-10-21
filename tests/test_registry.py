"""Tests for the central problem registry and the @register_problem decorator."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from algorithm_playground.core.problem import (
    BenchmarkCase,
    Problem,
    TestCase,
    VerificationResult,
)
from algorithm_playground.core.registry import (
    REGISTRY,
    ProblemRegistrationError,
    get_problem,
    list_problems,
    register_problem,
)


class _StubProblem(Problem[list[int], list[int], None]):
    name = "stub-for-tests"
    description = "Stub problem used by unit tests."

    def serialize_input(self, data: list[int], path: Path) -> None:
        path.write_bytes(b"")

    def deserialize_output(self, path: Path) -> list[int]:
        return []

    def deserialize_trace(self, path: Path) -> None:
        return None

    def test_cases(self) -> Iterator[TestCase[list[int]]]:
        return iter([])

    def benchmark_case(self, seed: int, size: int) -> BenchmarkCase[list[int]]:
        return BenchmarkCase("stub", size, [])

    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        return VerificationResult(True)


@pytest.fixture(autouse=True)
def _restore_registry() -> Iterator[None]:
    snapshot = dict(REGISTRY)
    try:
        yield
    finally:
        REGISTRY.clear()
        REGISTRY.update(snapshot)


def test_register_problem_adds_to_registry() -> None:
    register_problem(_StubProblem)
    assert "stub-for-tests" in REGISTRY
    assert REGISTRY["stub-for-tests"] is _StubProblem


def test_register_problem_returns_class_unchanged() -> None:
    returned = register_problem(_StubProblem)
    assert returned is _StubProblem


def test_register_problem_rejects_missing_name() -> None:
    class Anonymous(_StubProblem):
        name = ""

    with pytest.raises(ProblemRegistrationError):
        register_problem(Anonymous)


def test_register_problem_rejects_duplicate_name() -> None:
    register_problem(_StubProblem)

    class Conflicting(_StubProblem):
        name = "stub-for-tests"

    with pytest.raises(ProblemRegistrationError):
        register_problem(Conflicting)


def test_get_problem_instantiates_registered_class() -> None:
    register_problem(_StubProblem)
    instance = get_problem("stub-for-tests")
    assert isinstance(instance, _StubProblem)


def test_get_problem_raises_for_unknown_name() -> None:
    with pytest.raises(KeyError):
        get_problem("not-a-problem")


def test_list_problems_returns_sorted_names() -> None:
    register_problem(_StubProblem)
    names = list_problems()
    assert names == sorted(names)
    assert "stub-for-tests" in names


def test_re_registering_same_class_is_idempotent() -> None:
    register_problem(_StubProblem)
    register_problem(_StubProblem)  # must not raise
