Executable contract
===================

An *implementation* is a command that solves one problem. The harness runs it
as a child process once per input, hands it file paths, and reads the files it
writes. Any language works, because the whole interface is the command line
and the files:

.. code-block:: text

   <command...> <input_path> <output_path> [<trace_path>]

``<command...>`` is the implementation's command: a program followed by any
leading arguments of your choosing. The harness appends the paths. These are
all valid implementations:

.. code-block:: text

   ./build/merge_sort                      # compiled binary
   python3 my_sort.py                      # no executable bit needed
   node sort.js
   java -jar build/Sort.jar
   cargo run --quiet --release --

so a real invocation looks like
``node sort.js /tmp/algorithm-playground-x1/input.bin /tmp/algorithm-playground-x1/output.bin``.
The paths are absolute and point into a fresh scratch directory that the
harness creates for the run and deletes afterwards (``test
--keep-temporary-files`` keeps it and names it in the failure messages).

What the program must do
------------------------

* Receive two arguments after the command: ``input_path`` and
  ``output_path``. Read the binary input from ``input_path`` and write the
  binary output to ``output_path``. The input file already exists and must be
  treated as read-only. The output file does **not** exist yet: create it. A
  run that exits without creating it is a failure.

* Receive an optional third argument, ``trace_path``, only when a trace is
  wanted (the ``debug`` command passes it, and so does ``benchmark`` for its
  untimed counting runs with ``--count-operations``; ``test`` and the timed runs
  of ``benchmark`` do not). When present, also write the problem's binary trace
  stream to it. Trace support is optional. If the file is missing, empty, or
  malformed, ``debug`` says so and falls back to the problem's input and output
  view, and ``benchmark`` shows ``not reported`` instead of operation counts. A
  program that does not support traces should simply ignore a third argument
  instead of failing on it.

* Exit with status ``0`` on success. Any other status, a crash, or a timeout
  is a failed run, and everything the program wrote to standard error is
  included in the failure message under ``standard error:``.

* Do not read standard input and do not write results to standard output.
  Standard input is empty (the harness connects it to the null device), so a
  program that waits for input sees end of file at once. Standard output is
  captured and ignored. Use standard error only for diagnostics.

* Finish within the timeout (``--timeout``, default 60 seconds, or the
  ``timeout_seconds`` of the implementation's entry in the configuration file).
  The harness kills the process and everything it started when the timeout
  expires, and reports the run as failed.

The harness never interprets the bytes itself. The exact byte layout of the
input, output, and trace is **problem-defined**; the problem's page describes
it (see :doc:`problems/sorting` for the sorting format). Unless a problem says
otherwise, all multi-byte integers are little-endian. A malformed output file,
such as a header that promises more data than the file holds, is reported as a
failed run.

A complete example for the sorting problem, in Python:

.. code-block:: python

   import struct
   import sys

   input_path, output_path = sys.argv[1], sys.argv[2]
   with open(input_path, "rb") as stream:
       raw = stream.read()
   (count,) = struct.unpack_from("<Q", raw)
   values = sorted(struct.unpack_from(f"<{count}i", raw, 8))
   with open(output_path, "wb") as stream:
       stream.write(struct.pack(f"<Q{count}i", count, *values))

The Python reference implementation in ``examples/sorting/`` also writes the
optional trace; the C one ignores it.

Working directory
-----------------

The command runs in the implementation's working directory:

* For an implementation described in a :doc:`configuration file
  <configuration>`, that is the ``working_directory`` of its entry, which
  defaults to the directory containing the configuration file. Relative paths
  in ``command`` (such as ``./build/merge_sort``) are resolved against it, so
  the same configuration works wherever the command is launched from.
* For an implementation given on the command line as a file path or with
  ``--command``, it is the directory the user ran ``algorithm-playground``
  from. A file path is made absolute before use, so it works regardless.

The command is looked up the way the operating system looks up any program:
a name without a slash, such as ``node``, is searched for on ``PATH``; a name
with a slash, such as ``./build/merge_sort``, is a path relative to the
working directory.

Environment
-----------

By default the program receives a minimal, deterministic environment so that
benchmark runs are reproducible across machines. Only ``PATH``, ``LANG``,
``LC_ALL``, ``HOME``, and ``TMPDIR`` are forwarded (``PATH`` falls back to
``/usr/bin:/bin`` when the caller has none); everything else is stripped.

Toolchains that locate themselves through other variables, such as
``JAVA_HOME``, version-manager shims, a virtual environment, or
``CARGO_HOME``, may need the full environment. Opt in per implementation with
``inherit_environment = true`` in the configuration file, or for
implementations named on the command line with ``--inherit-environment``. The
program then receives a copy of the environment of the ``algorithm-playground``
process. The build command (below) follows the same setting.

Either way, an implementation in the configuration file can add variables of
its own with an ``environment`` table, applied on top of the minimal or
inherited environment (see :doc:`configuration`). The usual use is a
``PYTHONPATH`` that makes a helper module of the solutions repository
importable while everything else stays stripped.

Build commands
--------------

An implementation may declare a build command, such as ``make build/merge_sort``
or ``cargo build --release``. Before any run, the harness executes each
selected implementation's build command once, in its working directory and with
its environment policy, and prints which implementation is being built. The
build is not part of any timing.

* A build that exits non-zero, times out (300 seconds), or cannot be started
  is reported once, with the build's output, on standard error. That
  implementation is not run and appears as failed in the results (in ``test``
  as ``build failed`` in every row, in ``benchmark`` as a ``failed`` column and
  a ``failures`` entry of stage ``build`` in the JSON report), and the command
  exits with code ``1``. The other implementations are still built and run. When no
  implementation builds, nothing runs.
* ``--no-build`` skips build commands, for example when the artifacts are
  already up to date.
* Build commands can only be declared in the :doc:`configuration file
  <configuration>`. Implementations given as paths or ``--command`` are
  assumed to be ready to run.

Processes and cleanup
---------------------

Each run, and each build, starts in its own process group. When the run times
out, is interrupted, or finishes, the harness kills the whole group, so
processes your program started (compiler drivers, helper programs, background
jobs) never outlive the run and cannot keep the harness waiting by holding its
output pipes open. The run's wall time ends when your program itself exits. A
program that deliberately detaches into a new session escapes this cleanup.

On platforms without process groups only the program itself is killed.

Notes
-----

* Each run is a fresh process, so benchmark timings include process startup.
  The ``benchmark`` command reports that cost separately; see :doc:`cli`.
* Compiling is your responsibility, either by hand or through a build
  command. The harness does not invoke a compiler on its own.
