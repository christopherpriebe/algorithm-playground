"""Tests for the subprocess Runner.

We drive a real Python sorting executable rather than a mocked subprocess so
that the input/output/trace round-trip is exercised end-to-end. Specialized
failure-mode fixtures are written into the test's tmp_path on demand.
"""

from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path

import pytest

from algorithm_playground.core.runner import Runner, RunnerError
from algorithm_playground.problems.sorting import SortingProblem, SortingTrace


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestSuccessfulRun:
    def test_runner_returns_sorted_output(self, python_sort_executable: Path) -> None:
        runner = Runner(SortingProblem(), python_sort_executable)
        result = runner.run([3, 1, 2], collect_trace=False)
        assert result.output == [1, 2, 3]
        assert result.trace is None
        assert result.returncode == 0
        assert result.wall_seconds > 0.0

    def test_runner_returns_trace_when_requested(self, python_sort_executable: Path) -> None:
        runner = Runner(SortingProblem(), python_sort_executable)
        result = runner.run([4, 2, 3, 1], collect_trace=True)
        assert result.output == [1, 2, 3, 4]
        assert isinstance(result.trace, SortingTrace)
        assert result.trace.snapshots == ((4, 2, 3, 1), (1, 2, 3, 4))


class TestFailureModes:
    def test_missing_executable_raises_runner_error(self, tmp_path: Path) -> None:
        runner = Runner(SortingProblem(), tmp_path / "does-not-exist")
        with pytest.raises(RunnerError, match="not found"):
            runner.run([1, 2, 3])

    def test_non_zero_exit_raises_runner_error(self, tmp_path: Path) -> None:
        executable = _write_executable(
            tmp_path / "fail.py",
            """\
            #!/usr/bin/env python3
            import sys
            print("kaboom", file=sys.stderr)
            sys.exit(7)
            """,
        )
        runner = Runner(SortingProblem(), executable)
        with pytest.raises(RunnerError, match="exited with code 7"):
            runner.run([1, 2, 3])

    def test_missing_output_file_raises_runner_error(self, tmp_path: Path) -> None:
        executable = _write_executable(
            tmp_path / "no_output.py",
            """\
            #!/usr/bin/env python3
            import sys
            sys.exit(0)
            """,
        )
        runner = Runner(SortingProblem(), executable)
        with pytest.raises(RunnerError, match="did not produce an output file"):
            runner.run([1, 2, 3])

    def test_malformed_output_raises_runner_error(self, truncated_output_executable: Path) -> None:
        runner = Runner(SortingProblem(), truncated_output_executable)
        with pytest.raises(RunnerError, match="malformed output file"):
            runner.run([3, 1, 2])

    def test_malformed_trace_is_reported_not_raised(self, malformed_trace_executable: Path) -> None:
        runner = Runner(SortingProblem(), malformed_trace_executable)
        result = runner.run([3, 1, 2], collect_trace=True)
        assert result.output == [1, 2, 3]
        assert result.trace is None
        assert result.trace_error is not None
        assert "end of stream" in result.trace_error

    def test_timeout_raises_runner_error(self, tmp_path: Path) -> None:
        executable = _write_executable(
            tmp_path / "slow.py",
            """\
            #!/usr/bin/env python3
            import time
            time.sleep(5)
            """,
        )
        runner = Runner(SortingProblem(), executable, timeout_seconds=0.5)
        with pytest.raises(RunnerError, match="timed out"):
            runner.run([1, 2, 3])


class TestEnvironmentScrubbing:
    def test_minimal_env_does_not_include_random_host_variables(self, tmp_path: Path) -> None:
        executable = _write_executable(
            tmp_path / "echo_env.py",
            """\
            #!/usr/bin/env python3
            import os, struct, sys
            with open(sys.argv[1], "rb") as stream:
                raw = stream.read()
            count = struct.unpack_from("<Q", raw, 0)[0]
            with open(sys.argv[2], "wb") as stream:
                stream.write(raw)
            print(",".join(sorted(os.environ)), file=sys.stderr)
            """,
        )
        os.environ["ALGORITHM_PLAYGROUND_TEST_SECRET"] = "must-not-leak"
        try:
            runner = Runner(SortingProblem(), executable)
            result = runner.run([1, 2, 3])
        finally:
            os.environ.pop("ALGORITHM_PLAYGROUND_TEST_SECRET", None)
        forwarded_keys = set(result.stderr.strip().split(","))
        assert "ALGORITHM_PLAYGROUND_TEST_SECRET" not in forwarded_keys
        assert "PATH" in forwarded_keys
