Sorting
=======

The reference v1 problem: sort an array of 32-bit signed integers in
ascending order.

Binary format
-------------

All multi-byte integers are little-endian.

Input (``input.bin``)
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   u64  n                — element count
   n × i32 values         — values to sort

Output (``output.bin``)
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   u64  n                — element count (must equal input n)
   n × i32 values         — sorted values, ascending

Trace (``trace.bin``, optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   u32  kind             — trace kind tag (v1 only defines kind 0)
   For kind == 0 (state snapshots):
     u32  snapshot_count
     For each snapshot:
       u64  n              — element count
       n × i32 values        — current array state

The trace header is intentionally **just** a kind tag. There is no
``format_version`` field. Future kinds (for example, event streams that log
compares and swaps) will be additive: full-state snapshots remain useful
both as a sanity check on event replay and as a teaching visualization, so
adding a new kind never deprecates an existing one. v1 only defines kind
``0``; emitting any other value causes the harness to raise
:class:`~algorithm_playground.core.binary_io.BinaryFormatError`.

Test fixtures
-------------

``algorithm-playground test sorting`` runs these named fixtures:

* ``empty`` — zero elements
* ``single`` — one element
* ``two_sorted`` — ``[1, 2]``
* ``two_unsorted`` — ``[2, 1]``
* ``already_sorted`` — ``range(10)``
* ``reverse_sorted`` — ``range(9, -1, -1)``
* ``duplicates`` — mixed values with repeats
* ``all_equal`` — eight copies of the same value
* ``negatives_mixed`` — negative and positive values
* ``i32_extremes`` — ``INT32_MIN``, ``INT32_MAX``, and values adjacent to
  them

Benchmark generator
-------------------

``benchmark_case(seed, size)`` uses :class:`random.Random` with the given
seed to draw ``size`` independent values uniformly from
``[INT32_MIN, INT32_MAX]``. Two invocations with the same ``(seed, size)``
return identical arrays.

Reference executables
---------------------

The repository ships two executables that conform to the contract. Both use
their language's built-in sort; they show the contract, not an algorithm:

* ``examples/sorting/python_sort.py`` — wraps ``sorted``; writes a
  two-snapshot trace (input and output).
* ``examples/sorting/c_qsort.c`` — wraps libc's ``qsort``; ignores the
  optional trace path so ``debug`` exercises the fallback path.
