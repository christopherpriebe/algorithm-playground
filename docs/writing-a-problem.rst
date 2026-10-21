Writing a problem
=================

This page builds a complete problem outside this package and runs it, in three
steps: define the problem, make it available to the command-line tool, and
check it. The problem is deliberately small: count the distinct values in an
array of 32-bit integers. The interface behind it is described in
:doc:`extending`.

A problem is a Python class. You do not write a test runner, a random case
generator, a failure report, or a shrinker: the harness provides all of them
for every problem. You supply the binary formats, some cases, and the check
that decides whether an answer is right.

The binary format
-----------------

An implementation is any command that reads an input file and writes an output
file (see :doc:`executable-contract`); the problem decides what those files
contain. For this problem all integers are little-endian:

.. code-block:: text

   input:   u64 count, then count x i32 values
   output:  u64, the number of distinct values in the input

The problem
-----------

The complete problem, in a module called ``distinct_count_problem.py`` (it is
in the repository as ``examples/distinct_count/distinct_count_problem.py``):

.. literalinclude:: ../examples/distinct_count/distinct_count_problem.py
   :language: python

What each part does:

* ``Problem[list[int], int, None]`` says that an input is a list of integers,
  an output is an integer, and the problem has no trace format.
* ``@register_problem`` adds the class to the registry under its ``name`` when
  the module is imported. The ``description`` is shown by
  ``algorithm-playground list``.
* ``serialize_input`` and ``deserialize_output`` convert between the in-memory
  form and the files, using the helpers of ``algorithm_playground.authoring``.
  A malformed output raises ``BinaryFormatError``; ``expect_end_of_stream``
  rejects bytes after the last field, and ``read_i32_array`` checks a count
  against the bytes that are left.
* ``deserialize_input`` is optional. It reads an input file back, which lets
  ``debug --input-file`` run an input that ``test --save-failing-inputs`` saved.
* ``fixtures`` returns the small, named, hand-written cases. They are the first
  rows of the ``test`` matrix.
* ``generators`` returns the seeded input generators. A generator is a name, a
  description, and a function from a :class:`random.Random` and a size to an
  input. The first one is the default (``benchmark`` uses it unless
  ``--distribution`` names others). The harness
  hands each generated case its own seed, so every case can be rebuilt from its
  identifier.
* ``verify`` decides whether an output is right for an input.
* ``expected_output`` is optional. It lets failure reports show what a correct
  answer looks like next to the actual output.
* ``shrink`` is optional. It yields smaller variants of a failing input so that
  a failure on 80 values is reported as a failure on the 2 that matter;
  ``shrink_sequence`` is the building block for the common case.

Everything else (descriptions of inputs for reports, the startup input for
benchmarks, a rule that every input must keep, written once as ``check_input``)
has a working default. The core also has building blocks for the parts that every
problem needs in some form (binary formats, shrinking, describing a long value,
replaying events), listed in :doc:`extending`; use them rather than copying
code from another problem. Everything the example imports comes from one
module, ``algorithm_playground.authoring``, the stable surface for authors.

An implementation
-----------------

Any language works. In Python, ``distinct_count.py``:

.. literalinclude:: ../examples/distinct_count/distinct_count.py
   :language: python

Making the problem available
----------------------------

The command-line tool has to import your module so that its decorator runs.
There are three ways, from quickest to most permanent.

**On the command line.** Name the module, or the file it is in:

.. code-block:: console

   $ cd examples/distinct_count
   $ algorithm-playground list --problem-module distinct_count_problem
   $ algorithm-playground list --problem-module distinct_count_problem.py
   $ cd ../..
   $ algorithm-playground list --problem-module examples/distinct_count/distinct_count_problem.py

``--problem-module`` is accepted by every command and may be repeated. A module
name is looked up in the current directory as well as on the import path; a value
that ends in ``.py`` or contains a slash is the path of a file, relative to the
current directory, and the modules next to the file can be imported by it. The
directory that holds the module stays on the import path for the whole command,
so the module can import its neighbors later too, for example from inside a hook.
If the module cannot be found the error says what to try. A module that loads but registers no
problem produces a warning ("did you forget @register_problem?"), and a problem
class that leaves a method of the interface unimplemented is refused with the
list of the missing methods.

**In the configuration file** of your solutions repository. ``python_paths``
adds directories to the import path (relative to the file) and
``problem_modules`` lists the modules to import, so nobody has to remember an
option or an environment variable. This is the file in
``examples/distinct_count/algorithm-playground.toml``:

.. code-block:: toml

   python_paths = ["."]
   problem_modules = ["distinct_count_problem"]

   [[implementations]]
   name = "python-set"
   problem = "distinct-count"
   command = "python3 distinct_count.py"

Because the modules are loaded before the implementations are checked, an
implementation's ``problem`` may name a problem defined right there. A name that
no problem has is a configuration error. See :doc:`configuration`.

**As an installed package.** A package that provides problems declares an entry
point in the group ``algorithm_playground.problems`` in its ``pyproject.toml``.
The value is a module, which is imported, or a ``module:Class``, which is
registered:

.. code-block:: toml

   [project.entry-points."algorithm_playground.problems"]
   graphs = "solutions_problems.graphs"
   distinct-count = "solutions_problems.counting:DistinctCountProblem"

Once the package is installed, its problems are available everywhere without
any option or configuration. A plugin that fails to import produces a warning
that names it, and the command carries on without it.

``algorithm-playground list`` shows the source of every problem (``built-in``,
``entry point: graphs``, ``configuration: distinct_count_problem``, or
``option: distinct_count_problem``), and ``algorithm-playground list
distinct-count`` shows what your problem offers: its fixtures and their
descriptions, its distributions, and that it has no trace format.

Running it
----------

From ``examples/distinct_count``, where the configuration file is:

.. code-block:: console

   $ algorithm-playground test distinct-count
          test results — distinct-count
   ┏━━━━━━━━━━━━┳━━━━━━━━━━━━┓
   ┃ case       ┃ python-set ┃
   ┡━━━━━━━━━━━━╇━━━━━━━━━━━━┩
   │ fixtures   │    5/5     │
   ├────────────┼────────────┤
   │ uniform    │   10/10    │
   │ few_values │   10/10    │
   └────────────┴────────────┘
   python-set: 25/25 cases passed (5/5 fixtures, 20/20 generated)

   $ algorithm-playground benchmark distinct-count --sizes 1000,10000

When an implementation is wrong (say, one that outputs the length of the input),
the failure report shows the input, the expected and actual output, the smallest
failing input that shrinking found, and a command that reproduces the case; see
:doc:`cli`.

Checking the problem
--------------------

Add a test next to the problem. ``assert_valid_problem`` runs the checks
described in :doc:`extending`: fixture and generator names, determinism of the
generators for a fixed seed, the smallest size, serialization of every input,
whether ``deserialize_input`` reads back what was written, whether
``expected_output`` passes ``verify``, whether the fixtures and generated inputs
satisfy ``check_input``, and whether ``shrink`` candidates serialize.

.. code-block:: python

   from algorithm_playground.authoring import assert_valid_problem
   from distinct_count_problem import DistinctCountProblem


   def test_the_problem_is_valid():
       assert_valid_problem(DistinctCountProblem())

A finding is a sentence that names what is wrong, for example
``generator 'uniform' at size 5 returned different inputs for the same seed``
(the generator used randomness that did not come from its argument) or
``fixture 'huge' does not serialize: ValueError: ...``.

Where to go next
----------------

* Override ``describe_input`` and ``describe_output`` when the default
  ``repr`` is too long to read in a report; ``describe_sequence`` shows a long
  list as its first items and its length, or as a window around the position
  ``verify`` named in ``VerificationResult.focus``.
* Write the rule that every input must keep (an array that has to be sorted) as
  ``check_input``, so that shrinking skips candidates that break it.
* Add more generators that stress different shapes of input; each one is a
  distribution that ``test --distribution`` can select and that ``benchmark``
  can use.
* Define a trace format and ``deserialize_trace``, ``trace_frames`` and
  ``input_output_frame`` to give ``debug`` something to step through, and
  ``operation_counts`` to let ``benchmark --count-operations`` count what your
  algorithms do; the sorting problem is the reference, and its trace format
  (sections of snapshots and of compare, swap and write events) is documented
  in :doc:`problems/sorting`. ``deserialize_trace`` reads the trace file given the
  input; the hooks that use the trace afterwards (``operation_counts``,
  ``trace_warnings`` and ``trace_frames``) receive the input, the output and the
  trace, in that order, and ``input_output_frame`` receives the input and the
  output only. ``debug`` plays the frames you return with
  single-key navigation; you never write the stepper. ``read_sections`` and
  ``read_records`` read a trace file, and ``StateTimeline`` replays events to the
  state after any one of them.
* Set ``minimum_size`` when an input of size 0 is not valid; every generator
  then has to accept sizes from there, and the startup measurement, the
  generated test sizes and ``debug`` start from it.
* Set ``debug_generator`` to the name of the generator whose inputs make the
  best pictures, and ``operation_names`` to the operations your trace counts.
