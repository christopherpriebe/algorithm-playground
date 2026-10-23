"""A problem with two dimensions, to test what must work beyond a single size.

The problem is deliberately tiny. An input is a pair of counts, the ``vertices``
and the ``edges``, written as two ``u64`` values; the output is their sum as one
``u64``. Its one generator returns exactly the pair it is asked for, so a test can
read the dimensions of a case straight off the input.
"""

import random
from collections.abc import Iterator, Sequence
from pathlib import Path

from typing_extensions import override

from algorithm_playground.authoring import (
    Dimension,
    Fixture,
    InputGenerator,
    Problem,
    Size,
    VerificationResult,
    expect_end_of_stream,
    read_u64,
    register_problem,
    write_u64,
)
from helpers.executables import write_executable

PROBLEM_NAME = "pairs"

# The vertex count and the edge count of one input.
Pair = tuple[int, int]


def generate_pair(
    random_generator: random.Random,  # noqa: ARG001  signature fixed by the generator contract
    *,
    vertices: int,
    edges: int,
) -> Pair:
    """Return the pair of counts that was asked for."""
    return (vertices, edges)


class TwoDimensionProblem(Problem[Pair, int, None]):
    """Add the vertex count and the edge count of a pair."""

    name = PROBLEM_NAME
    description = "Add the vertex count and the edge count of a pair."
    dimensions = (
        Dimension(
            "vertices",
            description="the number of vertices",
            minimum=1,
            default_maximum=40,
        ),
        Dimension("edges", description="the number of edges", default_maximum=80),
    )
    growth_dimension = "edges"

    @override
    def serialize_input(self, data: Pair, path: Path) -> None:
        with path.open("wb") as stream:
            write_u64(stream, data[0])
            write_u64(stream, data[1])

    @override
    def deserialize_input(self, path: Path) -> Pair:
        with path.open("rb") as stream:
            pair = (read_u64(stream), read_u64(stream))
            expect_end_of_stream(stream, "The input file")
        return pair

    @override
    def deserialize_output(self, path: Path) -> int:
        with path.open("rb") as stream:
            total = read_u64(stream)
            expect_end_of_stream(stream, "The output file")
        return total

    @override
    def fixtures(self) -> Iterator[Fixture[Pair]]:
        yield Fixture("lonely", (1, 0), description="one vertex and no edge")
        yield Fixture("triangle", (3, 3), description="three vertices and three edges")

    @override
    def generators(self) -> Sequence[InputGenerator[Pair]]:
        return (
            InputGenerator(
                "exact",
                description="exactly the pair that was asked for",
                generate=generate_pair,
            ),
        )

    @override
    def verify(self, input_data: Pair, output: int) -> VerificationResult:
        expected = sum(input_data)
        if output == expected:
            return VerificationResult(True)
        return VerificationResult(False, message=f"expected {expected}, got {output}")

    @override
    def expected_output(self, input_data: Pair) -> int:
        return sum(input_data)


def register_two_dimension_problem() -> str:
    """Register the two-dimension problem for the rest of the test; return its name."""
    register_problem(TwoDimensionProblem)
    return PROBLEM_NAME


def add_pair(pair: Pair) -> int:
    """Add the counts, as a correct implementation of the problem does."""
    return sum(pair)


def write_pair_adder(path: Path) -> Path:
    """Write an executable that solves the two-dimension problem."""
    return write_executable(
        path,
        """\
        #!/usr/bin/env python3
        import struct, sys
        with open(sys.argv[1], "rb") as stream:
            vertices, edges = struct.unpack("<QQ", stream.read())
        with open(sys.argv[2], "wb") as stream:
            stream.write(struct.pack("<Q", vertices + edges))
        """,
    )


SIMPLE_GRAPH_NAME = "simple-graph"


def count_edges_of_a_complete_graph(vertices: int) -> int:
    """Count the edges a simple graph with ``vertices`` vertices can hold at most."""
    return vertices * (vertices - 1) // 2


class SimpleGraphProblem(TwoDimensionProblem):
    """The pair problem with coupled dimensions: no more edges than a simple graph holds."""

    name = SIMPLE_GRAPH_NAME
    description = "Add the counts of a pair that a simple graph could have."

    @override
    def check_size(self, size: Size) -> str | None:
        most = count_edges_of_a_complete_graph(size["vertices"])
        if size["edges"] > most:
            return f"a simple graph with {size['vertices']} vertices holds at most {most} edges"
        return None


def register_simple_graph_problem() -> str:
    """Register the coupled-dimension problem for the rest of the test; return its name."""
    register_problem(SimpleGraphProblem)
    return SIMPLE_GRAPH_NAME


def is_simple_graph_size(pair: Pair) -> bool:
    """Tell whether a pair of counts could be a simple graph."""
    return pair[1] <= count_edges_of_a_complete_graph(pair[0])


EXPLODING_SIZE_CHECK_NAME = "exploding-size-check"


class ExplodingSizeCheckProblem(TwoDimensionProblem):
    """The pair problem whose size check raises, to test how the commands cope."""

    name = EXPLODING_SIZE_CHECK_NAME

    @override
    def check_size(self, size: Size) -> str | None:
        message = "size check exploded"
        raise RuntimeError(message)


def register_exploding_size_check_problem() -> str:
    """Register the problem whose size check raises; return its name."""
    register_problem(ExplodingSizeCheckProblem)
    return EXPLODING_SIZE_CHECK_NAME


REJECTS_MINIMUM_NAME = "rejects-minimum"


class RejectingMinimumSizeProblem(TwoDimensionProblem):
    """The pair problem whose size check rejects its own minimum size (no edge)."""

    name = REJECTS_MINIMUM_NAME

    @override
    def check_size(self, size: Size) -> str | None:
        return "an edge is needed" if size["edges"] == 0 else None


def register_rejecting_minimum_size_problem() -> str:
    """Register the problem that rejects its minimum size; return its name."""
    register_problem(RejectingMinimumSizeProblem)
    return REJECTS_MINIMUM_NAME
