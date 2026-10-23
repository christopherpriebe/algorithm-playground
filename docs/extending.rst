Adding a new problem
====================

A problem is an interface. Everything generic lives in the core and works for
any problem that implements the interface: running implementations,
fixtures and seeded random cases, failure reports with the input, the expected
output, and the actual output, shrinking a failing input, benchmarking, and
checking a problem's own consistency. A problem only supplies what is specific
to it: its binary formats, its cases, and its correctness check.

A problem can live anywhere: in this package, in an installed package, or in
the repository where you keep your own solutions. This page is the reference
for the interface and for how a problem is found; :doc:`writing-a-problem` walks
through a complete problem from scratch.

Everything a problem author needs is exported from one module,
:mod:`algorithm_playground.authoring`, the stable surface for writing a
problem: the ``Problem`` interface with ``Fixture``, ``InputGenerator``,
``VerificationResult``, ``Frame`` and ``FrameSequence``, ``register_problem``,
the helpers that read and write the binary formats, the building blocks for
shrinking, describing and replaying (see `Building blocks`_), the chart
renderers, and the validation kit. Import from it and nothing else, as the examples on this page
do; the rest of the package may change between versions.

.. code-block:: python

   from algorithm_playground.authoring import Problem, register_problem

The interface
-------------

Subclass :class:`~algorithm_playground.core.Problem` and set the
``name`` and ``description`` class attributes (``dimensions``,
``growth_dimension``, ``debug_generator`` and ``operation_names``, below, are
optional). The type variables stand for
the in-memory form of an input, of an output, and of a trace (use ``None`` when
the problem has no trace format); the sorting problem, for instance, is
``Problem[list[int], list[int], SortingTrace]``. A problem is created without
arguments.

An input type needs value equality, as a list, a tuple or a dataclass has:
the validator compares inputs, and the shrinker skips a candidate equal to its
input.

Required members:

``serialize_input(data, path)``
   Write ``data`` to ``path`` in the problem's binary input format.

``deserialize_output(path)``
   Read an implementation's output file. Raise
   :class:`~algorithm_playground.core.BinaryFormatError` when it is
   malformed; the harness reports that as a failed run.

``fixtures()``
   Return the curated cases: an iterable of
   :class:`~algorithm_playground.core.Fixture` objects, each with a
   unique ``name``, the ``input_data``, and an optional ``description``.
   Fixtures are small, hand-written inputs where a bug is easy to understand.

``generators()``
   Return a sequence of :class:`~algorithm_playground.core.InputGenerator`
   objects: a ``name``, a ``description``, and a function
   ``generate(random_generator, **size)`` that builds an input of the given size
   from a seeded :class:`random.Random`. It receives one keyword argument per
   dimension of the problem, so a problem with the one dimension ``size`` can
   write ``generate(random_generator, size)``, and a graph problem
   ``generate(random_generator, *, vertices, edges)``. A generator is called
   with one keyword argument per dimension, so its parameters must be named
   after the dimensions (``size`` for a problem that declares none); a
   parameter with another name is reported by validation. Generators are the
   problem's *distributions*: ``uniform``, ``sorted``, ``few_unique``. The first
   one is the default, used by ``benchmark`` (unless ``--distribution`` names
   others, which it then measures one after the other) and for the startup
   input. A generator has to accept every combination of values at or above the
   minimums of the problem's dimensions, and may ignore or clamp a dimension it
   does not need.

``verify(input_data, output)``
   Return a :class:`~algorithm_playground.core.VerificationResult`:
   whether ``output`` is a valid answer for ``input_data`` and, if not, a
   message that says why: a failure needs a message (a pass may carry one too).
   Two more fields are optional and are for failures only. ``focus`` is the place
   in the output that matters, in whatever form the problem uses: an index, a
   vertex, an edge. The sorting problem's is the index of the first element that
   differs. Failure reports then show that place, not the start of a long
   output. ``category`` is a short name for the kind of wrong answer
   (``"too short"``, ``"not sorted"``): failures of one category are reported in
   one block, and shrinking keeps a failure of the same category, so give one only
   when the kinds are few and their names do not depend on the input. ``score``
   is a finite number that the problem assigns to the output, in its own units (a
   tour length, a cover size, a compression ratio, the inversions a heuristic
   sort leaves); it is allowed on a pass and on a failure, and the problem must
   name it with ``score_name``. The harness only reports scores and does not know
   which direction is better.

Optional class attributes, each with a working default:

``dimensions`` (default ``(Dimension("size"),)``)
   The numbers that make up the size of an input, as a tuple of
   :class:`~algorithm_playground.core.Dimension` objects. A graph has two:

   .. code-block:: python

      from algorithm_playground.authoring import Dimension

      dimensions = (
          Dimension("vertices", minimum=1, description="the number of vertices"),
          Dimension("edges", description="the number of edges", default_maximum=500),
      )

   A dimension has a ``name`` (a Python identifier, and neither ``seed``
   nor ``random_generator``), an optional ``description``, a ``minimum``
   (default ``0``): the smallest value at which every generator returns a valid
   input, such as ``minimum=1`` for a problem whose input needs a start vertex,
   and a ``default_maximum`` (default ``100``): the largest value ``test``
   generates when ``--maximum-size`` is not given. A size is one non-negative
   integer per dimension. The startup measurement of ``benchmark`` uses the
   minimums, ``test`` draws each dimension from its minimum up to its maximum
   (the dimensions vary independently), ``benchmark --sizes`` and ``--case``
   refuse sizes below a minimum with a clear message, ``debug`` starts from 16 for every
   dimension, raised to the dimension's minimum, and validation samples the generators from them. A problem that
   declares nothing has the one dimension ``size``. When the dimensions
   depend on each other (a simple graph holds at most ``vertices * (vertices -
   1) / 2`` edges), say so in ``check_size``.

``growth_dimension`` (default ``None``)
   The name of the dimension that the growth row of a benchmark follows (the
   ``n`` of ``n log n``). The default is the first dimension. For the graph
   problem above, ``growth_dimension = "edges"`` fits the growth of the time
   against the number of edges, whatever the vertices do.

``debug_generator`` (default ``None``)
   The name of the generator that ``debug`` draws its input from when
   ``--distribution`` is not given, instead of the first one. Use it when the
   first generator makes pictures that are hard to read (the sorting problem
   prefers ``small_range``, whose few values make a readable chart).

``operation_names`` (default ``()``)
   The names ``operation_counts`` returns, in the order a table should list them.
   ``algorithm-playground list PROBLEM`` shows them, so a user knows what
   ``benchmark --count-operations`` counts before running it.

``score_name`` (default ``None``)
   What ``verify`` scores (``"tour length"``, ``"inversions"``). It titles the
   score table of ``benchmark`` (a whole number is shown without decimals, any
   other value with two decimals), appears in the summary of ``test`` and in
   ``list PROBLEM``, and is recorded in the JSON reports. With a name, ``verify``
   must give a score for every output it verifies; without one it must give
   none. :func:`~algorithm_playground.core.validate_problem` reports a
   mismatch and, when the problem provides ``expected_output``, checks the
   score against the expected outputs.

Optional methods, each with a working default:

``expected_output(input_data)``
   A known-correct answer, or ``None`` (the default) when the problem cannot
   compute one cheaply or has many valid answers. It is only shown in failure
   reports, next to the actual output; ``verify`` alone decides whether a run
   passed.

``check_input(input_data)``
   Say why ``input_data`` is not a valid input, as text, or return ``None`` (the
   default accepts everything). A rule that every input must keep (an array that
   has to be sorted, a target that has to occur in it) is written here once:
   validation applies it to the fixtures, the generated samples and the shrink
   candidates, and the shrinker skips the candidates it rejects, so ``shrink`` can
   be generous and does not have to repeat the rule.

``check_size(size)``
   Say why a combination of dimension values is not one the problem accepts, as
   text, or return ``None`` (the default accepts every size at or above the
   minimums). Use it when the dimensions are coupled, so that an impossible
   size is refused up front with your reason instead of being clamped by a
   generator and mislabelled. It is consulted for every size the command line
   or a caller names (``benchmark --sizes``, ``debug --size``, ``--case``), for
   the startup size (``benchmark`` checks it together with ``--sizes`` before
   it builds or runs anything), and for every size the ``test`` plan draws: a rejected
   draw is redrawn, the first time from the usual stratified draw and then from
   uniformly random fractions of the case's own seeded generator, and after 100
   rejected attempts the plan fails with the last reason. The minimum size must
   be accepted. Any text, even empty, counts as a rejection (an empty reason is
   shown as ``(no reason given)``). ``debug`` without ``--size`` uses 16 for
   every dimension, raised to its minimum; a problem whose rule rejects that
   default needs ``--size``. Validation checks that the minimum is accepted,
   that the hook returns text or ``None``, and that it does not raise, at every
   size it samples; it samples generators only at sizes the hook accepts.

``describe_input(input_data, *, limit)`` and ``describe_output(output, *, limit, focus=None)``
   Text for failure reports, in at most about ``limit`` characters (the harness
   sizes ``limit`` from the width of the terminal). The default is the ``repr``
   cut to ``limit`` characters; override them when a better summary exists ("37
   values, the first ten are ..."). ``focus`` is the place that ``verify``
   gave in its result, or ``None``; it is passed for the actual and for the
   expected output, and a hook that cannot use it ignores it. The helpers
   ``describe_sequence(values, limit, focus=None)`` (a list shown whole, or as
   many items as fit with the count, or a window around ``focus``) and
   ``truncate_text(text, limit)`` (cuts any text, ending it in ``...``) do the
   work for most problems.

``shrink(input_data)``
   Yield smaller or simpler variants of a failing input, most aggressive first
   (drop half of it, drop one element, replace values by simpler ones). The
   harness runs them against the failing implementation, keeps the first that
   still fails the same way, asks for variants of that one, and so on. Candidates
   that ``check_input`` rejects are skipped. The default yields nothing, which
   turns shrinking off for the problem. The helpers of `Building blocks`_ cover
   sequences, integers, and inputs made of several fields.

``deserialize_input(path)``
   Read an input file written by ``serialize_input`` and return the input. It is
   what lets ``debug --input-file`` run a saved input (``test
   --save-failing-inputs`` writes them), because checking the output needs the
   input itself, not only the file. Raise
   :class:`~algorithm_playground.core.BinaryFormatError` for a
   malformed file. The default raises ``NotImplementedError``, which ``debug``
   reports as a problem that cannot read its input files; validation checks that
   a problem that has the hook reads back what it wrote.

``deserialize_trace(path, input_data)``
   Read an implementation's optional trace file; return ``None`` (the default)
   when the problem has no trace format or the file holds no trace. The runner
   calls it only for a file that exists and is not empty: a missing or empty
   file is "no trace" without the hook being called.
   ``input_data`` is the input the executable ran on: a format whose records
   refer to positions in the input validates them against it, and one that
   records only changes can start from it. Raise
   :class:`~algorithm_playground.core.BinaryFormatError` for a
   malformed file; the runner then treats it as "no trace" and keeps the
   reason. Any other exception the hook raises is turned into the same kind of
   trace error, naming the hook.

The three hooks that use a trace after it was read all take the same arguments, in
the order **input, output, trace**: ``operation_counts(input_data, output, trace)``,
``trace_warnings(input_data, output, trace)`` and ``trace_frames(input_data, output,
trace)``. The input and the output are the ones of the run that wrote the trace,
so a trace type need not carry copies of them (the sorting trace holds only the
snapshots and the events).

``operation_counts(input_data, output, trace)``
   The operations a trace records, as a mapping from the problem's own names to
   counts (sorting: ``compares``, ``swaps``, ``writes``), or ``None`` (the
   default) when the trace does not say. ``benchmark --count-operations`` runs
   each implementation once more with a trace path, collects these counts per
   size, shows them in a table, and estimates how each count grows with the
   size. Return ``None``, not zeros, for a trace that has no operation data, so
   that the table says ``not reported``.

``trace_warnings(input_data, output, trace)``
   The inconsistencies inside a trace, as sentences, or nothing (the default).
   ``debug`` shows them in yellow under every frame, below the key legend. Use it
   for a problem where two parts of a trace must agree (sorting replays its
   events and compares the result with the last snapshot); a warning does not
   fail the run.

``input_output_frame(input_data, output)`` and ``trace_frames(input_data, output, trace)``
   What ``debug`` shows. A problem does not print and does not run a stepper: it
   returns :class:`~algorithm_playground.core.Frame` objects and the
   stepper in :mod:`algorithm_playground.visualization` plays them back with
   single-key navigation. ``input_output_frame`` returns one frame for the input and
   output, or ``None`` (the default), and is shown when there is no usable trace
   or the trace has no frames. ``trace_frames`` returns the steps of a trace, in
   order, as a sequence of frames (empty by default). A frame has a ``body``
   (text, possibly with terminal color codes: the helpers ``render_bar_chart`` and
   ``render_side_by_side_bar_charts`` of :mod:`algorithm_playground.visualization`
   produce it), a short ``caption`` (the operation that led to the step, running
   totals) and the ``highlighted_elements`` (positions, vertices, edges) the body
   draws emphasized. A trace can have far more steps than are worth drawing in
   advance, so return a :class:`~algorithm_playground.core.FrameSequence`, which
   builds a frame only when the stepper asks for it.

The binary helpers of :mod:`algorithm_playground.core`
(``write_u64``, ``read_i32_array``, and the others, with ``BinaryFormatError``)
are exported from :mod:`algorithm_playground.authoring`.

Building blocks
---------------

A problem should only say what is specific to it. The core has a block for each
part that every problem needs in some form, all exported from
:mod:`algorithm_playground.authoring`, so that the next problem imports them
instead of copying code from an earlier one. The sorting problem is written with
them, and ``examples/distinct_count`` shows the smallest use.

**Binary formats.** Scalars: ``read_`` and ``write_`` for ``u8``, ``u32``, ``u64``,
``i32``, ``i64`` and ``f64``. Arrays: ``read_i32_array(stream, count)`` and the
same for ``u32``, ``i64`` and ``f64``, with ``write_`` counterparts; a reader
checks the count against the bytes left before it reads, so a corrupt header
cannot ask for a huge allocation, and a writer names the index of a value that
does not fit its type. ``expect_end_of_stream(stream, "The output file")`` rejects
trailing bytes. For traces, ``read_records(stream, count, record)`` reads a
bounded run of fixed-size records into tuples (``record`` is a
``struct.Struct("<BII")``; mind that a ``struct`` without the ``<`` prefix pads
its fields), ``read_record_bytes`` returns the same bytes as one block for a
problem that keeps millions of records in a compact form of its own, and
``read_sections(stream, {kind: reader})`` reads a file of ``u32`` kind-tagged
sections until its end and returns ``(kind, body)`` pairs, rejecting an unknown
kind with the list of the known ones. A trace reader is then a few lines:

.. code-block:: python

   import struct

   from algorithm_playground.authoring import read_records, read_sections, read_u64

   PROBE = struct.Struct("<III")  # low, high, middle

   def read_probes(stream):
       return read_records(stream, read_u64(stream), PROBE, "probes")

   def read_trace(path):
       with path.open("rb") as stream:
           return read_sections(stream, {0: read_probes})

**Describing.** ``describe_sequence(values, limit, focus=None)`` and
``truncate_text(text, limit)`` for ``describe_input`` and ``describe_output``.

**Shrinking.** ``shrink_sequence(values)`` removes chunks of elements, the halves
first; ``shrink_integers(values)`` makes the numbers of a sequence simpler (all
zero, ranked among the distinct values, one at a time zero or halved);
``shrink_integer_sequence(values)`` does both, which is the whole ``shrink`` hook
of a problem whose input is an array of numbers (the sorting problem's);
``shrink_integer(value)`` and ``shrink_each(values, shrink_element)`` do it for
one number and for the elements of a sequence one at a time;
``shrink_fields(value, {field: shrinker})`` applies a shrinker to each field of a
dataclass, a named tuple or a tuple, which is how an input made of several parts
is shrunk part by part; ``deduplicate_candidates(candidates, input)`` drops repeats. All of them
yield the type they were given (a list stays a list). Together:

.. code-block:: python

   from dataclasses import dataclass

   from algorithm_playground.authoring import (
       Problem, shrink_fields, shrink_integer, shrink_sequence,
   )

   @dataclass(frozen=True)
   class SearchInput:
       values: tuple[int, ...]
       target: int

   class SearchProblem(Problem[SearchInput, int, None]):
       def check_input(self, input_data: SearchInput) -> str | None:
           values = input_data.values
           return None if list(values) == sorted(values) else "the values are not sorted"

       def shrink(self, input_data: SearchInput):
           return shrink_fields(
               input_data, {"values": shrink_sequence, "target": shrink_integer}
           )

``check_input`` is what lets ``shrink`` stay this short: a candidate that breaks
the order of the values is skipped.

**Replaying.** ``StateTimeline(start_state, events, apply)`` gives the state after
any number of events from a start state, an event sequence and a function
``apply(state, events)`` that returns the state after a run of events. It keeps a
checkpoint every few hundred events, so a trace of a million events needs memory
for a few thousand states and a lookup replays only a short stretch. Use it for
the ``trace_frames`` and ``trace_warnings`` of any trace made of events that change
a state (sorting swaps, a graph that grows an edge at a time). A trace that
records its states directly has nothing to replay.

A problem is written for people it does not know, so a hook that raises never
ends a command in a traceback. What happens depends on when the hook is called:

* ``verify``, ``serialize_input`` and ``deserialize_output`` are called for every
  run. An exception there is an ``ERROR`` outcome in ``test`` (category
  ``serialization``, ``verification error`` or ``malformed output``; the first
  two are not shrunk, because the problem causes them), a failure of the
  implementation in that distribution in ``benchmark``, and a failed run or
  ``Output not checked`` in ``debug``. An exception from
  ``deserialize_trace`` only costs the trace, with a message that names the hook.
* ``describe_input``, ``describe_output`` and ``expected_output`` write the text
  of a failure report; if one raises, the report says ``could not describe`` and
  why. ``shrink`` and ``check_input`` end shrinking with a ``shrink note``, and
  ``operation_counts`` fails the implementation in that distribution.
* ``fixtures``, ``generators`` and the function of a generator are needed before
  any implementation runs, in every command. If one raises, or returns something
  that is not a ``Fixture`` or an ``InputGenerator``, the command prints a message
  that names the hook and exits with code ``1``; ``benchmark`` is the exception
  for a generator that raises on a later input, which fails that distribution for
  every implementation while the other distributions still run.
* ``trace_frames``, ``trace_warnings`` and ``input_output_frame`` (including what
  they return and the drawing of each frame) are called by ``debug`` only, which
  prints a message that names the hook and exits with code ``1``.
  ``deserialize_input`` is called by ``debug --input-file`` only; a file it cannot
  read is a usage error that says so.

Cases and identifiers
---------------------

Fixtures and generators produce :class:`~algorithm_playground.core.Case`
objects, each with a stable identifier (``fixture:empty``,
``generated:uniform:size=37:seed=1234567``; a problem with several dimensions
names each of them, ``generated:exact:vertices=100:edges=500:seed=1``) that
failure reports print and ``--case`` accepts. Because generators receive a seeded
:class:`random.Random`, the identifier is enough to rebuild the input exactly.
A generator therefore has to take all of its randomness from the generator it
is given, must return the same input for the same state, and must accept every
size from the problem's minimums up. Its name appears in identifiers, so
constructing an ``InputGenerator`` with a name that is empty or contains a colon
or whitespace raises ``ValueError``. Numbers in an identifier are written the
canonical way: ``size=05``, ``seed=+7`` and ``size=1_0`` are refused rather than
guessed at. The dimensions of a case may come in any order; the case is rebuilt
and named in the order the problem declares them.

``build_cases(problem, plan)`` expands a
:class:`~algorithm_playground.core.CasePlan` (include fixtures, number of
random cases, maximum size, distributions, seed) into the cases of a test run,
and ``resolve_case(problem, identifier)`` rebuilds one case from its identifier.

Finding a problem
-----------------

Decorate the class with
:func:`~algorithm_playground.core.register_problem`; importing the
module registers the problem. A class that leaves an abstract method
unimplemented is refused at registration with the list of what is missing. The
command-line tool imports modules from four places, and ``algorithm-playground
list`` shows which one each problem came from:

* the built-in problems of this package (``src/algorithm_playground/problems/``);
* installed packages that declare an entry point in the group
  ``algorithm_playground.problems``;
* the ``problem_modules`` of a :doc:`configuration file <configuration>`
  (with ``python_paths`` to make the modules importable);
* ``--problem-module MODULE_OR_FILE`` on any command: a module name, looked up
  in the current directory as well as on the import path, or the path of a
  ``.py`` file.

An entry point may name a module (imported, so its decorators run) or a
``Problem`` subclass (registered directly). A plugin that fails to load is
reported as a warning on standard error and does not break the command, and
whatever it registered before failing is removed again, so a half-loaded plugin
is never usable. A module that loads but registers nothing gets a warning too
("did you forget @register_problem?"). See :doc:`writing-a-problem` for the
details of each route, and ``algorithm-playground list PROBLEM`` to see what a
registered problem offers: its fixtures with their descriptions, its
distributions (the default and the debug one marked), whether it has a trace
format, and its operation names.

Registering a problem in a test changes a table that the whole process shares.
:func:`~algorithm_playground.core.snapshot_registry` copies the table
and :func:`~algorithm_playground.core.restore_registry` puts the copy
back, so a test or a fixture can undo whatever a test registered or loaded:
take the snapshot first and restore it once the test is over.

Checking a problem
------------------

:func:`~algorithm_playground.core.validate_problem` exercises a
problem the way the harness will, without any implementation, and returns a
list of findings (empty means valid; the input type needs value equality, as
described under "The interface");
:func:`~algorithm_playground.core.assert_valid_problem` raises
:class:`AssertionError` listing them, which makes it a one-line test:

.. code-block:: python

   from algorithm_playground.authoring import assert_valid_problem

   def test_my_problem_is_valid():
       assert_valid_problem(MyProblem())

It checks that the problem has a name and a description, ``dimensions`` that are
a non-empty tuple of uniquely named ``Dimension`` objects, a ``growth_dimension``
that names one of them (or ``None``), a ``check_size`` that accepts the minimum
size and returns text or ``None``, a ``debug_generator`` that names one of its
generators, and ``operation_names`` that are unique text; that fixture names are
unique (construction already rejects an empty one), every fixture is accepted by
``check_input`` and serializes; that generator names are unique (construction
already rejects one that is unusable in identifiers); that each generator returns
the same input for the same seed, accepts the sizes from the minimums up, and
produces inputs that ``check_input`` accepts and that serialize; that
``deserialize_input``, when the problem has it, reads back what ``serialize_input``
wrote; that ``expected_output``, when it returns something, passes ``verify``
and can be drawn by ``input_output_frame``; that the describe hooks return
text; and that the ``shrink`` candidates that ``check_input`` accepts serialize and
differ from their input (a hook that yields copies of its input would never make
progress). It cannot check
the trace hooks, which need a trace; test those with a trace file of your own,
as ``tests/sorting/test_traces.py`` does.

Worked example
--------------

The reference :class:`~algorithm_playground.problems.sorting.SortingProblem`
is a small, end-to-end example: see
``src/algorithm_playground/problems/sorting/_problem.py`` and the binary
format documented at :doc:`problems/sorting`. A minimal problem defined outside
this package is in ``examples/distinct_count/`` and is explained in
:doc:`writing-a-problem`.
