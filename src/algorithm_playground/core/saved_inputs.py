"""Saving the inputs that made implementations fail, so that a failure can be rerun.

:func:`save_failing_inputs` writes the input of every failing case of a test
report, and the shrunk input when there is one, in the problem's own binary
input format, so that the file is also a valid first argument for the
implementation under test. The layout is::

    DIRECTORY/<implementation>/<case identifier>/input.bin
    DIRECTORY/<implementation>/<case identifier>/shrunk-input.bin

Names are made safe for any file system by replacing every character other
than letters, digits and ``._=+-`` with an underscore (see
:func:`safe_file_name`), and a name that was changed in any way ends in a short
digest of the original, so that two different names never share a directory.
``debug --input-file`` runs a saved file (for a problem that implements
``deserialize_input``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from algorithm_playground.core._support import describe_error
from algorithm_playground.core.problem import Problem
from algorithm_playground.core.single_run import CaseStatus
from algorithm_playground.core.testing import TestReport

INPUT_FILE_NAME = "input.bin"
SHRUNK_INPUT_FILE_NAME = "shrunk-input.bin"
MAXIMUM_NAME_LENGTH = 80
_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9._=+-]")


@dataclass(frozen=True)
class SavedInputs:
    """Where the failing inputs of a test report were saved.

    ``errors`` describes each input that could not be written; the others were
    saved regardless.
    """

    inputs: dict[tuple[str, str], Path] = field(default_factory=dict)
    shrunk_inputs: dict[tuple[str, str], Path] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def input_path(self, implementation_name: str, case_identifier: str) -> Path | None:
        """Return the file with the input of a failing case, or ``None`` if there is none."""
        return self.inputs.get((implementation_name, case_identifier))

    def shrunk_input_path(self, implementation_name: str, case_identifier: str) -> Path | None:
        """Return the file with the shrunk input of a failing case, or ``None`` if there is none."""
        return self.shrunk_inputs.get((implementation_name, case_identifier))


def safe_file_name(text: str) -> str:
    """Turn ``text`` into a name that is valid on any file system and keeps it readable.

    A name that differs from ``text`` (a character was replaced), that has an
    upper-case letter (it could collide with another name on a file system that
    ignores case), or that is longer than 80 characters is cut to fit and ends
    in a short digest of the whole text, so that two different texts stay
    different. A name that needs none is returned as it is.
    """
    name = _UNSAFE_CHARACTERS.sub("_", text) or "_"
    if name.startswith("."):
        name = "_" + name[1:]
    if name != text or name != name.lower() or len(name) > MAXIMUM_NAME_LENGTH:
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        name = f"{name[: MAXIMUM_NAME_LENGTH - len(digest) - 1]}-{digest}"
    return name


def save_failing_inputs(
    problem: Problem[Any, Any, Any], report: TestReport, directory: Path
) -> SavedInputs:
    """Write the input of every failing case of ``report`` below ``directory``.

    Each failing outcome gets ``input.bin`` and, when shrinking found a smaller
    input, ``shrunk-input.bin`` next to it. A problem whose ``serialize_input``
    raises, or a file that cannot be written, is recorded in
    :attr:`SavedInputs.errors`.
    """
    inputs: dict[tuple[str, str], Path] = {}
    shrunk_inputs: dict[tuple[str, str], Path] = {}
    errors: list[str] = []

    def save(input_data: Any, path: Path) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            problem.serialize_input(input_data, path)
        except Exception as error:
            errors.append(f"Could not save {path}: {describe_error(error)}")
            return False
        return True

    for outcome in report.outcomes:
        if outcome.status is CaseStatus.PASSED:
            continue
        key = (outcome.implementation_name, outcome.case_identifier)
        case_directory = (
            directory
            / safe_file_name(outcome.implementation_name)
            / safe_file_name(outcome.case_identifier)
        )
        if save(outcome.case.input_data, case_directory / INPUT_FILE_NAME):
            inputs[key] = case_directory / INPUT_FILE_NAME
        if outcome.shrunk is not None and save(
            outcome.shrunk.case.input_data, case_directory / SHRUNK_INPUT_FILE_NAME
        ):
            shrunk_inputs[key] = case_directory / SHRUNK_INPUT_FILE_NAME
    return SavedInputs(inputs, shrunk_inputs, tuple(errors))
