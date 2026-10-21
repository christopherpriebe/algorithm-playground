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

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar

from algorithm_playground.core.cases import Fixture, InputGenerator, InputT
from algorithm_playground.core.description import truncate_text
from algorithm_playground.core.frames import Frame

__all__ = [
    "AnyProblem",
    "InputT",
    "OutputT",
    "Problem",
    "TraceT",
    "VerificationResult",
    "has_input_reader",
    "has_trace_format",
]

OutputT = TypeVar("OutputT")
TraceT = TypeVar("TraceT")


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of validating a single executable run.

    Args:
        passed: Whether the output is a valid answer.
        message: Why a run failed.
        focus: The position in the output where the first problem is, so that
            failure reports show a window around it instead of the start of a
            long output (see
            :func:`~algorithm_playground.core.description.describe_sequence`).
        category: A short name for the kind of wrong answer (``"too short"``,
            ``"unsorted"``). Failures of one category are reported in one
            block, and shrinking keeps a failure of the same category, so give
            one only when the kinds of failure are few and their names do not
            depend on the input.
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

    Class attributes:

    * ``name`` and ``description``: The name that selects the problem on the
      command line, and a one-line description.
    * ``minimum_size``: The smallest size at which every generator returns a
      valid input (default ``0``). Startup timing, the generated test cases,
      the benchmark sizes and the ``debug`` default size all start from it.
    * ``debug_generator``: The name of the generator that ``debug`` draws its
      input from when the user names none (default: the first generator). Name
      another when the first one makes pictures that are hard to read.
    * ``operation_names``: The keys that ``operation_counts`` returns, so that
      ``list PROBLEM`` can show what a benchmark with ``--count-operations``
      reports.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    minimum_size: ClassVar[int] = 0
    debug_generator: ClassVar[str | None] = None
    operation_names: ClassVar[tuple[str, ...]] = ()

    # ---- Binary I/O (required) ----------------------------------------

    @abstractmethod
    def serialize_input(self, data: InputT, path: Path) -> None:
        """Write an input to a file in the problem's binary input format.

        Args:
            data: The input.
            path: The file to write.
        """

    @abstractmethod
    def deserialize_output(self, path: Path) -> OutputT:
        """Read the output that an executable wrote.

        Args:
            path: The output file.

        Returns:
            The output.

        Raises:
            algorithm_playground.core.binary_format.BinaryFormatError:
                If the file does not match the problem's output format. The
                runner reports that as a failed run.
        """

    # ---- Cases (required) ----------------------------------------------

    @abstractmethod
    def fixtures(self) -> Iterable[Fixture[InputT]]:
        """Return the curated, named inputs: small cases where bugs are easy to understand.

        Returns:
            The fixtures, each with a unique non-empty name.
        """

    @abstractmethod
    def generators(self) -> Sequence[InputGenerator[InputT]]:
        """Return the named, seeded input generators.

        The first one is the default: ``benchmark`` uses it, and so does the
        startup timing. Every generator must accept each size from
        :attr:`minimum_size` up.

        Returns:
            The generators, each with a unique name.
        """

    # ---- Verification (required) ---------------------------------------

    @abstractmethod
    def verify(self, input_data: InputT, output: OutputT) -> VerificationResult:
        """Check whether an output is a valid answer for an input.

        Args:
            input_data: The input the executable ran on.
            output: The output the executable wrote.

        Returns:
            The verdict, with a message and optionally a focus and a category
            when the output is wrong.
        """

    # ---- Inputs, failure reports and shrinking (optional) ---------------

    def expected_output(self, input_data: InputT) -> OutputT | None:
        """Return a known-correct answer, or ``None`` when there is no single one.

        Failure reports show it next to the actual output. It is only for
        display; ``verify`` decides whether a run passed.

        Args:
            input_data: The input.

        Returns:
            The answer. The default returns ``None``.
        """
        return None

    def check_input(self, input_data: InputT) -> str | None:
        """Say why an input is not valid, or return ``None`` when it is.

        A rule that every input must keep (an array that has to be sorted, a
        target that has to occur in it) is written here once. Validation applies
        it to fixtures, generated samples and shrink candidates, and the
        shrinker skips the candidates it rejects, so ``shrink`` may be generous.

        Args:
            input_data: The input to check.

        Returns:
            The reason the input is invalid, or ``None``. The default accepts
            everything.
        """
        return None

    def describe_input(self, input_data: InputT, *, limit: int) -> str:
        """Describe an input for a failure report.

        Args:
            input_data: The input.
            limit: About the most characters the text may have.

        Returns:
            The text. The default is the ``repr``, truncated.
        """
        return truncate_text(repr(input_data), limit)

    def describe_output(self, output: OutputT, *, limit: int, focus: int | None = None) -> str:
        """Describe an output for a failure report.

        :func:`~algorithm_playground.core.description.describe_sequence` shows
        a window around ``focus``.

        Args:
            output: The output, actual or expected.
            limit: About the most characters the text may have.
            focus: The position that ``verify`` named in
                :attr:`VerificationResult.focus`, or ``None``. It is passed
                for the actual output and for the expected one; a hook that
                cannot use it ignores it.

        Returns:
            The text. The default is the ``repr``, truncated.
        """
        return truncate_text(repr(output), limit)

    def shrink(self, input_data: InputT) -> Iterator[InputT]:
        """Yield smaller or simpler variants of a failing input, most aggressive first.

        The harness runs the candidates against the failing implementation and
        keeps the first one that still fails the same way, then asks again for
        variants of that one, until none fails. Candidates that ``check_input``
        rejects are skipped. :mod:`~algorithm_playground.core.shrinking` has
        the building blocks.

        Args:
            input_data: The failing input.

        Yields:
            Candidates. The default yields nothing, which turns shrinking off.
        """
        return iter(())

    def deserialize_input(self, path: Path) -> InputT:
        """Read an input file written by ``serialize_input``.

        It is what lets ``debug --input-file`` run a saved input (``test
        --save-failing-inputs`` writes them), because the check of the output
        needs the input itself.

        Args:
            path: The input file.

        Returns:
            The input.

        Raises:
            algorithm_playground.core.binary_format.BinaryFormatError:
                If the file is malformed.
            NotImplementedError: By default, to say the problem cannot read its
                inputs.
        """
        raise NotImplementedError(
            f"The problem '{self.name}' does not implement deserialize_input, "
            "so it cannot read an input file"
        )

    # ---- Traces (optional) ----------------------------------------------

    def deserialize_trace(self, path: Path, input_data: InputT) -> TraceT | None:
        """Read the trace that an executable wrote.

        A trace format that refers to positions in the input (an event that
        names an index) is validated against ``input_data`` here, and one that
        records only changes can start from it. The runner calls this only for
        a file that exists and is not empty. The hooks that use the trace
        afterwards (``operation_counts``, ``trace_warnings`` and
        ``trace_frames``) receive the input and the output as well, in the
        order input, output, trace, so a trace need not carry copies of them.

        Args:
            path: The trace file.
            input_data: The input the executable ran on.

        Returns:
            The trace, or ``None`` if the file otherwise indicates the
            executable did not produce one. The default returns ``None``,
            which says the problem has no trace format.

        Raises:
            algorithm_playground.core.binary_format.BinaryFormatError:
                If the file is malformed. The runner treats that as "no trace"
                and records the reason; any other exception is recorded the
                same way, naming this hook.
        """
        return None

    def operation_counts(
        self, input_data: InputT, output: OutputT, trace: TraceT
    ) -> Mapping[str, int] | None:
        """Count the operations a trace records, by name.

        ``benchmark --count-operations`` collects these per size and estimates
        how each count grows. The names (``compares``, ``swaps``) are the
        problem's own. A trace that says no operation was done returns zeros;
        ``None`` means the trace does not say how many were done.

        Args:
            input_data: The input the executable ran on.
            output: The output the executable wrote.
            trace: The trace.

        Returns:
            The count of each operation, or ``None``. The default returns
            ``None``.
        """
        return None

    def trace_warnings(self, input_data: InputT, output: OutputT, trace: TraceT) -> Sequence[str]:
        """Return the inconsistencies found inside a trace, such as parts that disagree.

        ``debug`` shows them under every frame of the trace. They are warnings,
        not failures: the run is judged by ``verify`` alone.

        Args:
            input_data: The input the executable ran on.
            output: The output the executable wrote.
            trace: The trace.

        Returns:
            One message per inconsistency. The default finds none.
        """
        return ()

    # ---- Visualization (optional) ----------------------------------------

    def input_output_frame(self, input_data: InputT, output: OutputT) -> Frame | None:
        """Return a view of the input and the output.

        ``debug`` shows it when the implementation wrote no usable trace, and
        when the trace has no frames.

        Args:
            input_data: The input.
            output: The output.

        Returns:
            The frame, or ``None`` when there is none to show. The default
            returns ``None``.
        """
        return None

    def trace_frames(self, input_data: InputT, output: OutputT, trace: TraceT) -> Sequence[Frame]:
        """Return the steps of a trace as frames, in order.

        The stepper plays them back; the problem only describes them. Return a
        :class:`~algorithm_playground.core.frames.FrameSequence` when building
        every frame up front would be slow.

        Args:
            input_data: The input the executable ran on.
            output: The output the executable wrote.
            trace: The trace.

        Returns:
            The frames, or nothing when the trace has none. The default
            returns nothing.
        """
        return ()


# A problem whose input, output and trace types are not known where it is handled: the engines,
# the registry and the command-line front end work with problems of every type.
AnyProblem = Problem[Any, Any, Any]


def has_trace_format(problem: AnyProblem) -> bool:
    """Say whether a problem defines a trace format, that is, overrides ``deserialize_trace``.

    Args:
        problem: The problem.

    Returns:
        ``True`` if the problem overrides ``deserialize_trace``.
    """
    return type(problem).deserialize_trace is not Problem.deserialize_trace


def has_input_reader(problem: AnyProblem) -> bool:
    """Say whether a problem can read an input file, that is, overrides ``deserialize_input``.

    Args:
        problem: The problem.

    Returns:
        ``True`` if the problem overrides ``deserialize_input``.
    """
    return type(problem).deserialize_input is not Problem.deserialize_input
