CLI reference
=============

All commands are subcommands of ``algorithm-playground``; ``algorithm-playground
--version`` prints the version. Each command (except ``list``) takes the
problem's name as the first positional argument. The commands that run code
(``test``, ``benchmark``, ``debug``) then take the *implementations* to run.

Naming implementations
----------------------

An implementation is a command; see :doc:`executable-contract`. There are three
ways to name one, and they can be mixed in a single invocation:

``IMPLEMENTATION`` (positional, repeatable)
   Either the name of an implementation configured for this problem in a
   :doc:`configuration file <configuration>`, or the path of an existing file
   to run directly. A configured name wins when both match. A value that is
   neither is a usage error that lists the configured names.

``--command TEXT`` (repeatable)
   Command text, split with shell-style quoting, to which the harness appends
   the input, output, and optional trace paths. This is how to run
   interpreted or virtual-machine languages without an executable bit:
   ``--command "node sort.js"`` or ``--command "python3 my_sort.py"``. There is
   no shell, so pipes, variables, and globbing do not apply.

``--name TEXT`` (repeatable)
   The name for the ``--command`` in the same position, shown in tables and
   reports: ``--command "python3 sort.py insertion" --name insertion``. There
   may be fewer names than commands (the others get the default name, below) but
   not more, which is a usage error. It applies to ``--command`` only; a
   configured implementation has its configured name and a file its file name.

*(nothing)*
   With no positional implementation and no ``--command``, every
   implementation configured for the problem runs. Without such entries the
   command exits with code ``2`` and explains both ways to name an
   implementation.

Implementations run in the order given: positional arguments first, then
``--command`` values. Each implementation needs a unique name in tables and
reports. A configured implementation uses its configured name, a file uses its
file name, and a command uses its ``--name`` or else the name of the last of its
arguments that names an existing file without its extension, followed by the
arguments after it (``python3 sort.py`` is called ``sort``, ``python3
tests/instrumented_sort.py insertion`` is called ``instrumented_sort insertion``,
and ``java -jar build/Sort.jar`` is called ``Sort``), or its command text when no
argument does. So two commands that run one script with other arguments stay
apart. When two implementations would share a name (``a/sort`` and ``b/sort``)
both are shown as typed instead. If a duplicate remains, the command exits with
code ``2``.

These options are shared by ``test``, ``benchmark``, and ``debug`` (the first
two are also accepted by ``list``):

``--configuration PATH``
   The configuration file to read. Default: ``algorithm-playground.toml`` in
   the current directory or the nearest parent directory that has one (the
   search stops at a directory containing ``.git``), when there is one; see
   :doc:`configuration`.

``--problem-module MODULE_OR_FILE`` (repeatable)
   Make the problems of a Python module available, in addition to the built-in
   problems, installed plugins, and the ``problem_modules`` of the configuration
   file. The value is a module name, which is looked up in the current directory
   as well as on the import path (``python_paths`` in the configuration file adds
   directories to it), or the path of a ``.py`` file, relative to the current
   directory when it is not absolute. The directory that holds the module (the
   current directory for a module name, the directory of the file for a path)
   stays on the import path for the whole command, so the module can also import
   its neighbors later, from inside a hook. A module that cannot be imported is a
   usage error (exit code ``2``) that says what to try (its directory goes off
   the import path again); a module that loads but registers no problem gives a
   warning on standard error. See :doc:`writing-a-problem`.

``--build / --no-build``
   Run each selected implementation's build command once before using it
   (default), or skip building. Each build is announced. An implementation
   whose build fails is reported once, with the build's output, and is left
   out of the run; the others still run, the failed one is shown as failed in
   the results, and the command exits with code ``1``. When no implementation
   builds, nothing runs and the command exits with code ``1``.

After the builds, the command of every implementation is checked once, without
running it: a name with a slash must be an executable file (relative to the
implementation's working directory), a bare name must be found on the ``PATH``
of the environment the run uses, and the working directory must exist. An
implementation that fails the check is reported once on standard error
(``Cannot run NAME: command is not runnable (permission denied): ...``), shown
as ``cannot run`` where a failed build shows ``build failed``, left out of the
run, and makes the command exit with code ``1``; without the check, a
permission error would be repeated for every case. A script whose interpreter is
missing passes the check and fails when it runs.

``--inherit-environment``
   Give implementations named by path or ``--command`` the full environment of
   the ``algorithm-playground`` process instead of a minimal one. Configured
   implementations use their own ``inherit_environment`` setting.

Exit codes
----------

``0``
   Everything passed.

``1``
   A test failed or errored, a benchmark run failed or produced output that
   did not verify, a build failed, a command cannot be started, ``debug`` ran an
   implementation whose output did not verify, or a hook of the problem raised an exception (the message
   names the hook).

``2``
   Usage or configuration error: unknown problem, unknown implementation,
   no implementation to run, a duplicate name, an unknown ``--reference``, an
   invalid or missing configuration file, a configured problem name that no
   registered problem has, a problem module that cannot be imported, an unknown
   fixture, distribution, or case identifier (or one written with a plus sign,
   leading zeros, underscores, or spaces in a number), options that cannot be
   combined, invalid option values, or a ``--json`` path that cannot be written
   (a directory, a path below a file, a directory without write permission;
   these are checked before anything runs, and so is ``--save-failing-inputs``).

``130``
   The command was interrupted with Ctrl-C. The message ``Interrupted.`` goes to
   standard error, any process the command started is killed first, and in
   ``debug`` the terminal is put back into its normal mode.

Standard output and standard error
----------------------------------

Results go to standard output: tables, the failure messages that explain
them, summary lines, and the path of a written report. Everything that stops
or qualifies a command goes to standard error: usage and configuration errors,
build announcements and build output, warnings (including a problem plugin that
failed to load), a runner error in ``debug``, and progress bars (``test`` and
``benchmark`` show what is running). So ``algorithm-playground benchmark ... > results.txt``
captures the results and still shows the errors in the terminal.

``list``
--------

.. code-block:: console

   $ algorithm-playground list [PROBLEM] [--configuration PATH] \
       [--problem-module MODULE_OR_FILE]...

Print a table of every registered problem with its description and its
*source*: ``built-in``, ``entry point: NAME`` (an installed package),
``configuration: MODULE`` (a ``problem_modules`` entry), or ``option: MODULE``
(``--problem-module``). When a configuration file is found (or given with
``--configuration``), also print a table of its implementations: problem, name,
and command. Installed problem plugins that fail to load are reported as
warnings on standard error and do not stop the command.

With a problem name, ``list`` shows what that problem offers instead:

* its **fixtures**, with the description of each (the same text appears in the
  failure report when the fixture fails);
* its **distributions**, with their descriptions and a
  ``used as`` column that marks the default (the first, used by ``benchmark``)
  and the one ``debug`` prefers, and a note on the smallest size when the
  problem does not start at 0;
* whether it has a **trace format** (``debug`` and ``benchmark
  --count-operations`` need one) and, when it says, the **operations** that a
  benchmark counts from a trace;
* whether it can read its input files, which ``debug --input-file`` needs;
* the configured implementations for that problem.

``test``
--------

.. code-block:: console

   $ algorithm-playground test PROBLEM [IMPLEMENTATION]... \
       [--command TEXT]... [--configuration PATH] [--problem-module NAME]... \
       [--name TEXT]... [--build / --no-build] [--inherit-environment] \
       [--random-cases N] [--maximum-size N] [--seed N] [--distribution NAME]... \
       [--no-fixtures] [--fixture NAME]... [--case IDENTIFIER]... \
       [--shrink / --no-shrink] [--maximum-failures N] [--verbose] \
       [--timeout SECONDS] [--keep-temporary-files] \
       [--save-failing-inputs DIRECTORY] [--json FILE]

Run a set of *cases* against each selected implementation on identical inputs
and check every output with the problem's verifier. A case is either a
**fixture**, a small hand-written input with a name (``empty``,
``reverse_sorted``), or a **generated case**, an input produced by one of the
problem's seeded input distributions at some size. By default ``test`` runs
every fixture followed by 20 generated cases whose sizes range from the
problem's smallest size (0 for most problems) to 100, with small sizes favored
because most bugs live there. The distributions take turns, shifted by one every
round, so each of them gets small and large sizes alike. The same options always
produce the same cases.

Every case has a stable *identifier* that is printed in the results and
accepted by ``--case``:

``fixture:NAME``
   The fixture called ``NAME``.

``generated:DISTRIBUTION:size=N:seed=N``
   What the distribution ``DISTRIBUTION`` returns for size ``N`` and seed ``N``,
   for example ``generated:uniform:size=37:seed=1234567``. Each generated case has
   its own seed, derived from ``--seed`` and the position of the case. The
   numbers are plain integers: ``size=05``, ``size=+5``, ``size=1_0`` and a number
   with spaces are usage errors, not guesses.

The result is a matrix with one column per implementation. The fixtures are one
row, ``fixtures``, that counts how many passed (``24/24``); a fixture that some
implementation did not pass gets a row of its own below it, whose cell is
``PASS``, ``FAIL`` (the run completed but the output is wrong), or ``ERROR`` (the
run itself failed: crash, timeout, missing or malformed output file). With
``--verbose`` every fixture has a row and there is no counting row. The generated
cases are summarized by distribution, one row each, showing how many passed:

.. code-block:: text

   test results — sorting
   ┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
   ┃ case                     ┃ drops_last.py ┃ unsorted.py ┃
   ┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
   │ fixtures                 │     11/24     │    7/24     │
   │   two_unsorted           │     PASS      │    FAIL     │
   │   three_132              │     PASS      │    FAIL     │
   │   already_sorted         │     FAIL      │    PASS     │
   │   reverse_sorted         │     FAIL      │    FAIL     │
   │   ...                    │      ...      │     ...     │
   ├──────────────────────────┼───────────────┼─────────────┤
   │ uniform                  │      1/1      │     1/1     │
   │ sorted                   │      1/1      │     1/1     │
   │ reversed                 │      0/1      │     0/1     │
   │ all_equal                │      0/1      │     1/1     │
   └──────────────────────────┴───────────────┴─────────────┘
   drops_last.py: 19 of 32 cases did not pass
   FAIL drops_last.py on generated:reversed:size=7:seed=3299718969
       message: Output length 6 does not match input length 7
       input: [1620732704, 942543527, 675388264, ...] (7 values)
       expected: [..., 1620732704] (7 values, index 6 shown)
       actual: [..., 942543527] (6 values, index 5 shown)
       shrunk input: [0, 0, 0, 0, 0, 0]
       shrunk expected: [0, 0, 0, 0, 0, 0]
       shrunk actual: [0, 0, 0, 0, 0]
       shrunk message: Output length 5 does not match input length 6
       reproduce: algorithm-playground test sorting --command /home/you/drops_last.py --case generated:reversed:size=7:seed=3299718969
       same failure on: generated:nearly_sorted:size=22:seed=3858759722, generated:few_unique:size=30:seed=1281988302
   FAIL drops_last.py on fixture:all_equal
       message: Output length 7 does not match input length 8
       fixture: every element equal
       input: [7, 7, 7, 7, 7, 7, 7, 7]
       expected: [7, 7, 7, 7, 7, 7, 7, 7]
       actual: [7, 7, 7, 7, 7, 7, 7]
       reproduce: algorithm-playground test sorting --command /home/you/drops_last.py --case fixture:all_equal
       same failure on: fixture:negatives_mixed, fixture:already_sorted, fixture:reverse_sorted, fixture:duplicates, fixture:alternating_two_values, and 10 more
   unsorted.py: 22 of 32 cases did not pass
   ...
   drops_last.py: 13/32 cases passed (11/24 fixtures, 2/8 generated)

**Failure details.** Below the matrix, the failures of each implementation are
described under its name. For each failing case the report gives the case
identifier, the verifier's ``message``, a ``fixture`` line with the description
of the fixture when the case is one, the ``input``, the ``expected`` output when
the problem can say what a correct answer is, the ``actual`` output (left out
when the run produced none, as for an error), a one-line ``reproduce`` command,
and where the input was saved when ``--save-failing-inputs`` is given. Each value
is shortened to fit on one line of the terminal (the width of the terminal
less 24 characters, but at least 40; the JSON report holds the same text), and
when the verifier names the position of the first difference, the shortened
expected and actual outputs are windows around it (``[..., 1620732704] (7
values, index 6 shown)``) instead of the start. The case identifier always
regenerates the complete input. For an error, every line of the message is
shown, including the implementation's standard error.

Failures that come down to the same thing are shown once, with the other cases
listed after ``same failure on``, so a missing command or a crash that happens on
every case is not repeated and 40 failing cases that shrink to the same two
numbers are one block. Cases that shrank to the same input are one failure, and
so are cases with the same kind of failure when that says something: the
``category`` the problem's verifier gave a wrong answer (sorting has ``wrong
length`` and ``not sorted``) or the kind of run failure (a timeout, an exit
code, a signal); the rest are grouped by message. The blocks are ordered by the
size of the failing input, smallest first: shrunk inputs, then fixtures, then
generated cases by size. At most ``--maximum-failures`` of these blocks are
described per implementation; the remaining failing cases are only listed by
identifier (the JSON report always holds all of them).
An implementation whose build failed is not run: its column shows
``build failed`` in every row and its summary line reads
``name: build failed, not run`` (the build output was printed once, on
standard error, when the build failed). The same goes for an implementation
that cannot be started, with ``cannot run`` in place of ``build failed``. The
exit code is ``1`` if any cell is not ``PASS`` or any build failed or command
cannot run, so the command is CI-friendly.

**Saving failing inputs.** ``--save-failing-inputs DIRECTORY`` writes the input
of every failing case, in the problem's binary input format (the file the
implementation received), to
``DIRECTORY/IMPLEMENTATION/CASE/input.bin``, and the shrunk input, when
shrinking found one, to ``shrunk-input.bin`` next to it. The implementation name
and the case identifier are made safe for a file system by replacing every
character other than letters, digits and ``._=+-`` with an underscore. A name
that needed any change (a character was replaced, it has an upper-case letter
that could collide with a lower-case one on a file system that ignores case, or
it was cut for being very long) ends in a dash and eight hexadecimal digits of
the SHA-256 of the original, so that two different names never share a
directory (``fixture_empty-bcb2cb5e``); the failure block prints the paths. A saved input
survives the run, can be given to an implementation by hand, and can be run
under ``debug`` with ``--input-file``, without regenerating it or knowing its seed.

**Shrinking.** When a *generated* case fails, the input is usually bigger than
it needs to be. With ``--shrink`` (the default) the harness asks the problem
for smaller variants of the input (dropping elements, simplifying values),
runs them against the implementation that failed, keeps any that still fail,
and repeats. The smallest failing input found is shown as ``shrunk input``,
with its own expected output, actual output, and message. A candidate only
counts when it fails *the same way* as the original: the same status (a wrong
answer does not shrink into a crash), the same category (a verifier that names
kinds of wrong answer keeps the kind) and, for an error, the same kind of error
(the same exit code, the same signal, a timeout stays a timeout). A candidate
that equals its input, or that the problem's ``check_input`` hook rejects as not
a valid input (an array that has to be sorted, no longer sorted), is skipped.
Shrinking is bounded: at most 200 candidates per case (skipped candidates count
too, so a hook that never stops cannot keep it going), at most three failing
cases per implementation, and 30 seconds per implementation; a candidate runs
with a timeout no longer than the time that is left, and one that times out
only because of that limit proves nothing. When shrinking stops because a bound
was reached, or a case is not shrunk because the bounds of its implementation
were used up, the failure says so in a ``shrink note`` (and in the JSON report):
for example that shrinking stopped after 200 candidates and a smaller failing
input may exist. If the problem's ``shrink`` or ``check_input`` hook raises, the
failure is reported with a ``shrink note`` as well and keeps whatever was found
before. A problem that does not define a ``shrink``
hook reports no shrunk input. Two kinds of failure are not shrunk, and the
``shrink note`` says why: one that the problem's own hooks cause (category
``serialization``, when ``serialize_input`` cannot write the input, or
``verification error``, when ``verify`` raises), because a smaller input says
nothing about the implementation, and a timeout when the time that is left for
shrinking is shorter than the timeout, because no candidate could show that it
times out too. Fixtures are not shrunk. A shrunk input cannot be
replayed by name; the ``reproduce`` command reproduces the original case, and
shrinking runs again.

**Reproducing.** The ``reproduce`` command names the implementation (by its
configured name, or with ``--command`` and the full command) and the failing
case, so pasting it runs exactly the failing input again. Every option you passed
that can change the outcome is repeated in it: ``--timeout`` when it is not the
default, ``--inherit-environment`` and ``--no-build``, and for finding the
problem ``--configuration`` and ``--problem-module``.

**Progress.** While the cases run, a progress line on standard error shows
which implementation and case are running, and when a failure is being
shrunk.

Choosing cases:

``--random-cases N``
   Number of generated cases (default: ``20``; ``0`` runs fixtures only). They
   are spread over the distributions in turn, so with several distributions
   each gets a share.

``--maximum-size N``
   Largest size of a generated case (default: ``100``). Sizes are spread from
   ``0`` to ``N`` with small sizes over-represented.

``--seed N``
   Seed that determines every generated case (default: ``0``). A different
   seed explores different inputs, which is how to hunt for a rare bug.

``--distribution NAME`` (repeatable)
   Draw the generated cases from the named distributions only (default: all of
   the problem's distributions). An unknown name is a usage error that lists
   the available ones.

``--no-fixtures``
   Skip the curated fixtures.

``--fixture NAME`` (repeatable)
   Run only the named fixtures, in the order given. This is the same as
   ``--case fixture:NAME``.

``--case IDENTIFIER`` (repeatable)
   Run only the cases with these identifiers, in the order given, instead of
   the planned cases. Use it to reproduce a failure. A case named twice (two
   ``--case`` values, or ``--fixture single`` with ``--case fixture:single``)
   runs once. ``--fixture`` and ``--case`` select exact cases, so combining them
   with ``--random-cases``, ``--maximum-size``, ``--seed``, ``--distribution``,
   or ``--no-fixtures`` is a usage error.

Other options:

``--shrink / --no-shrink``
   Shrink failing generated cases (default) or report them as generated.

``--maximum-failures N``
   Failure blocks to describe in full per implementation (default: ``5``).

``--verbose``
   Show a row for every fixture in the matrix, not only for the fixtures that
   some implementation did not pass.

``--save-failing-inputs DIRECTORY``
   Write the input of every failing case, and its shrunk input, below
   ``DIRECTORY`` (see above). The directory is created as needed; a path that is
   a file, or that cannot be created, is a usage error before anything runs.

``--timeout``
   Per-case timeout in seconds (default: ``60``).

``--keep-temporary-files``
   Preserve the per-run scratch directory after the run so you can inspect
   the binary input, output, and any trace files the implementation produced.
   The message of every failing or erroring case ends with the line
   ``Temporary files were kept in <directory>``.

``--json FILE``
   Write the complete test report to ``FILE``, creating missing parent
   directories. Everything the terminal report shows is in it, without the
   limit on described failures. The path is checked before anything runs (a
   directory, a parent that is a file, or a directory without write permission is
   a usage error with exit code ``2``), and so is a failure while writing the
   file. ``report`` says what kind of report it is and ``format_version`` changes
   whenever a key is renamed, removed, or reinterpreted (currently ``2``; version
   2 added ``report``, ``settings``, and the ``command``, ``files``,
   ``inherit_environment`` and ``timeout_seconds`` of every implementation, renamed
   the ``generator`` key of a case to ``distribution``, and added ``shrink_note``
   to every outcome; ``cannot_run``, ``category``, ``saved_input`` and
   ``saved_shrunk_input`` are new keys that did not change the version because
   they only add to it):

   .. code-block:: text

      {
        "report": "test",
        "format_version": 2,
        "problem": "sorting",
        "passed": false,
        "settings": {
          "cases": "planned" | "explicit",
          "seed", "random_cases", "maximum_size",    (null when explicit)
          "distributions": ["uniform", ...],         (null when explicit)
          "include_fixtures": true | false,          (null when explicit)
          "shrink": {"enabled", "maximum_shrunk_cases", "maximum_runs",
                     "time_budget_seconds"},
          "timeout_seconds"
        },
        "cases": [
          {"identifier": "fixture:empty", "kind": "fixture", "fixture"},
          {"identifier": "generated:uniform:size=12:seed=5", "kind": "generated",
           "distribution", "size", "seed"}
        ],
        "implementations": [
          {"name", "command": [...], "working_directory",
           "inherit_environment", "timeout_seconds" (null: the default),
           "files": [{"path", "sha256"}],
           "build_failure": null or the build output,
           "cannot_run": null or why the command cannot be started,
           "summary": {"passed", "failed", "errors"},
           "outcomes": [
             {"case": the identifier, "status": "passed" | "failed" | "error",
              "category" (for example "not sorted" or "timeout"; "" for a pass),
              "message",
              "failure": null or {"input", "expected", "actual"},
              "saved_input": null or the path of the file written by
                             --save-failing-inputs,
              "saved_shrunk_input": null or the path of the shrunk input,
              "shrink_note": null or why shrinking did not do its job or finish,
              "shrunk": null or {"case", "message", "input", "expected", "actual"}}
           ]}
        ],
        "host": {...},
        "metadata": {...}
      }

   The outcomes of an implementation follow the order of ``cases``. ``expected``
   and ``actual`` are ``null`` when there is nothing to show. An implementation
   whose build failed or that cannot run has no outcomes. ``settings.cases`` is
   ``explicit`` when
   ``--fixture`` or ``--case`` named the cases, and the planning keys are then
   ``null``. ``passed`` is true only when every outcome passed and no build
   failed and every command could run.

``benchmark``
-------------

.. code-block:: console

   $ algorithm-playground benchmark PROBLEM [IMPLEMENTATION]... \
       [--command TEXT]... [--configuration PATH] [--problem-module NAME]... \
       [--name TEXT]... [--build / --no-build] [--inherit-environment] \
       [--reference NAME] [--distribution NAME]... [--seed N] \
       [--sizes 1000,10000,100000] \
       [--repetitions 5] [--warmup 1] [--timeout SECONDS] \
       [--json FILE] [--plot / --no-plot] [--verify / --no-verify] \
       [--subtract-startup-time] [--count-operations]

For each distribution and size, run ``--warmup`` discarded iterations
followed by ``--repetitions`` measured iterations of every selected
implementation. A *distribution* is one of the problem's input distributions
(``--distribution NAME``, repeatable); without the option only the problem's
default distribution is measured, the first one it lists (for sorting,
``uniform``). All implementations receive identical seeded inputs.
Repetitions are interleaved round-robin (repetition 1 of every implementation,
then repetition 2, and so on), so drift in system load affects every
implementation equally. An unknown distribution is a usage error (exit code
``2``) that lists the available ones, and so is a size below the problem's
smallest size.

Before the sized runs, each implementation is also timed on the smallest input
(the problem's default distribution at its ``minimum_size``, which is 0 for most
problems, an empty input) with the same warmup and repetition counts. That row,
labelled ``startup``, shows the fixed cost every run
pays: process startup, interpreter or runtime initialization, and file I/O.
For an interpreted implementation this can dominate small sizes. The startup
is measured once per implementation, however many distributions are selected.

**Reading the tables.** Each table has a title line above it, and the times in a
table share one unit (s, ms, us or ns), chosen so that the typical time is at
least one, which the column headers name (``median (ms)``); a table of several
implementations names the unit and the reference under it. With one distribution
a line under the table names it (``distribution: uniform``); with several, each
distribution has a header row and its own block of rows separated by a rule.

**One implementation.** The table has one row per size with the minimum,
median, standard deviation, and sample count of the wall-clock time, followed
by a note about the startup cost. If the run fails part-way, the rows that
completed are still printed, followed by the failure.

**Several implementations.** The table has one row per size (plus the startup
row) and one column per implementation. Each cell shows the median and, in
parentheses, the ratio to the reference implementation:

.. code-block:: text

   benchmark — sorting
   ┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
   ┃     size ┃ instrumented_sort insertion ┃ instrumented_sort merge ┃
   ┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
   │  startup │              47.087 (1.00x) │          45.245 (0.96x) │
   ├──────────┼─────────────────────────────┼─────────────────────────┤
   │  uniform │                             │                         │
   │      100 │              42.000 (1.00x) │          48.923 (1.16x) │
   │    1,000 │             138.859 (1.00x) │          48.496 (0.35x) │
   │    3,000 │             782.356 (1.00x) │          89.011 (0.11x) │
   │   growth │               ~ n (n^0.81)* │       ~ log n (n^0.15)* │
   ├──────────┼─────────────────────────────┼─────────────────────────┤
   │   sorted │                             │                         │
   │      100 │              47.676 (1.00x) │          50.904 (1.07x) │
   │    1,000 │              48.405 (1.00x) │          49.069 (1.01x) │
   │    3,000 │              90.590 (1.00x) │          83.053 (0.92x) │
   │   growth │           ~ log n (n^0.16)* │       ~ log n (n^0.12)* │
   └──────────┴─────────────────────────────┴─────────────────────────┘
   median in ms, ratio to instrumented_sort insertion
   * The medians of this series are too close to the startup time to tell how the time grows; use larger sizes.

A ratio below ``1.00x`` means faster than the reference. The ratio is omitted
when it is not meaningful (the reference has no measurement or a median that
is not positive).

**Growth.** When at least three sizes of a distribution have a positive
startup-adjusted median, the block ends with a ``growth`` row that gives, per implementation, how
the time grows with the size: the best-fitting class and the fitted exponent,
for example ``~ n log n (n^1.21)``. The exponent ``k`` of a power law
``time ~ n^k`` is fitted to the medians by least squares on log-log axes
(``n^1.04`` for an algorithm that scales about linearly, ``n^2.00`` for a
quadratic one). The class is the one of ``1``, ``log n``, ``n``, ``n log n``,
``n^2`` and ``n^3`` that fits best: each is fitted as ``time ~ c * f(n)``, also by
least squares on the logarithms, with the constant ``c`` free, and the one with
the smallest residual wins (a tie goes to the slower-growing class). Only
points with a size of at least 2 and a positive value take part in the class
fit, and without three of them the row shows the exponent alone. The fit always
uses each median of the unadjusted samples minus the median of the
implementation's startup runs (the statistic that the reliability check below
compares with), whether or not ``--subtract-startup-time`` is given: a fixed startup cost would otherwise flatten every curve toward ``1``, so
the growth describes the algorithm's work, not process startup. Points whose
startup-adjusted median is not positive (work below the noise) are ignored, and an implementation
without enough points shows ``-``. Growth is estimated per distribution, so a
sorting algorithm that is linearithmic on ``uniform`` and quadratic on
``median_of_three_killer`` shows both.

A timing growth that cannot be trusted is marked with a star: when fewer than
three sizes have a median (of the unadjusted samples) above the median of the
implementation's startup runs by more than three standard deviations of those
runs and 10 percent of the startup median, the series is mostly process startup,
and the fitted growth says little about the algorithm. The note under the table
then asks for larger sizes. The JSON report has the same verdict as ``reliable``.
Counts of operations are exact and are never marked.

**Operation counts.** With ``--count-operations`` the benchmark also reports
how many operations each implementation performed, which unlike a wall time is
exactly reproducible and says what an algorithm does rather than how fast the
machine runs it. After the timed runs of every distribution and size, each
implementation is run once more, untimed, with a trace path, and the problem's
``operation_counts`` are read from the trace it writes (for sorting: the
``compares``, ``swaps`` and ``writes`` of the event section described in
:doc:`problems/sorting`). The counting run is not part of any timing. The counts
go in tables below the timing table, one per counted operation, titled with its
name (``compares — sorting``): one row per size, one column per implementation,
and a ``growth`` row per distribution with the same class and exponent
(``~ n^2 (n^1.97)``) fitted to the counts by the method of the timing growth
(this excerpt of a run on sizes 100 to 3,000 shows two of the three tables):

.. code-block:: text

   compares — sorting
   ┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
   ┃     size ┃ instrumented_sort insertion ┃ instrumented_sort merge ┃
   ┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
   │  uniform │                             │                         │
   │      100 │                       2,794 │                     539 │
   │    1,000 │                     250,479 │                   8,694 │
   │    3,000 │                   2,252,743 │                  30,936 │
   │   growth │              ~ n^2 (n^1.97) │      ~ n log n (n^1.19) │
   ├──────────┼─────────────────────────────┼─────────────────────────┤
   │   sorted │                             │                         │
   │      100 │                          99 │                     316 │
   │    1,000 │                         999 │                   4,932 │
   │    3,000 │                       2,999 │                  16,828 │
   │   growth │                ~ n (n^1.00) │      ~ n log n (n^1.17) │
   └──────────┴─────────────────────────────┴─────────────────────────┘
   writes — sorting
   ┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
   ┃     size ┃ instrumented_sort insertion ┃ instrumented_sort merge ┃
   ┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
   │  uniform │                             │                         │
   │      100 │                           0 │                     672 │
   │    1,000 │                           0 │                   9,976 │
   │    3,000 │                           0 │                  34,904 │
   │   growth │                           - │      ~ n log n (n^1.16) │
   └──────────┴─────────────────────────────┴─────────────────────────┘

An implementation that writes no trace or a trace without events shows ``not
reported`` in place of its counts, in every table, and is not an error; if no
implementation reports anything, a note replaces the tables. Counts come only from a counting run
whose output verifies (unless ``--no-verify``) and whose trace is well formed. A
cell says why when they are missing for another reason: ``malformed trace``
(the message of the trace error follows below the tables) or ``output did not
verify`` (the verifier's message follows below the tables); neither is a failure
of the implementation, and its timings are unaffected. A counting run that fails
(the program crashes or times out when given a trace path) shows ``counting
failed`` and fails the implementation for the rest of that distribution like a
timed run does, but its timings are kept. Counts need a
trace, and a trace of a quadratic algorithm is quadratic in size, so use
smaller ``--sizes`` than for timing. The growth of a count is exact
for what the algorithm did (insertion sort's compares on ``reversed`` input
are ``~ n^2``, on ``sorted`` input ``~ n``, merge sort's ``~ n log n`` with an
exponent of about 1.1 to 1.2 over small sizes, the apparent exponent of
``n log n``).

If an implementation fails (it crashes, times out, writes malformed output,
cannot be given its input, or its output does not verify), the cell where it
failed says ``failed``, the cells it never reached because of that failure say
``skipped``, its failure message is printed below the table, and the remaining
implementations carry on. A failure stops the implementation only in the
distribution it happened in: its later distributions still run, and only the
remaining sizes of the failed distribution are skipped. A failure of the startup
run, on the other hand, fails the startup cell and skips everything. A generator
of the problem that raises is a failure of its distribution, not of an
implementation: every unmeasured cell of that distribution says ``failed`` for
every implementation, the message is printed once, the other distributions still
run, and the exit code is ``1`` (stage ``distribution`` in the JSON report). The
problem's ``generators`` hook, and the generator of the startup input, have to
work, because nothing can be measured without them: if one raises, the message
names it and the command exits with code ``1`` before anything runs. An
implementation whose build failed is not run at all: it is ``failed`` in every
cell and in the JSON report (a failure of stage ``build`` holds the build
output), and the build output itself was printed once, on standard error, when
the build failed. So is an implementation whose command cannot be started (stage
``cannot run``). The exit code is then ``1``.

With ``--plot`` (the default), the median time against size is drawn on one
terminal chart with a legend: one line per implementation, or one per
implementation and distribution (labelled ``implementation (distribution)``)
when several distributions are selected. Failed implementations contribute the
sizes they completed. The chart is drawn only when standard output is a
terminal, so ``benchmark ... > results.txt`` holds the tables without chart
escape codes.

``--distribution``
   Name of an input distribution to measure; repeat it to measure several
   (``--distribution uniform --distribution sorted``). Names are those listed
   by ``list PROBLEM`` (see :doc:`problems/sorting` for sorting). Default: the
   problem's default distribution only.

``--reference``
   The implementation that ratios are computed against (default: the first
   selected one that was built and can be started). It must be one of the
   selected implementation names.

``--subtract-startup-time``
   Subtract the mean of an implementation's own startup runs from each of
   its measured samples, so the table, plot and JSON estimate algorithm work
   instead of total run time. Off by default. It does not change the growth,
   which always subtracts the median startup time (see above). Results are not
   clamped: a negative value means the work is smaller than the run-to-run noise
   of the measurement. The JSON report always keeps the unadjusted times in
   ``raw_samples_seconds`` and the startup runs under ``startup``.

``--count-operations``
   Run each implementation once more per distribution and size with a trace
   path, untimed, and report the operations it counted with their growth (see
   above). Off by default, because it doubles the number of runs of the
   fastest sizes and needs implementations that write traces. For a problem
   without a trace format it has no effect: a warning on standard error says that
   the problem does not define operation counts, and no counting run is made.

``--seed``
   Seed for the random number generator used to produce the input
   (default: ``0``).

``--sizes``
   Comma-separated list of input sizes (default: ``1000,10000,100000``).
   Underscores are allowed for readability (for example ``--sizes 100_000``). Each
   size may appear once; repeating one is a usage error.

``--repetitions``
   Number of measured runs per size (default: ``5``).

``--warmup``
   Number of discarded runs per size before measurement starts
   (default: ``1``).

``--timeout``
   Per-invocation timeout in seconds (default: ``60``). It must be a finite
   number; ``nan`` and ``inf`` are usage errors, as for every command.

``--verify``
   Verify each measured run's output before counting its sample. Disable
   with ``--no-verify`` to remove verification overhead from the timings.

``--json``
   Path to write a JSON report; it is checked before anything runs, like the
   path of ``test --json``. It records what kind of report it is, the format
   version, the problem, the settings, the host, and the package version, and for
   each implementation its name, command, working directory, the SHA-256 of every
   file the command refers to, its failures, the startup measurement, one result
   per distribution and size, and the time growth per distribution. The
   summary fields describe the reported samples, which are sorted;
   ``raw_samples_seconds`` holds the unadjusted wall times in the order the runs
   happened. Results are listed distribution by distribution, in the order of
   ``settings.distributions``, and by size within each. ``format_version``
   changes whenever a key is renamed, removed, or reinterpreted (currently ``6``;
   version 2 renamed ``case_name`` to ``case_identifier`` and added
   ``distribution`` and ``settings.distributions``; version 3 added
   ``settings.count_operations``, ``operation_counts`` and ``operation_growth``;
   version 4 added ``report``, renamed ``growth`` to ``time_growth``, replaced
   the single ``failure`` text by the ``failures`` list, added
   ``inherit_environment`` and ``timeout_seconds`` to every implementation, and
   added ``operation_issue`` to every result; version 5 turned each growth from
   the bare exponent into an object that also names the best-fitting class, and
   added the stage ``cannot run`` to the failures; version 6 added the stage
   ``distribution`` and made the time growth subtract the median startup time
   instead of the mean):

   .. code-block:: text

      {
        "report": "benchmark",
        "format_version": 6,
        "problem": "sorting",
        "settings": {"seed", "sizes", "repetitions", "warmup",
                     "timeout_seconds", "verify_outputs",
                     "subtract_startup_time", "count_operations",
                     "distributions": ["uniform", ...]},
        "implementations": [
          {"name", "command", "working_directory",
           "inherit_environment", "timeout_seconds" (null: the default),
           "files": [{"path", "sha256"}],
           "failures": [{"stage": "build" | "cannot run" | "startup" | "measurement"
                                 | "distribution",
                         "distribution" (null unless measurement or distribution),
                         "size" (null unless measurement),
                         "message"}],
           "startup": {...},
           "results": [{"distribution", "size",
                        "case_identifier" (for example
                        "generated:uniform:size=1000:seed=0"),
                        "operation_counts": null or {"compares", "swaps",
                                                     "writes"},
                        "operation_issue": null or {"kind", "message"},
                        "samples_seconds", "raw_samples_seconds",
                        "minimum_seconds", "median_seconds", "mean_seconds",
                        "standard_deviation_seconds"}],
           "time_growth": {"uniform": {"exponent": 1.04, "class": "n",
                                       "reliable": true},
                           "sorted": null, ...},
           "operation_growth": {"uniform": {"compares": {"exponent": 1.12,
                                                         "class": "n log n"},
                                            "swaps": null, ...}, ...}}
        ],
        "host": {...},
        "metadata": {...}
      }

   ``failures`` is empty for an implementation that completed everything. A
   ``measurement`` failure names the distribution and the size at which it
   happened; the sizes of that distribution after it were not run (they are the
   ``skipped`` cells of the table, and no result exists for them or for the
   failed size, except that a failed counting run keeps its timing result).
   ``time_growth`` has one entry per selected distribution: the growth fitted
   to the medians of that distribution's results minus the median startup time
   (see above) as an object with
   the ``exponent``, the best-fitting ``class`` (``"1"``, ``"log n"``, ``"n"``,
   ``"n log n"``, ``"n^2"`` or ``"n^3"``, or ``null`` when fewer than three
   points could be compared) and ``reliable``, or ``null`` when fewer than three
   startup-adjusted medians are positive. ``operation_counts`` is ``null`` for a
   result without counts: counting was off, the implementation reported none, or
   ``operation_issue`` says why it could not: ``kind`` is ``malformed trace``,
   ``output did not verify`` or ``counting failed``. The names inside the counts
   are the problem's own. ``operation_growth`` has one entry per selected
   distribution, which maps each operation the implementation reported to the
   growth fitted to its counts (an object with ``exponent`` and ``class``, as for
   the time but without ``reliable``; ``null`` when fewer than three sizes had a
   positive count) and is empty when it reported nothing.

``--plot``
   Draw a terminal plot of size against median time using ``plotext``, when
   standard output is a terminal. Disable with ``--no-plot``.

``debug``
---------

.. code-block:: console

   $ algorithm-playground debug PROBLEM [IMPLEMENTATION] \
       [--command TEXT] [--configuration PATH] [--problem-module NAME]... \
       [--name TEXT] [--build / --no-build] [--inherit-environment] \
       [--seed N] [--size N] [--distribution NAME] \
       [--fixture NAME] [--case IDENTIFIER] [--input-file PATH] \
       [--auto-advance] [--delay-milliseconds N] [--timeout SECONDS]

Take a single input (the fixture named by ``--fixture``, the case with the
identifier given to ``--case``, the input saved in the file given to
``--input-file``, or a seeded one of ``--size`` from a
distribution of the problem: ``--distribution``, else the one the problem prefers
for debugging, else its default), invoke **one** implementation with a
trace path, and step through the resulting trace. Naming zero or several implementations is a
usage error (exit code ``2``), except that a configuration with exactly one
implementation for the problem needs no argument.

If the problem has a trace format and the implementation does not write a
non-empty trace file, ``debug`` prints a friendly message explaining how to add
trace support and falls back to the problem's input and output view, which it
also does for a trace with no frames. A problem without a trace format
(``list PROBLEM`` says so) gets no trace path at all: ``debug`` says that the
problem has no trace format, so there is no trace to step through, and shows the
input and output view. A failed run exits with code ``1``, and so
does a run whose output does not verify (after the visualization is shown). An
output that does not verify is described like a failure of ``test``, under the
message: the ``input``, the ``expected`` output when the problem knows it, and the
``actual`` output, each shortened to the width of the terminal. The
hooks of the problem that ``debug`` calls (``verify``, ``input_output_frame``,
``trace_frames``, ``trace_warnings``, and the drawing of each frame) are guarded:
if one raises, the message names it and the exit code is ``1``, never a
traceback. If ``verify`` raises, the output is not checked (``Output not
checked``) but the picture is still shown.

**What is shown.** The problem turns the trace into *frames*, one per step, and
the stepper plays them back; each frame is a picture with a caption. For
sorting (see :doc:`problems/sorting` for the trace format):

* a trace with **events** has a frame for the starting array and one more per
  event, drawn after the event. The bars the event touched have another color
  (compared, swapped, or written, named in the chart's legend) and the caption
  names the event, the values it touched and the operations done so far, for
  example ``event 7 / 37: swap(2, 3)``, ``values now: [2] = 17, [3] = -4`` and
  ``so far: 5 compares, 3 swaps, 0 writes``. The bar heights are ranks among the
  starting values, not the values, so that huge values stay readable (see
  :doc:`problems/sorting`). A trace with events alone (no snapshots) is replayed
  from the input.
* a trace with only **snapshots** has a frame per snapshot, and the positions
  that changed since the previous snapshot have another color.
* when a trace has events and snapshots, the frames follow the events, and the
  harness checks that replaying the events ends at the last snapshot. If not, a
  yellow ``Trace warning`` under every frame names the first index where they
  differ. A first snapshot that is not as long as the input is a warning as well.
  They are warnings: the run still passes or fails on its output.

**Keys.** On a terminal each key acts at once, without Enter:

.. list-table::
   :widths: 25 75

   * - right arrow, ``n``, Enter
     - next frame
   * - left arrow, ``p``
     - previous frame
   * - ``g``
     - jump: asks for a frame number (1 to the number of frames)
   * - space
     - pause or resume auto-advance
   * - ``q``
     - quit

Ctrl-C ends ``debug`` with the terminal restored and exit code ``130``. A key
that is more than one byte (an arrow with a modifier, ``é``) and a bracketed paste
each give one ``Unknown key`` message, not several.

When standard input is not a terminal (a pipe, a file, or a platform without
``termios``) the stepper reads one command per line instead: ``n``, ``p``,
``g NUMBER``, ``pause``, ``q`` (an empty line is ``n``), and quits when the input
ends. That makes a session scriptable, for example
``printf 'n\nn\ng 20\nq\n' | algorithm-playground debug sorting ...``. The
screen is cleared between frames only on a terminal.

Options:

``--seed``
   Seed for generated input (default: ``0``).

``--size``
   Size of generated input (default: ``16``, or the problem's smallest size if
   that is larger).

``--distribution``
   Name of the distribution to generate from. Default: the distribution the
   problem prefers for debugging (``small_range`` for sorting, because a few
   small values make a readable chart), else its default. An unknown name is a
   usage error.

``--seed``, ``--size`` and ``--distribution`` generate an input, so combining
any of them with ``--fixture``, ``--case`` or ``--input-file``, which name one, is
a usage error, as is combining those three with each other.

``--fixture``
   Use the named fixture (see ``test``) as the input instead of generating
   one. An unknown name is a usage error that lists the fixtures.

``--case``
   Use the case with this identifier, for example
   ``generated:uniform:size=37:seed=1234567`` from a failure report, as the
   input.

``--input-file``
   Use the input in this file as the input. The file is in the problem's binary
   input format, for example one written by ``test --save-failing-inputs`` or
   the ``input.bin`` kept by ``--keep-temporary-files``, and the problem reads
   it with its ``deserialize_input`` hook (``list PROBLEM`` says whether it
   has one; sorting does). A problem without the hook, or a file that is not
   in the format, is a usage error.

``--auto-advance``
   Start playing: move to the next frame after the delay, until the last
   one. Space pauses and resumes it, and a manual step keeps it playing. With
   line input there is nothing to interrupt a running playback, so it simply
   waits the delay between frames.

``--delay-milliseconds``
   Delay between auto-advanced frames in milliseconds (default: ``250``).

``--timeout``
   Per-invocation timeout in seconds (default: ``60``).
