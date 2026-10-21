Quickstart
==========

Install
-------

The package is a standard Python project managed with ``uv``:

.. code-block:: console

   $ git clone https://github.com/christopherpriebe/algorithm-playground.git
   $ cd algorithm-playground
   $ uv sync --extra dev

Once installed, the ``algorithm-playground`` command is available inside the
project's virtual environment:

.. code-block:: console

   $ uv run algorithm-playground list
                           Registered problems
   ┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
   ┃ name    ┃ description                                                 ┃
   ┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
   │ sorting │ Sort an array of 32-bit signed integers in ascending order. │
   └─────────┴─────────────────────────────────────────────────────────────┘

Test the reference Python sort
------------------------------

The ``examples/sorting/`` directory ships two executables that honor
the sorting binary contract:

.. code-block:: console

   $ uv run algorithm-playground test sorting examples/sorting/python_sort.py
   ...
   10/10 fixtures passed

Benchmark with a reproducible seed
----------------------------------

``benchmark`` accepts comma-separated sizes and a random seed. With ``--json``
it archives a full report (executable SHA-256, host details, samples per
size) for later comparison:

.. code-block:: console

   $ uv run algorithm-playground benchmark sorting examples/sorting/python_sort.py \
       --seed 42 --sizes 1000,10000,100000 --repetitions 3 --json /tmp/bench.json

Step through a trace
--------------------

The Python example writes a two-snapshot trace (the input and the sorted
output). An algorithm you write yourself would record a snapshot after each
step:

.. code-block:: console

   $ uv run algorithm-playground debug sorting examples/sorting/python_sort.py \
       --size 16 --seed 7

Press ``n`` to advance, ``p`` to go back, ``g <index>`` to jump, ``q`` to
quit. Add ``--auto-advance --delay-milliseconds 200`` to play the trace back
automatically.
