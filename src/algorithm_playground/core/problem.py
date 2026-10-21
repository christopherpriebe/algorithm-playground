"""The Problem abstract base class and supporting dataclasses.

A `Problem` defines the per-problem contract that the harness uses to drive
arbitrary user executables. Each subclass owns the binary input/output/trace
layout, a set of test fixtures, a benchmark input generator, a verifier, and
optional terminal visualizers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Generic, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")
TraceT = TypeVar("TraceT")


@dataclass(frozen=True)
class TestCase(Generic[InputT]):
    """A named fixture used for functional verification."""

    __test__: ClassVar[bool] = False  # Tell pytest not to collect this as a test class.

    name: str
    input_data: InputT


@dataclass(frozen=True)
class BenchmarkCase(Generic[InputT]):
    """A generated benchmark input at a particular size."""

    name: str
    size: int
    input_data: InputT


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of validating a single executable run."""

    passed: bool
    message: str = ""


class Problem(ABC, Generic[InputT, OutputT, TraceT]):
    """Abstract algorithmic problem definition.

    Concrete subclasses set the ``name`` and ``description`` class attributes
    and implement the abstract methods below. Register the subclass with
    :func:`algorithm_playground.core.registry.register_problem` so that the
    CLI can discover it.
    """

    name: ClassVar[str]
    description: ClassVar[str]

    # ---- Binary I/O ----------------------------------------------------

    @abstractmethod
    def serialize_input(self, data: InputT, path: Path) -> None:
        """Write ``data`` to ``path`` in the problem's binary input format."""

    @abstractmethod
    def deserialize_output(self, path: Path) -> OutputT:
        """Read and return the executable's output from ``path``.

        Raise :class:`~algorithm_playground.core.binary_io.BinaryFormatError`
        if the file does not match the problem's output format; the runner
        reports that as a failed run.
        """

    @abstractmethod
    def deserialize_trace(self, path: Path) -> TraceT | None:
        """Read and return a trace from ``path``.

        Return ``None`` if the file is empty or otherwise indicates the
        executable did not produce a trace. Raise
        :class:`~algorithm_playground.core.binary_io.BinaryFormatError` if the
        file is malformed; the runner treats that as "no trace" and records
        the reason.
        """

    # ---- Cases ---------------------------------------------------------

    @abstractmethod
    def test_cases(self) -> Iterator[TestCase[InputT]]:
        """Yield the curated functional test fixtures for this problem."""

    @abstractmethod
    def benchmark_case(self, seed: int, size: int) -> BenchmarkCase[InputT]:
        """Generate a single seeded benchmark input of the requested size."""

    def baseline_case(self, seed: int) -> BenchmarkCase[InputT]:
        """Return the smallest valid input, used to measure startup time.

        ``benchmark`` times the executable on this input to estimate how much
        of each run is fixed cost (process startup, file I/O) rather than
        algorithm work. Defaults to a size-0 benchmark case; override it if
        size 0 is not a valid input for the problem.
        """
        return self.benchmark_case(seed=seed, size=0)

    # ---- Verification --------------------------------------------------

    @abstractmethod
    def verify(self, input_data: InputT, output: OutputT) -> VerificationResult:
        """Check whether ``output`` is a valid answer for ``input_data``."""

    # ---- Visualization (optional, default no-op) -----------------------

    def visualize_io(self, input_data: InputT, output: OutputT) -> None:
        """Render the input and output side-by-side. Default: no-op."""

    def visualize_trace(
        self,
        trace: TraceT,
        *,
        auto_advance: bool = False,
        delay_milliseconds: int = 250,
    ) -> None:
        """Render a trace interactively. Default: no-op.

        Implementations that present an interactive stepper should honor
        ``auto_advance`` and ``delay_milliseconds`` so the CLI's ``debug``
        command can drive playback.
        """
