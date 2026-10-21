Executable contract
===================

Every executable driven by ``algorithm-playground`` honors a single, simple
contract::

   <executable> <input_path> <output_path> [<trace_path>]

* ``argc == 3``: read binary input from ``input_path``, write binary output
  to ``output_path``. Exit 0 on success; any non-zero exit is treated as a
  run failure and the executable's stderr is surfaced to the user.

* ``argc == 4``: same as above, AND write a binary trace stream to
  ``trace_path``. Implementing trace support is optional. If the file is
  missing, empty, or malformed, the playground's ``debug`` command reports
  "trace not supported by this executable" cleanly and falls back to the
  input/output view.

The exact byte layout of input, output, and trace is **problem-defined**.
The harness itself never interprets bytes — it delegates serialization and
deserialization to the :class:`~algorithm_playground.core.problem.Problem`
subclass. See :doc:`problems/sorting` for the canonical sorting format.

Notes
-----

* All multi-byte integers are little-endian unless a problem explicitly
  states otherwise.
* The executable receives a minimal, deterministic environment: ``PATH``,
  ``LANG``, ``LC_ALL``, ``HOME``, and ``TMPDIR`` are forwarded; everything
  else is stripped so benchmark runs are reproducible across machines.
* The executable should not read from stdin or write program output to
  stdout; stdout is captured but ignored. Use stderr only for diagnostic
  messages — they surface to the user on failure.
* Compile or build the executable yourself; the harness does not invoke a
  compiler.
