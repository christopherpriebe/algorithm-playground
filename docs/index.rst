algorithm-playground
====================

``algorithm-playground`` is a learning and benchmarking sandbox for algorithms.
It provides a Typer-based command-line harness, ``algorithm-playground``, that
drives any executable written in any language as long as the executable
implements a small, problem-specific binary I/O contract.

Three modes:

* **test** — run a curated set of small fixtures to verify functional correctness.
* **benchmark** — measure wall-time across configurable sizes with a seeded
  random number generator, so runs are reproducible.
* **debug** — invoke the executable in an optional trace mode and walk through
  the algorithm's intermediate state in the terminal.

The bundled ``sorting`` problem (sort an array of ``i32`` ascending) is the
reference implementation. Adding a new problem means subclassing the
:class:`~algorithm_playground.core.problem.Problem` ABC, decorating it with
:func:`~algorithm_playground.core.registry.register_problem`, and documenting
its binary format.

.. toctree::
   :maxdepth: 2
   :caption: Guides

   quickstart
   cli
   executable-contract
   extending

.. toctree::
   :maxdepth: 2
   :caption: Problems

   problems/sorting

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api/core
   api/problems
   api/visualization
