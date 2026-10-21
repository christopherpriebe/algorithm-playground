Quickstart
==========

Install
-------

To use the command anywhere, install it as a tool:

.. code-block:: console

   $ uv tool install algorithm-playground
   $ pipx install algorithm-playground

The ``examples/`` directory used below lives only in the repository, not in the
installed package. To follow this page, or to work on the project, clone it:

.. code-block:: console

   $ git clone https://github.com/christopherpriebe/algorithm-playground.git
   $ cd algorithm-playground
   $ uv sync --extra dev

The commands below use ``uv run`` to run ``algorithm-playground`` from that
checkout; with an installed tool, drop the ``uv run`` prefix:

.. code-block:: console

   $ uv run algorithm-playground --version
   $ uv run algorithm-playground list
                                   Registered problems
   ┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
   ┃ name    ┃ description                                                 ┃ source   ┃
   ┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
   │ sorting │ Sort an array of 32-bit signed integers in ascending order. │ built-in │
   └─────────┴─────────────────────────────────────────────────────────────┴──────────┘

``list sorting`` shows what one problem offers: its fixtures with their
descriptions, its input distributions (the default is marked), whether it has a
trace format, and which operations ``benchmark --count-operations`` counts.

Test the reference Python sort
------------------------------

The ``examples/sorting/`` directory ships two executables that honor
the sorting binary contract:

.. code-block:: console

   $ uv run algorithm-playground test sorting examples/sorting/python_sort.py
   ...
   python_sort.py: 44/44 cases passed (24/24 fixtures, 20/20 generated)

``test`` runs the problem's fixtures (small, named, hand-written inputs) and 20
seeded random cases. When an implementation is wrong, the report shows the
failing input, the expected and actual output, the smallest failing input that
shrinking found, and a command that reproduces the case; see :doc:`cli`. To keep
the failing inputs, add ``--save-failing-inputs failures``; each one is a file
that ``debug --input-file`` can step through:

.. code-block:: console

   $ uv run algorithm-playground test sorting my_sort.py --save-failing-inputs failures
   $ uv run algorithm-playground debug sorting my_sort.py \
       --input-file failures/my_sort.py/generated_uniform_size=9_seed=1150936189/shrunk-input.bin

Benchmark with a reproducible seed
----------------------------------

``benchmark`` accepts comma-separated sizes and a random seed. With ``--json``
it archives a full report (SHA-256 of the files each command refers to, host
details, samples per size) for later comparison:

.. code-block:: console

   $ uv run algorithm-playground benchmark sorting examples/sorting/python_sort.py \
       --seed 42 --sizes 1000,10000,100000 --repetitions 3 --json /tmp/bench.json

Benchmark input distributions
-----------------------------

By default ``benchmark`` uses the problem's default distribution. Name others
with ``--distribution`` (repeatable) to see how an implementation behaves on
sorted, duplicate-heavy, or adversarial input; ``algorithm-playground list
sorting`` lists them. With three or more sizes the table ends each distribution
with a ``growth`` row, the best-fitting class and the fitted exponent of the
median time, such as ``~ n log n (n^1.21)``:

.. code-block:: console

   $ uv run algorithm-playground benchmark sorting examples/sorting/c_qsort \
       --distribution uniform --distribution sorted --distribution few_unique \
       --sizes 1000,10000,100000

Compare implementations
-----------------------

``test`` and ``benchmark`` accept several implementations and run them on
identical inputs. Name them as paths, or as command text for anything that is
not directly executable (two commands that run one script with other arguments
are told apart by those arguments, and ``--name`` names a command):

.. code-block:: console

   $ make -C examples/sorting
   $ uv run algorithm-playground test sorting \
       --command "python3 examples/sorting/python_sort.py" examples/sorting/c_qsort
   $ uv run algorithm-playground benchmark sorting \
       examples/sorting/python_sort.py examples/sorting/c_qsort \
       --sizes 1000,10000 --repetitions 3

The benchmark prints one table with a median and a ratio to the reference
(the first implementation, or ``--reference NAME``) per implementation, plots
them on one chart, and writes all of them to the ``--json`` report. A
repository of your own solutions can describe its implementations once in an
``algorithm-playground.toml`` file and run them by name; see :doc:`configuration`.

Step through a trace
--------------------

The Python example writes a two-snapshot trace (the input and the sorted
output). An algorithm you write yourself can record a snapshot after each step,
and the individual compares, swaps and writes as events; see
:doc:`problems/sorting` for the format.

.. code-block:: console

   $ uv run algorithm-playground debug sorting examples/sorting/python_sort.py \
       --size 16 --seed 7

On a terminal each key acts at once: right arrow or ``n`` advances, left arrow
or ``p`` goes back, ``g`` jumps to a frame you name, space pauses and resumes
auto-advance, ``q`` quits. Add ``--auto-advance --delay-milliseconds 200`` to
play the trace back automatically. With events, every frame shows the operation
that led to it, colors the bars it touched, and keeps count of the operations
so far.

Count operations
----------------

Wall time depends on the machine; the number of compares an algorithm makes
does not. If an implementation writes an event trace, ``benchmark`` can count
its operations and estimate how they grow:

.. code-block:: console

   $ uv run algorithm-playground benchmark sorting my-insertion-sort my-merge-sort \
       --count-operations --distribution uniform --sizes 100,200,400,800

Below the timing table there is a table for each operation (compares, swaps
and writes) with a column per implementation and a row per size, followed by a
``growth`` row such as ``~ n^2 (n^1.97)`` for an algorithm whose compares grow
about quadratically. An implementation that writes no events shows ``not
reported``.
