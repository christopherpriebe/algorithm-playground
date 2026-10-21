``algorithm_playground.authoring``
==================================

The stable surface for writing a problem. A problem author imports everything
from this one module; see :doc:`../writing-a-problem` for a walk-through and
:doc:`../extending` for the interface.

.. automodule:: algorithm_playground.authoring

What it exports
---------------

The interface and its value types
   :class:`~algorithm_playground.core.problem.Problem`,
   :class:`~algorithm_playground.core.cases.Fixture`,
   :class:`~algorithm_playground.core.cases.InputGenerator`,
   :class:`~algorithm_playground.core.problem.VerificationResult`,
   :class:`~algorithm_playground.core.frames.Frame`,
   :class:`~algorithm_playground.core.frames.FrameSequence`.

Registration
   :func:`~algorithm_playground.core.registry.register_problem`.

The binary formats
   :class:`~algorithm_playground.core.binary_format.BinaryFormatError`; the
   scalars :func:`~algorithm_playground.core.binary_format.read_u8`,
   :func:`~algorithm_playground.core.binary_format.read_u32`,
   :func:`~algorithm_playground.core.binary_format.read_u64`,
   :func:`~algorithm_playground.core.binary_format.read_i32`,
   :func:`~algorithm_playground.core.binary_format.read_i64`,
   :func:`~algorithm_playground.core.binary_format.read_f64` and their ``write_``
   counterparts; the arrays
   :func:`~algorithm_playground.core.binary_format.read_i32_array`,
   :func:`~algorithm_playground.core.binary_format.read_u32_array`,
   :func:`~algorithm_playground.core.binary_format.read_i64_array`,
   :func:`~algorithm_playground.core.binary_format.read_f64_array` and their
   ``write_`` counterparts;
   :func:`~algorithm_playground.core.binary_format.expect_end_of_stream`;
   :func:`~algorithm_playground.core.binary_format.read_records`,
   :func:`~algorithm_playground.core.binary_format.read_record_bytes` and
   :func:`~algorithm_playground.core.binary_format.read_sections` for traces.

Describing and shrinking
   :func:`~algorithm_playground.core.description.describe_sequence`,
   :func:`~algorithm_playground.core.description.truncate_text`,
   :func:`~algorithm_playground.core.shrinking.shrink_sequence`,
   :func:`~algorithm_playground.core.shrinking.shrink_integers`,
   :func:`~algorithm_playground.core.shrinking.shrink_integer_sequence`,
   :func:`~algorithm_playground.core.shrinking.shrink_integer`,
   :func:`~algorithm_playground.core.shrinking.shrink_each`,
   :func:`~algorithm_playground.core.shrinking.shrink_fields`,
   :func:`~algorithm_playground.core.shrinking.distinct`.

Replaying events
   :class:`~algorithm_playground.core.replay.StateTimeline`.

Charts for frames
   :class:`~algorithm_playground.visualization.charts.BarHighlight`,
   :func:`~algorithm_playground.visualization.charts.render_bar_chart`,
   :func:`~algorithm_playground.visualization.charts.render_side_by_side_bar_charts`.

The validation kit
   :func:`~algorithm_playground.core.validation.validate_problem`,
   :func:`~algorithm_playground.core.validation.assert_valid_problem`.
