"""The stable surface for writing a problem.

A problem author imports everything from this one module::

    from algorithm_playground.authoring import Problem, register_problem, ...

Everything here is part of the public API and changes only with a deliberate
version bump: the :class:`~algorithm_playground.core.Problem` interface with its
value types, the registration decorator, the helpers that read and write the
binary formats, the building blocks for shrinking, describing and replaying, the
chart renderers that turn data into the text of a
:class:`~algorithm_playground.core.Frame`, and the validation kit. The rest of
the package (the engines, the registry, the command-line front end) is not meant
for problem authors. See the guide :doc:`/writing-a-problem`.
"""

from algorithm_playground.core._binary_format import (
    BinaryFormatError,
    expect_end_of_stream,
    read_f64,
    read_f64_array,
    read_i32,
    read_i32_array,
    read_i64,
    read_i64_array,
    read_record_bytes,
    read_records,
    read_sections,
    read_u8,
    read_u32,
    read_u32_array,
    read_u64,
    write_f64,
    write_f64_array,
    write_i32,
    write_i32_array,
    write_i64,
    write_i64_array,
    write_u8,
    write_u32,
    write_u32_array,
    write_u64,
)
from algorithm_playground.core._cases import Fixture, InputGenerator
from algorithm_playground.core._description import describe_sequence, truncate_text
from algorithm_playground.core._dimensions import Dimension, Size
from algorithm_playground.core._errors import AlgorithmPlaygroundError
from algorithm_playground.core._frames import Frame, FrameSequence
from algorithm_playground.core._problem import Problem, VerificationResult
from algorithm_playground.core._registry import register_problem
from algorithm_playground.core._replay import StateTimeline
from algorithm_playground.core._shrinking import (
    deduplicate_candidates,
    shrink_each,
    shrink_fields,
    shrink_integer,
    shrink_integer_sequence,
    shrink_integers,
    shrink_sequence,
)
from algorithm_playground.core._validation import assert_valid_problem, validate_problem
from algorithm_playground.visualization._charts import (
    BarHighlight,
    render_bar_chart,
    render_side_by_side_bar_charts,
)

__all__ = [
    "AlgorithmPlaygroundError",
    "BarHighlight",
    "BinaryFormatError",
    "Dimension",
    "Fixture",
    "Frame",
    "FrameSequence",
    "InputGenerator",
    "Problem",
    "Size",
    "StateTimeline",
    "VerificationResult",
    "assert_valid_problem",
    "deduplicate_candidates",
    "describe_sequence",
    "expect_end_of_stream",
    "read_f64",
    "read_f64_array",
    "read_i32",
    "read_i32_array",
    "read_i64",
    "read_i64_array",
    "read_record_bytes",
    "read_records",
    "read_sections",
    "read_u8",
    "read_u32",
    "read_u32_array",
    "read_u64",
    "register_problem",
    "render_bar_chart",
    "render_side_by_side_bar_charts",
    "shrink_each",
    "shrink_fields",
    "shrink_integer",
    "shrink_integer_sequence",
    "shrink_integers",
    "shrink_sequence",
    "truncate_text",
    "validate_problem",
    "write_f64",
    "write_f64_array",
    "write_i32",
    "write_i32_array",
    "write_i64",
    "write_i64_array",
    "write_u8",
    "write_u32",
    "write_u32_array",
    "write_u64",
]
