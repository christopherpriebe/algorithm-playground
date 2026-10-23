``algorithm_playground.authoring``
==================================

The stable surface for writing a problem. A problem author imports everything
from this one module; see :doc:`../writing-a-problem` for a walk-through and
:doc:`../extending` for the interface.

.. automodule:: algorithm_playground.authoring
   :no-members:

What it exports
---------------

The interface and its value types
   :class:`~algorithm_playground.core.Problem`,
   :class:`~algorithm_playground.core.Dimension`,
   :class:`~algorithm_playground.core.Size`,
   :class:`~algorithm_playground.core.Fixture`,
   :class:`~algorithm_playground.core.InputGenerator`,
   :class:`~algorithm_playground.core.VerificationResult`,
   :class:`~algorithm_playground.core.Frame`,
   :class:`~algorithm_playground.core.FrameSequence`.

Errors
   :class:`~algorithm_playground.core.AlgorithmPlaygroundError`, the base of
   every exception class the package defines.

Registration
   :func:`~algorithm_playground.core.register_problem`.

The binary formats
   :class:`~algorithm_playground.core.BinaryFormatError`; the
   scalars :func:`~algorithm_playground.core.read_u8`,
   :func:`~algorithm_playground.core.read_u32`,
   :func:`~algorithm_playground.core.read_u64`,
   :func:`~algorithm_playground.core.read_i32`,
   :func:`~algorithm_playground.core.read_i64`,
   :func:`~algorithm_playground.core.read_f64` and their ``write_``
   counterparts; the arrays
   :func:`~algorithm_playground.core.read_i32_array`,
   :func:`~algorithm_playground.core.read_u32_array`,
   :func:`~algorithm_playground.core.read_i64_array`,
   :func:`~algorithm_playground.core.read_f64_array` and their
   ``write_`` counterparts;
   :func:`~algorithm_playground.core.expect_end_of_stream`;
   :func:`~algorithm_playground.core.read_records`,
   :func:`~algorithm_playground.core.read_record_bytes` and
   :func:`~algorithm_playground.core.read_sections` for traces.

Describing and shrinking
   :func:`~algorithm_playground.core.describe_sequence`,
   :func:`~algorithm_playground.core.truncate_text`,
   :func:`~algorithm_playground.core.shrink_sequence`,
   :func:`~algorithm_playground.core.shrink_integers`,
   :func:`~algorithm_playground.core.shrink_integer_sequence`,
   :func:`~algorithm_playground.core.shrink_integer`,
   :func:`~algorithm_playground.core.shrink_each`,
   :func:`~algorithm_playground.core.shrink_fields`,
   :func:`~algorithm_playground.core.deduplicate_candidates`.

Replaying events
   :class:`~algorithm_playground.core.StateTimeline`.

Charts for frames
   :class:`~algorithm_playground.visualization.BarHighlight`,
   :func:`~algorithm_playground.visualization.render_bar_chart`,
   :func:`~algorithm_playground.visualization.render_side_by_side_bar_charts`.

The validation kit
   :func:`~algorithm_playground.core.validate_problem`,
   :func:`~algorithm_playground.core.assert_valid_problem`.
