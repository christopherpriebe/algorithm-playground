CLI reference
=============

All commands are subcommands of ``algorithm-playground``. Each accepts the
problem's slug as the first positional argument and a path to the executable
as the second.

``list``
--------

.. code-block:: console

   $ algorithm-playground list

Print a table of every registered problem and its description.

``test``
--------

.. code-block:: console

   $ algorithm-playground test PROBLEM EXECUTABLE [--timeout SECONDS] [--keep-temporary-files]

Run every fixture returned by ``Problem.test_cases()`` against ``EXECUTABLE``
and report pass/fail per case. Exit code equals the number of failures, so
the command is CI-friendly.

Options:

``--timeout / -t``
   Per-fixture timeout in seconds (default: ``60``).

``--keep-temporary-files``
   Preserve the per-run scratch directory after the run so you can inspect
   the binary input, output, and any trace files the executable produced.

``benchmark``
-------------

.. code-block:: console

   $ algorithm-playground benchmark PROBLEM EXECUTABLE \
       [--seed N] [--sizes 1000,10000,100000] \
       [--repetitions 5] [--warmup 1] [--timeout SECONDS] \
       [--json FILE] [--plot / --no-plot] [--verify / --no-verify] \
       [--subtract-startup-time]

For each size in ``--sizes``, run ``--warmup`` discarded iterations followed
by ``--repetitions`` measured iterations. Reports the minimum, median, and
standard deviation of wall-clock time.

Before the sized runs, the executable is also timed on an empty input (the
problem's ``baseline_case``) with the same warmup and repetition counts. That
row, labelled ``startup (empty input)``, shows the fixed cost every run pays:
process startup, interpreter or runtime initialization, and file I/O. For an
interpreted executable this can dominate small sizes.

``--subtract-startup-time``
   Subtract the mean of the empty-input runs from every measured sample, so
   the table, plot and JSON estimate algorithm work instead of total run
   time. Off by default. Results are not clamped: a negative value means the
   work is smaller than the run-to-run noise of the measurement. The JSON
   report always keeps the unadjusted times in ``raw_samples_seconds`` and
   the empty-input runs under ``startup``.

``--seed``
   Seed for the random number generator used to produce the input
   (default: ``0``).

``--sizes``
   Comma-separated list of input sizes (default: ``1000,10000,100000``).
   Underscores are allowed for readability (e.g. ``--sizes 100_000``).

``--repetitions``
   Number of measured runs per size (default: ``5``).

``--warmup``
   Number of discarded runs per size before measurement starts
   (default: ``1``).

``--verify``
   Verify each measured run's output before counting its sample. Disable
   with ``--no-verify`` to remove verification overhead from the timings.

``--json``
   Path to write a JSON report containing the configuration, samples,
   summary statistics, host info, and executable SHA-256.

``--plot``
   Draw a terminal plot of size vs. median time using ``plotext``. Disable
   with ``--no-plot``.

``debug``
---------

.. code-block:: console

   $ algorithm-playground debug PROBLEM EXECUTABLE \
       [--seed N] [--size N] [--from-test NAME] \
       [--auto-advance] [--delay-milliseconds N] [--timeout SECONDS]

Generate a single input (either from ``--from-test <case_name>`` or a seeded
random of ``--size``), invoke the executable with a trace path, and step
through the resulting trace.

If the executable does not write a non-empty trace file, ``debug`` prints
a friendly message explaining how to add trace support and falls back to
the problem's ``visualize_io`` view.

Options:

``--seed``
   Seed for generated input (ignored when ``--from-test`` is set).

``--size``
   Size of generated input (ignored when ``--from-test`` is set;
   default: ``16``).

``--from-test``
   Use a registered test fixture as the input instead of generating one.

``--auto-advance``
   Advance through frames automatically.

``--delay-milliseconds``
   Delay between auto-advanced frames in milliseconds (default: ``250``).
