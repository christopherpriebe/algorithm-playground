``algorithm_playground.core``
=============================

The ``core`` package holds the framework: the :class:`Problem` ABC with its
cases and validation, the registry, the subprocess :class:`Runner`, the
:class:`Implementation` command wrapper and its TOML configuration, the test
and benchmark engines, and the small binary format and statistics helpers. A
problem author does not import from here; :doc:`authoring` re-exports what a
problem needs.

Public API
----------

``algorithm_playground.authoring`` is the stable surface for writing a problem.
``algorithm_playground.core`` and ``algorithm_playground.visualization`` are
public as well, for code that drives the engines or draws charts, and the package
ships a ``py.typed`` marker so type checkers use its annotations.
``algorithm_playground.cli`` is the command-line front end and is not a public
API; neither are modules and names that start with an underscore.

Problem ABC
-----------

.. automodule:: algorithm_playground.core.problem

Cases
-----

.. automodule:: algorithm_playground.core.cases

Hooks
-----

.. automodule:: algorithm_playground.core.hooks

Frames
------

.. automodule:: algorithm_playground.core.frames

Describing
----------

.. automodule:: algorithm_playground.core.description

Shrinking
---------

.. automodule:: algorithm_playground.core.shrinking

Replaying
---------

.. automodule:: algorithm_playground.core.replay

Validation
----------

.. automodule:: algorithm_playground.core.validation

Registry
--------

.. automodule:: algorithm_playground.core.registry

Implementation
--------------

.. automodule:: algorithm_playground.core.implementation

Configuration
-------------

.. automodule:: algorithm_playground.core.configuration

Runner
------

.. automodule:: algorithm_playground.core.runner

Single run
----------

.. automodule:: algorithm_playground.core.single_run

Test engine
-----------

.. automodule:: algorithm_playground.core.testing

Saved inputs
------------

.. automodule:: algorithm_playground.core.saved_inputs

Benchmark engine
----------------

.. automodule:: algorithm_playground.core.benchmarking

Report
------

.. automodule:: algorithm_playground.core.report

Binary format
-------------

.. automodule:: algorithm_playground.core.binary_format

Statistics
----------

.. automodule:: algorithm_playground.core.statistics
