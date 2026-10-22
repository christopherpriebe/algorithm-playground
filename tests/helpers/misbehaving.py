"""A problem whose hooks misbehave on request, to test how the harness copes.

The problem counts the distinct values of an array. It defines no trace format.
``build_faulty_problem_class(fault)`` returns a subclass in which the hook named by
``fault`` raises (``fixtures``, ``generators``, ``verify``, ``serialize_input``
and ``expected_output`` as they are; ``generator`` for the function of the
``broken`` distribution, which raises for every size, next to the working
``uniform`` distribution).
"""

import random
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from typing_extensions import override

from algorithm_playground.authoring import (
    Fixture,
    InputGenerator,
    Problem,
    VerificationResult,
    expect_end_of_stream,
    read_i32_array,
    read_u64,
    shrink_sequence,
    write_i32_array,
    write_u64,
)

PROBLEM_NAME = "faulty"


def generate_uniform(random_generator: random.Random, size: int) -> list[int]:
    """Generate ``size`` values between zero and nine."""
    return [random_generator.randint(0, 9) for _ in range(size)]


def generate_broken(
    random_generator: random.Random,  # noqa: ARG001  signature fixed by the generator contract
    size: int,  # noqa: ARG001  signature fixed by the generator contract
) -> list[int]:
    """Fail for every size, as a generator that is broken."""
    message = "generator exploded"
    raise RuntimeError(message)


class FaultyProblem(Problem[list[int], int, None]):
    """Counts distinct values; ``fault`` names the hook that raises (empty: none does)."""

    name = PROBLEM_NAME
    description = "misbehaving [bold]problem[/bold]"
    fault = ""

    @override
    def serialize_input(self, data: list[int], path: Path) -> None:
        if self.fault == "serialize_input":
            message = "serialize_input exploded"
            raise RuntimeError(message)
        with path.open("wb") as stream:
            write_u64(stream, len(data))
            write_i32_array(stream, data)

    @override
    def deserialize_input(self, path: Path) -> list[int]:
        with path.open("rb") as stream:
            values = read_i32_array(stream, read_u64(stream))
            expect_end_of_stream(stream, "input")
        return values

    @override
    def deserialize_output(self, path: Path) -> int:
        with path.open("rb") as stream:
            count = read_u64(stream)
            expect_end_of_stream(stream, "output")
        return count

    @override
    def fixtures(self) -> Iterable[Fixture[list[int]]]:
        if self.fault == "fixtures":
            message = "fixtures exploded"
            raise RuntimeError(message)
        yield Fixture("one", [1], description="a [red]fixture[/red] description")

    @override
    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        if self.fault == "generators":
            message = "generators exploded"
            raise RuntimeError(message)
        generators = [
            InputGenerator(
                "uniform", description="uniform values", generate=generate_uniform
            )
        ]
        if self.fault == "generator":
            generators.append(
                InputGenerator(
                    "broken", description="always raises", generate=generate_broken
                )
            )
        return generators

    @override
    def verify(self, input_data: list[int], output: int) -> VerificationResult:
        if self.fault == "verify":
            message = "verify exploded"
            raise RuntimeError(message)
        expected = len(set(input_data))
        return VerificationResult(
            output == expected, message=f"expected {expected}, got {output}"
        )

    @override
    def expected_output(self, input_data: list[int]) -> int | None:
        if self.fault == "expected_output":
            message = "expected_output exploded"
            raise RuntimeError(message)
        return len(set(input_data))

    @override
    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        return shrink_sequence(input_data)


def build_faulty_problem_class(fault: str) -> type[FaultyProblem]:
    """Build the faulty problem class in which the hook called ``fault`` raises.

    Args:
        fault: The name of the hook that raises; empty for a problem that does not misbehave.

    Returns:
        A subclass of :class:`FaultyProblem` with ``fault`` set.
    """
    return type("FaultyProblemWithFault", (FaultyProblem,), {"fault": fault})


def count_distinct_values(values: list[int]) -> int:
    """Count the distinct values, as a correct implementation of the faulty problem does."""
    return len(set(values))
