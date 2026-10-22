algorithm-playground
====================

``algorithm-playground`` is a learning and benchmarking sandbox for algorithms.
It provides a Typer-based command-line harness, ``algorithm-playground``, that
drives any command written in any language (``./sort``, ``python3 sort.py``,
``node sort.js``, ``java -jar Sort.jar``) as long as it implements a small,
problem-specific binary I/O contract. Several implementations can be tested and
benchmarked side by side, and a configuration file lets a separate repository
of solutions describe its implementations by name.

Three modes:

* **test** — run curated fixtures and seeded random cases on one or more
  implementations to verify functional correctness, with failure reports that
  shrink the failing input.
* **benchmark** — measure wall-time across configurable sizes with a seeded
  random number generator, so runs are reproducible, and compare
  implementations in one table, plot, and JSON report.
* **debug** — invoke an implementation in an optional trace mode and step through
  the algorithm's intermediate states and operations in the terminal, one key at
  a time.

The bundled ``sorting`` problem (sort an array of ``i32`` ascending) is the
reference implementation. A problem is an interface: subclass the
:class:`~algorithm_playground.core.Problem` ABC, decorate it with
:func:`~algorithm_playground.core.register_problem` (both come from
:mod:`algorithm_playground.authoring`, the stable module for authors), and
supply the binary format, some fixtures and input generators, and a verifier. Seeded
random cases, failure reports with shrinking, and benchmarking come from the
core. Problems can live in your own package or solutions repository and are
found through configuration, a command-line option, or entry points; see
:doc:`writing-a-problem`.

.. toctree::
   :maxdepth: 2
   :caption: Guides

   quickstart
   cli
   executable-contract
   configuration
   writing-a-problem
   extending

.. toctree::
   :maxdepth: 2
   :caption: Problems

   problems/sorting

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api/authoring
   api/core
   api/problems
   api/visualization

.. toctree::
   :maxdepth: 2
   :caption: Project

   development
