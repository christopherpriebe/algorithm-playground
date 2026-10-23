``algorithm_playground.core``
=============================

.. automodule:: algorithm_playground.core
   :no-members:

The ``core`` package holds the framework: the
:class:`~algorithm_playground.core.Problem` ABC with its cases and
validation, the registry, the subprocess
:class:`~algorithm_playground.core.Runner`, the
:class:`~algorithm_playground.core.Implementation` command wrapper
and its TOML configuration, the test and benchmark engines, and the small binary
format and statistics helpers. A problem author does not import from here;
:doc:`authoring` re-exports what a problem needs.

Public API
----------

``algorithm_playground.authoring`` is the stable surface for writing a problem.
``algorithm_playground.core`` and ``algorithm_playground.visualization`` are
public as well, for code that drives the engines or draws charts, and the package
ships a ``py.typed`` marker so type checkers use its annotations.
``algorithm_playground.cli`` is the command-line front end and is not a public
API; neither are modules and names that start with an underscore.

Errors
------

.. autoexception:: algorithm_playground.core.AlgorithmPlaygroundError

Problem ABC
-----------

.. autoclass:: algorithm_playground.core.VerificationResult
.. autoclass:: algorithm_playground.core.Problem
.. autofunction:: algorithm_playground.core.has_trace_format
.. autofunction:: algorithm_playground.core.has_input_reader

Dimensions and sizes
--------------------

.. autoclass:: algorithm_playground.core.Dimension
.. autoclass:: algorithm_playground.core.Size
.. autofunction:: algorithm_playground.core.parse_size
.. autofunction:: algorithm_playground.core.build_minimum_size
.. autofunction:: algorithm_playground.core.build_default_maximum_size
.. autofunction:: algorithm_playground.core.get_growth_dimension

Cases
-----

.. autoexception:: algorithm_playground.core.CaseError
.. autoclass:: algorithm_playground.core.Fixture
.. autoclass:: algorithm_playground.core.InputGenerator
.. autoclass:: algorithm_playground.core.FixtureOrigin
.. autoclass:: algorithm_playground.core.GeneratedOrigin
.. autoclass:: algorithm_playground.core.ShrunkOrigin
.. autoclass:: algorithm_playground.core.Case
.. autoclass:: algorithm_playground.core.CasePlan
.. autofunction:: algorithm_playground.core.get_default_generator
.. autofunction:: algorithm_playground.core.build_startup_case
.. autofunction:: algorithm_playground.core.check_sizes
.. autofunction:: algorithm_playground.core.generate_case
.. autofunction:: algorithm_playground.core.build_cases
.. autofunction:: algorithm_playground.core.parse_case_identifier
.. autofunction:: algorithm_playground.core.resolve_case
.. autofunction:: algorithm_playground.core.select_generators
.. autofunction:: algorithm_playground.core.collect_problem_fixtures
.. autofunction:: algorithm_playground.core.collect_problem_generators

Hooks
-----

.. autoexception:: algorithm_playground.core.HookError
.. autofunction:: algorithm_playground.core.call_hook

Frames
------

.. autoclass:: algorithm_playground.core.Frame
.. autoclass:: algorithm_playground.core.FrameSequence

Describing
----------

.. autofunction:: algorithm_playground.core.describe_error
.. autofunction:: algorithm_playground.core.truncate_text
.. autofunction:: algorithm_playground.core.describe_sequence

Shrinking
---------

.. autofunction:: algorithm_playground.core.shrink_sequence
.. autofunction:: algorithm_playground.core.shrink_integer
.. autofunction:: algorithm_playground.core.shrink_each
.. autofunction:: algorithm_playground.core.shrink_integers
.. autofunction:: algorithm_playground.core.shrink_integer_sequence
.. autofunction:: algorithm_playground.core.shrink_fields
.. autofunction:: algorithm_playground.core.deduplicate_candidates

Replaying
---------

.. autoclass:: algorithm_playground.core.StateTimeline

Validation
----------

.. autofunction:: algorithm_playground.core.validate_problem
.. autofunction:: algorithm_playground.core.assert_valid_problem

Registry
--------

.. autoexception:: algorithm_playground.core.ProblemRegistrationError
.. autoexception:: algorithm_playground.core.UnknownProblemError
.. autoexception:: algorithm_playground.core.ProblemLoadError
.. autoclass:: algorithm_playground.core.ProblemSourceKind
.. autoclass:: algorithm_playground.core.ProblemSource
.. autoclass:: algorithm_playground.core.RegistrySnapshot
.. autofunction:: algorithm_playground.core.register_problem
.. autofunction:: algorithm_playground.core.get_problem
.. autofunction:: algorithm_playground.core.list_problems
.. autofunction:: algorithm_playground.core.list_problem_descriptions
.. autofunction:: algorithm_playground.core.list_problem_sources
.. autofunction:: algorithm_playground.core.snapshot_registry
.. autofunction:: algorithm_playground.core.restore_registry
.. autofunction:: algorithm_playground.core.load_problem_modules
.. autofunction:: algorithm_playground.core.load_entry_point_problems

Implementation
--------------

.. autoclass:: algorithm_playground.core.Implementation

Configuration
-------------

.. autoexception:: algorithm_playground.core.ConfigurationError
.. autoclass:: algorithm_playground.core.ConfiguredImplementation
.. autoclass:: algorithm_playground.core.Configuration
.. autofunction:: algorithm_playground.core.find_configuration
.. autofunction:: algorithm_playground.core.load_configuration
.. autofunction:: algorithm_playground.core.load_configured_problems
.. autofunction:: algorithm_playground.core.check_configured_problems

Runner
------

.. autoclass:: algorithm_playground.core.TemporaryFilePolicy
.. autoexception:: algorithm_playground.core.RunnerError
.. autoexception:: algorithm_playground.core.BuildError
.. autoclass:: algorithm_playground.core.RunResult
.. autoclass:: algorithm_playground.core.RunnerLike
.. autoclass:: algorithm_playground.core.Runner
.. autofunction:: algorithm_playground.core.build_subprocess_runner_factory
.. autofunction:: algorithm_playground.core.build_implementation
.. autofunction:: algorithm_playground.core.check_can_start
.. autofunction:: algorithm_playground.core.build_implementations

Single run
----------

.. autodata:: algorithm_playground.core.PROBLEM_HOOK_CATEGORIES
.. autoclass:: algorithm_playground.core.CaseStatus
.. autoclass:: algorithm_playground.core.SingleRun
.. autofunction:: algorithm_playground.core.run_single
.. autofunction:: algorithm_playground.core.run_single_with_trace

Test engine
-----------

.. autoclass:: algorithm_playground.core.CasePhase
.. autoclass:: algorithm_playground.core.FailureDetail
.. autoclass:: algorithm_playground.core.ShrunkFailure
.. autoclass:: algorithm_playground.core.CaseOutcome
.. autoclass:: algorithm_playground.core.CaseProgress
.. autoclass:: algorithm_playground.core.ShrinkOptions
.. autoclass:: algorithm_playground.core.TestRunOptions
.. autoclass:: algorithm_playground.core.TestSettings
.. autoclass:: algorithm_playground.core.TestReport
.. autofunction:: algorithm_playground.core.describe_failure
.. autofunction:: algorithm_playground.core.run_tests

Saved inputs
------------

.. autoclass:: algorithm_playground.core.SavedInputs
.. autofunction:: algorithm_playground.core.make_safe_file_name
.. autofunction:: algorithm_playground.core.save_failing_inputs

Benchmark engine
----------------

.. autoclass:: algorithm_playground.core.BenchmarkSettings
.. autoclass:: algorithm_playground.core.BenchmarkPhase
.. autoclass:: algorithm_playground.core.BenchmarkProgress
.. autoclass:: algorithm_playground.core.OperationIssueKind
.. autoclass:: algorithm_playground.core.OperationIssue
.. autoclass:: algorithm_playground.core.SizeMeasurement
.. autoclass:: algorithm_playground.core.FailureStage
.. autoclass:: algorithm_playground.core.BenchmarkFailure
.. autoclass:: algorithm_playground.core.CellStatus
.. autoclass:: algorithm_playground.core.ImplementationBenchmark
.. autoclass:: algorithm_playground.core.BenchmarkReport
.. autofunction:: algorithm_playground.core.include_failed_implementations
.. autofunction:: algorithm_playground.core.count_total_runs
.. autofunction:: algorithm_playground.core.run_benchmark

Report
------

.. autofunction:: algorithm_playground.core.convert_benchmark_report_to_json
.. autofunction:: algorithm_playground.core.convert_correctness_report_to_json

Binary format
-------------

.. autoexception:: algorithm_playground.core.BinaryFormatError
.. autofunction:: algorithm_playground.core.write_u8
.. autofunction:: algorithm_playground.core.write_u32
.. autofunction:: algorithm_playground.core.write_u64
.. autofunction:: algorithm_playground.core.write_i32
.. autofunction:: algorithm_playground.core.write_i64
.. autofunction:: algorithm_playground.core.write_f64
.. autofunction:: algorithm_playground.core.read_u8
.. autofunction:: algorithm_playground.core.read_u32
.. autofunction:: algorithm_playground.core.read_u64
.. autofunction:: algorithm_playground.core.read_i32
.. autofunction:: algorithm_playground.core.read_i64
.. autofunction:: algorithm_playground.core.read_f64
.. autofunction:: algorithm_playground.core.write_i32_array
.. autofunction:: algorithm_playground.core.write_u32_array
.. autofunction:: algorithm_playground.core.write_i64_array
.. autofunction:: algorithm_playground.core.write_f64_array
.. autofunction:: algorithm_playground.core.read_i32_array
.. autofunction:: algorithm_playground.core.read_u32_array
.. autofunction:: algorithm_playground.core.read_i64_array
.. autofunction:: algorithm_playground.core.read_f64_array
.. autofunction:: algorithm_playground.core.expect_end_of_stream
.. autofunction:: algorithm_playground.core.read_record_bytes
.. autofunction:: algorithm_playground.core.read_records
.. autofunction:: algorithm_playground.core.read_sections

Statistics
----------

.. autoclass:: algorithm_playground.core.TimingSummary
.. autoclass:: algorithm_playground.core.Growth
.. autofunction:: algorithm_playground.core.summarize
.. autofunction:: algorithm_playground.core.subtract_startup
.. autofunction:: algorithm_playground.core.estimate_growth_exponent
.. autofunction:: algorithm_playground.core.estimate_growth
.. autofunction:: algorithm_playground.core.fit_growth_class
.. autofunction:: algorithm_playground.core.format_duration
