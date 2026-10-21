"""Framework primitives: the Problem ABC, registry, runner, and shared helpers."""

from algorithm_playground.core.problem import (
    BenchmarkCase,
    Problem,
    TestCase,
    VerificationResult,
)
from algorithm_playground.core.registry import (
    get_problem,
    list_problems,
    register_problem,
)
from algorithm_playground.core.runner import Runner, RunnerError, RunResult

__all__ = [
    "BenchmarkCase",
    "Problem",
    "RunResult",
    "Runner",
    "RunnerError",
    "TestCase",
    "VerificationResult",
    "get_problem",
    "list_problems",
    "register_problem",
]
