"""The Problem abstract base class and supporting dataclasses.

A :class:`Problem` is an interface. The core supplies everything generic
(running implementations, seeded random cases, failure reports, shrinking,
benchmarking, validation) and a problem supplies only what is specific to it:

* the binary formats (``serialize_input``, ``deserialize_output``);
* the cases to try (``fixtures`` and ``generators``);
* the correctness check (``verify``).

Everything else has a working default: ``expected_output``, ``check_input``,
``check_size``, ``describe_input`` and ``describe_output``, ``shrink``, ``deserialize_input``,
``deserialize_trace`` with ``operation_counts`` and ``trace_warnings``, the
frames that ``debug`` steps through (``input_output_frame`` and
``trace_frames``), and the class attributes ``dimensions``,
``growth_dimension``, ``debug_generator`` and ``operation_names``. The core has helpers for the
usual hooks: the binary format readers and writers (such as
:func:`~algorithm_playground.core.read_i32_array`),
:func:`~algorithm_playground.core.describe_sequence`, the shrinkers (such as
:func:`~algorithm_playground.core.shrink_sequence`), and
:class:`~algorithm_playground.core.StateTimeline`. A problem can live in any
package; see :func:`~algorithm_playground.core.register_problem` for how it is
found and :func:`~algorithm_playground.core.validate_problem` for how an author
checks it.
"""

import math
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar

from algorithm_playground.core._cases import Fixture, InputGenerator, InputT
from algorithm_playground.core._description import truncate_text
from algorithm_playground.core._dimensions import Dimension, Size
from algorithm_playground.core._frames import Frame

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


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The outcome of validating a single executable run.

    Args:
        passed: Whether the output is a valid answer.
        message: Why a run failed.
        focus: The place in the output where the first problem is, in the
            problem's own terms (an index, a vertex, an edge, a cell). Failure
            reports hand it to ``describe_output`` so the description can show
            that place instead of the start of a long output.
        category: A short name for the kind of wrong answer (``"too short"``,
            ``"unsorted"``). Failures of one category are reported in one
            block, and shrinking keeps a failure of the same category, so give
            one only when the kinds of failure are few and their names do not
            depend on the input.
        score: A finite number the problem assigns to the output, in the
            problem's own units (a tour length, a cover size, a compression
            ratio). Allowed on a passed and on a failed result; the problem
            names it with ``score_name``. Always stored as a ``float`` (or
            ``None``). The harness only reports it and does not know which
            direction is better.

    Raises:
        ValueError: If a failed verification has no message, a passed one
            has a focus or a category, or a score is not a finite number.
    """

    passed: bool
    _: KW_ONLY
    message: str = ""
    focus: object | None = None
    category: str = ""
    score: float | None = None

    def __post_init__(self) -> None:
        if not self.passed and not self.message:
            message = "A failed verification needs a message"
            raise ValueError(message)
        if self.passed and (self.focus is not None or self.category):
            message = "A passed verification cannot have a focus or a category"
            raise ValueError(message)
        if self.score is not None and (
            isinstance(self.score, bool)
            or not isinstance(self.score, int | float)
            or not math.isfinite(self.score)
        ):
            message = f"A score must be a finite number, not {self.score!r}"
            raise ValueError(message)
        if self.score is not None:
            object.__setattr__(self, "score", float(self.score))


class Problem(ABC, Generic[InputT, OutputT, TraceT]):
    """Abstract algorithmic problem definition.

    Concrete subclasses set the ``name`` and ``description`` class attributes,
    implement the abstract methods, and may override the optional hooks.
    Instances are created without arguments. Register the subclass with
    :func:`~algorithm_playground.core.register_problem` so that the
    command-line tool can find it.

    Class attributes:

    * ``name`` and ``description``: The name that selects the problem on the
      command line, and a one-line description.
    * ``dimensions``: The numbers that make up the size of an input, as a
      tuple of :class:`~algorithm_playground.core.Dimension` objects (a graph
      has ``vertices`` and ``edges``). The default is the one dimension
      ``size``. Every generator must accept every combination of values at or
      above the minimums of the dimensions, and may ignore or clamp a
      dimension it does not need. Startup timing, the generated test cases,
      the benchmark sizes and the ``debug`` default size all start from the
      minimums.
    * ``growth_dimension``: The name of the dimension that the growth row of a
      benchmark follows (default: the first dimension).
    * ``debug_generator``: The name of the generator that ``debug`` draws its
      input from when the user names none (default: the first generator). Name
      another when the first one makes pictures that are hard to read.
    * ``operation_names``: The keys that ``operation_counts`` returns, so that
      ``list PROBLEM`` can show what a benchmark with ``--count-operations``
      reports.
    * ``score_name``: What ``verify`` scores (``"tour length"``,
      ``"inversions"``), shown as the title of the score tables and recorded
      in reports. ``None`` (the default) means the problem never scores; a
      problem that names a score must give one for every output it verifies.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    dimensions: ClassVar[tuple[Dimension, ...]] = (Dimension("size"),)
    growth_dimension: ClassVar[str | None] = None
    debug_generator: ClassVar[str | None] = None
    operation_names: ClassVar[tuple[str, ...]] = ()
    score_name: ClassVar[str | None] = None

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
            algorithm_playground.core.BinaryFormatError:
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
        startup timing. A generator is called as
        ``generate(random_generator, **size)``, with one keyword argument per
        dimension, and must accept every combination of values at or above the
        minimums of the dimensions.

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
            when the output is wrong. When the problem declares a
            ``score_name``, the verdict carries a ``score`` for every output,
            passed or failed.
        """

    # ---- Inputs, failure reports and shrinking (optional) ---------------

    def expected_output(self, input_data: InputT) -> OutputT | None:  # noqa: ARG002  default hook, signature fixed by its overrides
        """Return a known-correct answer, or ``None`` when there is no single one.

        Failure reports show it next to the actual output. It is only for
        display; ``verify`` decides whether a run passed.

        Args:
            input_data: The input.

        Returns:
            The answer. The default returns ``None``.
        """
        return None

    def check_input(self, input_data: InputT) -> str | None:  # noqa: ARG002  default hook, signature fixed by its overrides
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

    def check_size(self, size: Size) -> str | None:  # noqa: ARG002  default hook, signature fixed by its overrides
        """Say why a combination of dimension values is not one the problem accepts, as text, or return ``None``.

        A rule that couples the dimensions (a simple graph holds at most
        ``vertices * (vertices - 1) / 2`` edges) is written here once. It is
        consulted for every size the command line or a caller names, for the
        startup size, and for every size the test plan draws, which redraws a
        rejected one. Any text, even empty, is a rejection. The minimum size must be accepted.

        Args:
            size: The value of each dimension, all at or above the minimums.

        Returns:
            The reason the size is not accepted, or ``None``. The default
            accepts every size at or above the minimums.
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

    def describe_output(
        self,
        output: OutputT,
        *,
        limit: int,
        focus: object | None = None,  # noqa: ARG002  default hook, signature fixed by its overrides
    ) -> str:
        """Describe an output for a failure report.

        :func:`~algorithm_playground.core.describe_sequence` shows a window
        around ``focus`` when it is an index, and an override passes it on only
        then.

        Args:
            output: The output, actual or expected.
            limit: About the most characters the text may have.
            focus: The focus that ``verify`` named in its
                :class:`~algorithm_playground.core.VerificationResult`, or
                ``None``. It is passed for the actual output and for the expected
                one; a hook that cannot use it ignores it.

        Returns:
            The text. The default is the ``repr``, truncated.
        """
        return truncate_text(repr(output), limit)

    def shrink(self, input_data: InputT) -> Iterator[InputT]:  # noqa: ARG002  default hook, signature fixed by its overrides
        """Return smaller or simpler variants of a failing input, most aggressive first.

        The harness runs the candidates against the failing implementation and
        keeps the first one that still fails the same way, then asks again for
        variants of that one, until none fails. Candidates that ``check_input``
        rejects are skipped. The shrinkers of the core, such as
        :func:`~algorithm_playground.core.shrink_sequence`, are the building blocks.

        Args:
            input_data: The failing input.

        Returns:
            An iterator of candidates. The default yields nothing, which turns
            shrinking off.
        """
        return iter(())

    def deserialize_input(self, path: Path) -> InputT:
        """Read an input file written by ``serialize_input``.

        It is what lets ``debug --input-file`` run a saved input (``test
        --save-failing-inputs`` writes them), because the check of the output
        needs the input itself.

        Args:
            path: The input file.

        An override returns the input and raises
        :class:`~algorithm_playground.core.BinaryFormatError` if
        the file is malformed.

        Raises:
            NotImplementedError: By default, to say the problem cannot read its
                inputs.
        """
        message = (
            f"The problem '{self.name}' does not implement deserialize_input, "
            "so it cannot read an input file"
        )
        raise NotImplementedError(message)

    # ---- Traces (optional) ----------------------------------------------

    def deserialize_trace(self, path: Path, input_data: InputT) -> TraceT | None:  # noqa: ARG002  default hook, signature fixed by its overrides
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
            which says the problem has no trace format. An override raises
            :class:`~algorithm_playground.core.BinaryFormatError`
            if the file is malformed. The runner treats that as "no trace" and
            records the reason; any other exception is recorded the same way,
            naming this hook.
        """
        return None

    def operation_counts(
        self,
        input_data: InputT,  # noqa: ARG002  default hook, signature fixed by its overrides
        output: OutputT,  # noqa: ARG002  default hook, signature fixed by its overrides
        trace: TraceT,  # noqa: ARG002  default hook, signature fixed by its overrides
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

    def trace_warnings(
        self,
        input_data: InputT,  # noqa: ARG002  default hook, signature fixed by its overrides
        output: OutputT,  # noqa: ARG002  default hook, signature fixed by its overrides
        trace: TraceT,  # noqa: ARG002  default hook, signature fixed by its overrides
    ) -> Sequence[str]:
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

    def input_output_frame(self, input_data: InputT, output: OutputT) -> Frame | None:  # noqa: ARG002  default hook, signature fixed by its overrides
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

    def trace_frames(
        self,
        input_data: InputT,  # noqa: ARG002  default hook, signature fixed by its overrides
        output: OutputT,  # noqa: ARG002  default hook, signature fixed by its overrides
        trace: TraceT,  # noqa: ARG002  default hook, signature fixed by its overrides
    ) -> Sequence[Frame]:
        """Return the steps of a trace as frames, in order.

        The stepper plays them back; the problem only describes them. Return a
        :class:`~algorithm_playground.core.FrameSequence` when building
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
