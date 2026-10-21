"""A problem defined outside the algorithm-playground package: count distinct values.

Input:  ``u64 count`` followed by ``count`` little-endian ``i32`` values.
Output: ``u64``, the number of distinct values in the input.

Load it with ``--problem-module distinct_count_problem`` or, as the
``algorithm-playground.toml`` next to this file does, with ``problem_modules``.
"""

import random
from collections.abc import Iterator, Sequence
from pathlib import Path

from algorithm_playground.authoring import (
    Fixture,
    InputGenerator,
    Problem,
    VerificationResult,
    expect_end_of_stream,
    read_i32_array,
    read_u64,
    register_problem,
    shrink_sequence,
    write_i32_array,
    write_u64,
)

I32_MIN = -(2**31)
I32_MAX = 2**31 - 1


def _uniform(random_generator: random.Random, size: int) -> list[int]:
    return [random_generator.randint(I32_MIN, I32_MAX) for _ in range(size)]


def _few_values(random_generator: random.Random, size: int) -> list[int]:
    return [random_generator.randint(0, 4) for _ in range(size)]


@register_problem
class DistinctCountProblem(Problem[list[int], int, None]):
    """Count the distinct values in an array of i32 values."""

    name = "distinct-count"
    description = "Count the distinct values in an array of 32-bit signed integers."

    def serialize_input(self, data: list[int], path: Path) -> None:
        with path.open("wb") as stream:
            write_u64(stream, len(data))
            write_i32_array(stream, data)

    def deserialize_input(self, path: Path) -> list[int]:
        with path.open("rb") as stream:
            values = read_i32_array(stream, read_u64(stream))
            expect_end_of_stream(stream, "The input file")
        return values

    def deserialize_output(self, path: Path) -> int:
        with path.open("rb") as stream:
            count = read_u64(stream)
            expect_end_of_stream(stream, "The output file")
        return count

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield Fixture("empty", [], "no values")
        yield Fixture("one_value", [5])
        yield Fixture("all_equal", [3, 3, 3, 3], "one distinct value, repeated")
        yield Fixture("all_distinct", [4, 1, 3, 2])
        yield Fixture("negatives", [-1, -1, 0, 1], "negative values count too")

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return (
            InputGenerator("uniform", "values from the whole i32 range", _uniform),
            InputGenerator("few_values", "values drawn from a set of five", _few_values),
        )

    def verify(self, input_data: list[int], output: int) -> VerificationResult:
        expected = len(set(input_data))
        if output == expected:
            return VerificationResult(passed=True)
        else:
            return VerificationResult(
                passed=False, message=f"Expected {expected} distinct values, got {output}"
            )

    def expected_output(self, input_data: list[int]) -> int:
        return len(set(input_data))

    def shrink(self, input_data: list[int]) -> Iterator[list[int]]:
        return shrink_sequence(input_data)
