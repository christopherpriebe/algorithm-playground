"""The Problem abstract base class and supporting dataclasses.

A :class:`Problem` is an interface. The core supplies everything generic
(running implementations, seeded random cases, failure reports, shrinking,
benchmarking, validation) and a problem supplies only what is specific to it:

* the binary formats (``serialize_input``, ``deserialize_output``);
* the cases to try (``fixtures`` and ``generators``);
* the correctness check (``verify``).

Everything else has a working default: ``expected_output``, ``check_input``,
``describe_input`` and ``describe_output``, ``shrink``, ``deserialize_input``,
``deserialize_trace`` with ``operation_counts`` and ``trace_warnings``, the
frames that ``debug`` steps through (``input_output_frame`` and
``trace_frames``), and the class attributes ``minimum_size``,
``debug_generator`` and ``operation_names``. Helpers for the usual hooks live
next to this module: :mod:`~algorithm_playground.core.binary_format`,
:mod:`~algorithm_playground.core.description`,
:mod:`~algorithm_playground.core.shrinking` and
:mod:`~algorithm_playground.core.replay`. A problem can live in any package; see
:mod:`algorithm_playground.core.registry` for how it is found and
:func:`~algorithm_playground.core.validation.validate_problem` for how an
author checks it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar

from algorithm_playground.core.cases import Fixture, InputGenerator, InputT
from algorithm_playground.core.description import truncate_text
from algorithm_playground.core.frames import Frame

OutputT = TypeVar("OutputT")
TraceT = TypeVar("TraceT")


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of validating a single executable run.

    ``message`` says why a run failed. ``focus`` is optional: the position in
    the output where the first problem is, so that failure reports show a window
    around it instead of the start of a long output (see
    :func:`~algorithm_playground.core.description.describe_sequence`).
    ``category`` is optional too: a short name for the kind of wrong answer
    (``"too short"``, ``"unsorted"``). Failures of one category are reported in
    one block, and shrinking keeps a failure of the same category, so give one
    only when the kinds of failure are few and their names do not depend on the
    input.
    """

    passed: bool
    message: str = ""
    focus: int | None = None
    category: str = ""


class Problem(ABC, Generic[InputT, OutputT, TraceT]):
    """Abstract algorithmic problem definition.

    Concrete subclasses set the ``name`` and ``description`` class attributes,
    implement the abstract methods, and may override the optional hooks.
    Instances are created without arguments. Register the subclass with
    :func:`~algorithm_playground.core.registry.register_problem` so that the
    command-line tool can find it.

    Three more class attributes are optional. ``minimum_size`` is the smallest
    size at which every generator returns a valid input (default ``0``);
    startup timing, the generated test cases, the benchmark sizes and the
    ``debug`` default size all start from it. ``debug_generator`` names the
    generator that ``debug`` draws its input from when the user names none
    (default: the first generator), which suits a problem whose first
    generator makes pictures that are hard to read. ``operation_names`` lists
    the keys that ``operation_counts`` returns, so that ``list PROBLEM`` can
    show what a benchmark with ``--count-operations`` reports.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    minimum_size: ClassVar[int] = 0
    debug_generator: ClassVar[str | None] = None
    operation_names: ClassVar[tuple[str, ...]] = ()

    # ---- Binary I/O (required) ----------------------------------------

    @abstractmethod
    def serialize_input(self, data: InputT, path: Path) -> None:
        """Write ``data`` to ``path`` in the problem's binary input format."""

    @abstractmethod
    def deserialize_output(self, path: Path) -> OutputT:
        """Read and return the executable's output from ``path``.

        Raise :class:`~algorithm_playground.core.binary_format.BinaryFormatError`
        if the file does not match the problem's output format; the runner
        reports that as a failed run.
        """

    # ---- Cases (required) ----------------------------------------------

    @abstractmethod
    def fixtures(self) -> Iterable[Fixture[InputT]]:
        """Return the curated, named inputs: small cases where bugs are easy to understand."""

    @abstractmethod
    def generators(self) -> Sequence[InputGenerator[InputT]]:
        """Return the named, seeded input generators.

        The first one is the default: ``benchmark`` uses it, and so does the
        startup timing. Every generator must accept each size from
        :attr:`minimum_size` up.
        """

    # ---- Verification (required) ---------------------------------------

    @abstractmethod
    def verify(self, input_data: InputT, output: OutputT) -> VerificationResult:
        """Check whether ``output`` is a valid answer for ``input_data``."""

    # ---- Inputs, failure reports and shrinking (optional) ---------------

    def expected_output(self, input_data: InputT) -> OutputT | None:
        """Return a known-correct answer for ``input_data``, or ``None`` when there is no single one.

        Failure reports show it next to the actual output. It is only for
        display; ``verify`` decides whether a run passed.
        """
        return None

    def check_input(self, input_data: InputT) -> str | None:
        """Say why ``input_data`` is not a valid input, or return ``None`` when it is.

        A rule that every input must keep (an array that has to be sorted, a
        target that has to occur in it) is written here once. Validation applies
        it to fixtures, generated samples and shrink candidates, and the
        shrinker skips the candidates it rejects, so ``shrink`` may be generous.
        The default accepts everything.
        """
        return None

    def describe_input(self, input_data: InputT, *, limit: int) -> str:
        """Describe ``input_data`` for a failure report in at most about ``limit`` characters."""
        return truncate_text(repr(input_data), limit)

    def describe_output(self, output: OutputT, *, limit: int, focus: int | None = None) -> str:
        """Describe ``output`` for a failure report in at most about ``limit`` characters.

        ``focus`` is the position that ``verify`` named in
        :attr:`VerificationResult.focus`, or ``None``. It is passed for the
        actual output and for the expected one; a hook that cannot use it
        ignores it. :func:`~algorithm_playground.core.description.describe_sequence`
        shows a window around it.
        """
        return truncate_text(repr(output), limit)

    def shrink(self, input_data: InputT) -> Iterator[InputT]:
        """Yield smaller or simpler variants of a failing ``input_data``, most aggressive first.

        The harness runs the candidates against the failing implementation and
        keeps the first one that still fails the same way, then asks again for
        variants of that one, until none fails. Candidates that ``check_input``
        rejects are skipped. The default yields nothing, which turns shrinking
        off. :mod:`~algorithm_playground.core.shrinking` has the building
        blocks.
        """
        return iter(())

    def deserialize_input(self, path: Path) -> InputT:
        """Read an input file written by ``serialize_input`` and return the input.

        It is what lets ``debug --input-file`` run a saved input (``test
        --save-failing-inputs`` writes them), because the check of the output
        needs the input itself. Raise
        :class:`~algorithm_playground.core.binary_format.BinaryFormatError` for a
        malformed file. The default says the problem cannot read its inputs.
        """
        raise NotImplementedError(
            f"The problem '{self.name}' does not implement deserialize_input, "
            "so it cannot read an input file"
        )

    # ---- Traces (optional) ----------------------------------------------

    def deserialize_trace(self, path: Path, input_data: InputT) -> TraceT | None:
        """Read and return a trace from ``path``.

        ``input_data`` is the input the executable ran on. A trace format that
        refers to positions in the input (an event that names an index) is
        validated against it here, and one that records only changes can
        start from it. The runner calls this only for a file that exists and
        is not empty, so a missing or empty file never gets here. Return
        ``None`` if the file otherwise indicates the executable did not
        produce a trace. Raise
        :class:`~algorithm_playground.core.binary_format.BinaryFormatError` if the
        file is malformed; the runner treats that as "no trace" and records
        the reason (any other exception is recorded the same way, naming this
        hook). The default says the problem has no trace format.

        The hooks that use the trace afterwards (``operation_counts``,
        ``trace_warnings`` and ``trace_frames``) receive the input and the
        output as well, in the order input, output, trace, so a trace need not
        carry copies of them.
        """
        return None

    def operation_counts(
        self, input_data: InputT, output: OutputT, trace: TraceT
    ) -> Mapping[str, int] | None:
        """Count the operations a trace records, by name, or return ``None`` when it records none.

        ``benchmark --count-operations`` collects these per size and estimates
        how each count grows. The names (``compares``, ``swaps``) are the
        problem's own. Return ``None``, as the default does, when the trace
        does not say how many operations were done; a trace that says none
        were done returns zeros instead.
        """
        return None

    def trace_warnings(self, input_data: InputT, output: OutputT, trace: TraceT) -> Sequence[str]:
        """Return the inconsistencies found inside ``trace``, such as parts that disagree.

        ``debug`` shows them under every frame of the trace. They are warnings,
        not failures: the run is judged by ``verify`` alone. The default finds
        none.
        """
        return ()

    # ---- Visualization (optional) ----------------------------------------

    def input_output_frame(self, input_data: InputT, output: OutputT) -> Frame | None:
        """Return a view of the input and the output, or ``None`` when there is none to show.

        ``debug`` shows it when the implementation wrote no usable trace, and
        when the trace has no frames.
        """
        return None

    def trace_frames(self, input_data: InputT, output: OutputT, trace: TraceT) -> Sequence[Frame]:
        """Return the steps of ``trace`` as frames, in order, or nothing when it has none.

        The stepper plays them back; the problem only describes them. Return a
        :class:`~algorithm_playground.core.frames.FrameSequence` when building
        every frame up front would be slow.
        """
        return ()


def has_trace_format(problem: Problem[Any, Any, Any]) -> bool:
    """Whether ``problem`` defines a trace format, that is, overrides ``deserialize_trace``."""
    return type(problem).deserialize_trace is not Problem.deserialize_trace


def has_input_reader(problem: Problem[Any, Any, Any]) -> bool:
    """Whether ``problem`` can read an input file, that is, overrides ``deserialize_input``."""
    return type(problem).deserialize_input is not Problem.deserialize_input
