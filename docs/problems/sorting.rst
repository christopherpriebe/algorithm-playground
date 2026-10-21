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

The output file must be exactly ``8 + 4 × n`` bytes long: the declared count
must match the size of the file, and bytes after the last value are rejected
as a malformed output. A header that promises more values than the file holds
is rejected before anything is read. The harness reports a malformed output as
a failed run.

Trace (``trace.bin``, optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A trace tells ``debug`` what the algorithm did and ``benchmark
--count-operations`` how often. The file is a sequence of **sections** that is
read until the end of the file. Every section starts with a ``u32`` *kind* that
says how to read the rest of it:

.. code-block:: text

   section*                   — zero or more sections, back to back, up to EOF

   u32  kind                  — 0 = state snapshots, 1 = events
   kind 0 body (state snapshots):
     u32  snapshot_count
     snapshot_count × {
       u64  n                 — element count of this snapshot
       n × i32 values         — the array at that moment
     }
   kind 1 body (events):
     u64  event_count
     event_count × 9-byte record {
       u8   type              — 0 = compare, 1 = swap, 2 = write
       u32  first
       u32  second
     }

Mind the widths: ``snapshot_count`` is a ``u32``, but ``event_count`` is a
``u64`` (and so is the ``n`` of every snapshot), because a run can record far
more events than snapshots. A writer that uses one width for both produces a
file the harness cannot read.

There is no version field and no total length: the kind of a section decides
how many bytes belong to it, and the next section starts right after. A file
that holds only one kind-0 section (the whole format of version one) is still
valid, an empty file means "no trace", and an unknown kind is an error. Both
kinds may be present, in any order, and a kind may appear more than once: the
snapshots of all kind-0 sections are joined in file order, and so are the
events of all kind-1 sections. That lets a program append a section whenever it
has something to say instead of buffering the whole run.

**Snapshots** (kind 0) are full copies of the array, for instance one after
every pass. They are what a person looks at, and the final one lets the harness
check the events (see below). **Events** (kind 1) are the individual operations,
in the order they happened, and are the source of the operation counts.

Event semantics. All integers are little-endian, and indices are zero-based
positions in the array being sorted:

.. list-table::
   :header-rows: 1
   :widths: 10 12 14 14 50

   * - ``type``
     - Name
     - ``first``
     - ``second``
     - Meaning
   * - ``0``
     - compare
     - index
     - index
     - The elements at the two indices were compared. The array does not change.
   * - ``1``
     - swap
     - index
     - index
     - The elements at the two indices exchanged places.
   * - ``2``
     - write
     - index
     - value
     - The element at ``first`` was set to ``second``, read as the bit pattern
       of an ``i32`` (so ``0xFFFFFFFF`` is ``-1``). Use it for algorithms that
       move values without swapping, such as the merge step of merge sort or
       the shifting of insertion sort.

A program may record any subset of these (an insertion sort that shifts has
compares and writes but no swaps). The counts are what ``--count-operations``
reports, as ``compares``, ``swaps`` and ``writes``; a trace with an event
section but no events of a type counts ``0`` for it, while a trace without an
event section reports nothing (``not reported``). What counts as a compare is
up to the algorithm: record one event for every comparison of two array
elements, not for loop-bound tests.

How a trace is checked when it is read. The harness rejects the whole trace
(``debug`` then says the trace file is malformed and falls back to the input and
output view, and ``benchmark`` shows ``not reported``) when:

* a section kind is neither ``0`` nor ``1``, or the file ends in the middle of
  a section or of a section header;
* a count promises more bytes than the file has left (``snapshot`` lengths and
  ``event_count`` are compared with the remaining bytes before anything is
  read, so a corrupt count cannot make the harness allocate a huge buffer);
* an event has a type other than ``0``, ``1`` or ``2``;
* an event names an index that is not below the length of the array. That
  length is the length of the first snapshot when the trace has a snapshot, and
  the length of the input otherwise. The ``second`` field of a write is a value,
  not an index, and is never range checked.

The harness calls the problem's trace reader only for a trace file that exists
and holds at least one byte; a missing or empty file simply means "no trace",
so a program that does not support traces needs to do nothing.

Replaying events. The array that the events act on is the first snapshot, or the
input when there is no snapshot. Replaying means applying the events in order:
swaps exchange two elements, writes set one, compares do nothing. ``debug``
does this to draw the array after every event (so a trace with events alone is
enough to be stepped through) and, when the trace has events and at least two
snapshots, to check that the replay ends at the **last** snapshot. If it does
not, ``debug`` shows a *trace warning* under every frame naming the first index
where they differ. A warning is not a failure: the run is still judged by its
output alone, and the frames still show the events. It means that either the
events or the snapshots are recorded wrongly, which is the usual symptom of a
missing swap or a write with the wrong index. A first snapshot that is not as
long as the input is a trace warning too: a snapshot shows the whole array.

A small trace, shown as hexadecimal bytes. For the input ``[3, 1, 2]`` an
insertion sort could write one snapshot section with the input and the output,
and one event section:

.. code-block:: text

   00000000                      kind 0: snapshots
   02000000                        snapshot_count = 2
   0300000000000000                  n = 3
   03000000 01000000 02000000          3, 1, 2
   0300000000000000                  n = 3
   01000000 02000000 03000000          1, 2, 3
   01000000                      kind 1: events
   0500000000000000                event_count = 5
   00 00000000 01000000            compare(0, 1)
   01 00000000 01000000            swap(0, 1)      -> 1, 3, 2
   00 01000000 02000000            compare(1, 2)
   01 01000000 02000000            swap(1, 2)      -> 1, 2, 3
   00 00000000 01000000            compare(0, 1)

A writer is short in any language. This is the one the repository's own
instrumented sorters use, in Python (it is the real code of
``tests/instrumented_sort.py``, which is written from this page alone and shares
nothing with the reader it tests):

.. literalinclude:: ../../tests/instrumented_sort.py
   :language: python
   :pyobject: encode_trace

.. warning::

   An event record is **nine** bytes: ``u8``, ``u32``, ``u32``, with nothing
   between the fields. In C and C++ a ``struct`` with those fields is twelve
   bytes, because the compiler pads the ``u32`` fields to a multiple of four,
   so writing the struct as it is (``fwrite(&event, sizeof event, 1, stream)``)
   produces a file the harness reads as garbage. Write the fields one by one, or
   pack the struct:

   .. code-block:: c

      /* Little-endian machines (x86-64, ARM64): the bytes are the numbers as they are. */
      static void write_event(FILE *stream, uint8_t type, uint32_t first, uint32_t second) {
          fwrite(&type, 1, 1, stream);
          fwrite(&first, 4, 1, stream);
          fwrite(&second, 4, 1, stream);
      }

      /* Or, with GCC, Clang and MSVC (#pragma pack), a struct without padding: */
      #pragma pack(push, 1)
      struct event { uint8_t type; uint32_t first; uint32_t second; };
      #pragma pack(pop)   /* sizeof(struct event) == 9 */

   A mismatch shows as ``Unsupported trace kind`` or as an event that names an
   impossible index in the trace error that ``debug`` prints.

A trace with a million events is 9 MB; the harness reads the event section as
one block and keeps nine bytes per event in memory, so counting the operations
of large inputs is practical. A quadratic algorithm still writes a quadratic
number of events, so keep ``--count-operations`` to sizes where that is
affordable.

The format grows by adding kinds: a reader that does not know a kind rejects
the file, as above. The repository's own example, ``examples/sorting/python_sort.py``, wraps the
built-in sort and so writes only the two-snapshot trace. ``tests/instrumented_sort.py``
is a complete insertion sort and merge sort that write both sections; read it
as the model for your own instrumented algorithm.

Fixtures
--------

``algorithm-playground test sorting`` runs these named fixtures, followed by
generated cases (see below). Each one is small enough to read in a failure
report.

* ``empty`` — zero elements
* ``single`` — one element
* ``two_sorted`` — ``[1, 2]``
* ``two_unsorted`` — ``[2, 1]``
* ``two_equal`` — ``[5, 5]``
* ``three_123``, ``three_132``, ``three_213``, ``three_231``, ``three_312``,
  ``three_321`` — all six permutations of three distinct values
* ``already_sorted`` — ``range(10)``
* ``reverse_sorted`` — ``range(9, -1, -1)``
* ``duplicates`` — mixed values with repeats
* ``all_equal`` — eight copies of the same value
* ``alternating_two_values`` — ``0, 1, 0, 1, ...``
* ``duplicated_extremes`` — many copies of both ``INT32_MIN`` and
  ``INT32_MAX``
* ``negatives_mixed`` — negative and positive values
* ``i32_extremes`` — ``INT32_MIN``, ``INT32_MAX``, and values adjacent to
  them
* ``length_15``, ``length_16``, ``length_17`` — scrambled permutations whose
  lengths are a power of two and its neighbors, where block-based and
  recursive algorithms change their behavior
* ``largest_first`` — sorted except that the largest element comes first
* ``smallest_last`` — sorted except that the smallest element comes last

Input generators
----------------

A generator draws all of its randomness from the :class:`random.Random` it is
given, so two invocations with the same ``(seed, size)`` return identical
arrays; it accepts size 0 (the sorting problem's ``minimum_size``) and returns
only values within the i32 range. The first one, ``uniform``, is the default:
``benchmark`` uses it unless ``--distribution`` names others, and the startup
measurement uses it at size 0. ``test`` draws its generated cases from all of
them (``generated:uniform:size=37:seed=1234567``,
``generated:sorted:size=12:seed=5``, ...), taking turns in a pattern that gives
every distribution small and large sizes alike; ``--distribution`` restricts
that to chosen ones. ``debug`` draws from ``small_range`` unless
``--distribution`` says otherwise, because a picture of values between ``-10``
and ``10`` is easier to read than one of random 32-bit numbers. Each generator is
also a benchmark *distribution*; ``algorithm-playground list sorting`` lists
them:

* ``uniform`` — values drawn uniformly from ``[INT32_MIN, INT32_MAX]``
* ``sorted`` — uniform values in ascending order
* ``reversed`` — uniform values in descending order
* ``nearly_sorted`` — ascending order with about 1% of the positions swapped
  with a neighbor at most four positions away (``size // 100`` swaps, at least
  one), so every element is near its place and insertion sort needs about
  linear work
* ``few_unique`` — values taken from a pool of eight random values
* ``all_equal`` — one random value repeated
* ``sawtooth`` — one ascending run of about ``sqrt(size)`` values, repeated
* ``organ_pipe`` — ascending up to the middle, then descending
* ``median_of_three_killer`` — Musser's adversarial sequence, below
* ``small_range`` — values between ``-10`` and ``10``, so many duplicates

The median-of-three killer
~~~~~~~~~~~~~~~~~~~~~~~~~~

A quicksort that picks the median of the first element, the middle element (at
``first + (last - first) // 2``) and the last element of the range as its pivot
is fast on random and on sorted input, but David Musser (*Introspective Sorting
and Selection Algorithms*, 1997) showed an input that makes it quadratic. For a size of ``2k`` with ``k`` even it is the permutation of
``1..2k``

.. code-block:: text

   1, k+1, 3, k+3, 5, k+5, ..., k-1, 2k-1,   2, 4, 6, ..., 2k

(for ``2k = 8``: ``1 5 3 7 2 4 6 8``). The first, middle, and last elements are
``1``, ``2``, and ``2k``, so the pivot is ``2``; the partition splits off two
elements, leaves the rest in the same shape, and every round again removes only
two. The generator keeps the shape for other sizes: a size that is not a
multiple of four uses the next multiple of four and drops the values above the
size, and an odd size appends the largest value to the sequence one smaller.
The ranks are then spread evenly over the i32 range, which keeps the same
order. The sequence does not depend on the seed.

The construction is exact for a Hoare partition that sweeps inwards from both
ends, as in the original SGI standard template library. It is also quadratic
against the variant libstdc++ has used for years, which takes the median of the
*second*, the middle and the *second to last* element, moves it to the front,
and partitions the rest (measured with a cutoff of 16 elements: about four times
the comparisons for every doubling of the size, against about twice for random
input), though with a smaller constant. An algorithm with another pivot rule (a
random pivot, introsort's fall back to heapsort) is unaffected. Benchmark a quicksort on
``uniform`` and ``median_of_three_killer`` and compare the ``growth`` rows to
see which one you have.

Failure reports and shrinking
-----------------------------

Failure reports show a sorted copy of the input as the expected output, cut to
a readable length with the number of values; for a wrong output, the verifier
names the index of the first difference, so the expected and the actual output
are shown as windows around it (``[..., 7, 8, 9, ...] (1000 values, indices 497
to 499 shown)``) and not as their first values. The verifier also names a kind of
failure (``wrong length`` or ``not sorted``), so failures of one kind that shrink
to the same input are reported once. A failing generated input is shrunk
by trying these candidates in order (they are ``shrink_integer_sequence`` of the core:
``shrink_sequence`` followed by ``shrink_integers``) and keeping the first one that fails in the
same way (the same status, the same kind of failure, and for an error the same
kind of error), then starting again from that one:

#. remove a chunk of elements: the halves first, then smaller chunks down to
   single elements;
#. replace every value by ``0``;
#. replace each value by its rank among the distinct values, which keeps the
   order but makes the numbers small;
#. replace one value at a time by ``0`` or by half of itself.

What ``debug`` draws
--------------------

The bars of a frame are **ranks**, not values. Values from the whole i32 range
differ by billions, which makes nearly every bar look equally tall once the axis
is scaled to the largest, so the height of a bar is the rank of its value among
the distinct values of the starting array (the smallest has height 1, equal
values share a height). A value that is not among them, such as one a faulty
write stored, takes the height of the next larger rank. The caption carries the
actual values the event touched (``values now: [2] = 17, [3] = -4``), so nothing
is lost.

Reference executables
---------------------

The repository ships two executables that conform to the contract. Both use
their language's built-in sort; they show the contract, not an algorithm:

* ``examples/sorting/python_sort.py`` — wraps ``sorted``; writes a
  two-snapshot trace (input and output) and no events.
* ``examples/sorting/c_qsort.c`` — wraps libc's ``qsort``; ignores the
  optional trace path so ``debug`` exercises the fallback path.
