Adding a new problem
====================

Adding a problem means subclassing
:class:`~algorithm_playground.core.problem.Problem`, implementing its abstract
methods, and decorating the class with
:func:`~algorithm_playground.core.registry.register_problem`. The CLI picks
up the new problem automatically once its module is imported.

Minimal skeleton
----------------

.. code-block:: python

   from collections.abc import Iterator
   from pathlib import Path

   from algorithm_playground.core.problem import (
       BenchmarkCase,
       Problem,
       TestCase,
       VerificationResult,
   )
   from algorithm_playground.core.registry import register_problem


   @register_problem
   class MyProblem(Problem[InputT, OutputT, TraceT]):
       name = "my-problem"
       description = "One-line description shown in `algorithm-playground list`."

       def serialize_input(self, data: InputT, path: Path) -> None:
           ...

       def deserialize_output(self, path: Path) -> OutputT:
           ...

       def deserialize_trace(self, path: Path) -> TraceT | None:
           ...

       def test_cases(self) -> Iterator[TestCase[InputT]]:
           yield TestCase("empty", ...)

       def benchmark_case(self, seed: int, size: int) -> BenchmarkCase[InputT]:
           ...

       def verify(self, input_data: InputT, output: OutputT) -> VerificationResult:
           ...

``baseline_case(seed)`` is optional. ``benchmark`` uses it to time the
executable on the smallest valid input and estimate startup cost. The default
returns ``benchmark_case(seed, size=0)``; override it if a size-0 input is not
valid for your problem.

Discovery
---------

Built-in problems live under ``src/algorithm_playground/problems/`` and are
imported by ``algorithm_playground.problems.__init__``. Adding a new
subpackage there is enough to wire it up: the import triggers the
``@register_problem`` decorator at module load time.

Visualization (optional)
------------------------

Override :meth:`~algorithm_playground.core.problem.Problem.visualize_io` and
:meth:`~algorithm_playground.core.problem.Problem.visualize_trace` to give
the ``debug`` command something to render. The
:mod:`algorithm_playground.visualization` module exposes a thin set of
helpers that wrap ``plotext`` (bar / line charts) and ``rich`` (interactive
stepper) so most problems do not need to touch those libraries directly.

``visualize_trace`` should honor ``auto_advance`` and ``delay_milliseconds``
so the CLI's ``--auto-advance`` / ``--delay-milliseconds`` flags drive
playback.

Worked example
--------------

The reference :class:`~algorithm_playground.problems.sorting.SortingProblem`
is a small, end-to-end example: see
``src/algorithm_playground/problems/sorting/problem.py`` and the binary
format documented at :doc:`problems/sorting`.
