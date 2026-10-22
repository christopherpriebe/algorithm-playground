``algorithm_playground.visualization``
======================================

.. automodule:: algorithm_playground.visualization
   :no-members:

Terminal-based rendering helpers used by problem implementations and the
``debug`` command.

Charts
------

.. autoclass:: algorithm_playground.visualization.AxisScale
.. autoclass:: algorithm_playground.visualization.BarHighlight
.. autoclass:: algorithm_playground.visualization.ChartSeries
.. autofunction:: algorithm_playground.visualization.render_bar_chart
.. autofunction:: algorithm_playground.visualization.render_side_by_side_bar_charts
.. autofunction:: algorithm_playground.visualization.render_line_chart

Stepper
-------

.. autoclass:: algorithm_playground.visualization.StepperOptions
.. autoclass:: algorithm_playground.visualization.StepperState
.. autofunction:: algorithm_playground.visualization.compute_next_state
.. autofunction:: algorithm_playground.visualization.parse_jump_target
.. autofunction:: algorithm_playground.visualization.show_frame
.. autofunction:: algorithm_playground.visualization.step_through

Keys
----

.. autoclass:: algorithm_playground.visualization.Key
.. autoclass:: algorithm_playground.visualization.KeyPress
.. autoclass:: algorithm_playground.visualization.KeySource
.. autoclass:: algorithm_playground.visualization.LineKeySource
.. autoclass:: algorithm_playground.visualization.TerminalKeySource
.. autofunction:: algorithm_playground.visualization.decode_key
.. autofunction:: algorithm_playground.visualization.decode_line
.. autofunction:: algorithm_playground.visualization.open_terminal_key_source
