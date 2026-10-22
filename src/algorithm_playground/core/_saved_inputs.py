"""Saving the inputs that made implementations fail, so that a failure can be rerun.

:func:`save_failing_inputs` writes the input of every failing case of a test
report, and the shrunk input when there is one, in the problem's own binary
input format, so that the file is also a valid first argument for the
implementation under test. The layout is::

    DIRECTORY/<implementation>/<case identifier>/input.bin
    DIRECTORY/<implementation>/<case identifier>/shrunk-input.bin

Names are made safe for any file system by replacing every character other
than letters, digits and ``._=+-`` with an underscore (see
:func:`make_safe_file_name`), and a name that was changed in any way ends in a short
digest of the original, so that two different names never share a directory.
``debug --input-file`` runs a saved file (for a problem that implements
``deserialize_input``).
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from algorithm_playground.core._description import describe_error
from algorithm_playground.core._problem import AnyProblem
from algorithm_playground.core._single_run import CaseStatus
from algorithm_playground.core._testing import TestReport

__all__ = [
    "INPUT_FILE_NAME",
    "MAXIMUM_NAME_LENGTH",
    "SHRUNK_INPUT_FILE_NAME",
    "SavedInputs",
    "make_safe_file_name",
    "save_failing_inputs",
]

INPUT_FILE_NAME = "input.bin"
SHRUNK_INPUT_FILE_NAME = "shrunk-input.bin"
MAXIMUM_NAME_LENGTH = 80
_UNSAFE_CHARACTERS = re.compile(r"[^A-Za-z0-9._=+-]")


def _try_write_input(problem: AnyProblem, input_data: object, path: Path) -> str | None:
    """Write ``input_data`` to ``path`` in the input format of ``problem``.

    Returns:
        ``None`` on success, else the text of the error to report.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        problem.serialize_input(input_data, path)
    except Exception as error:  # noqa: BLE001  serialize_input is problem code
        return f"Could not save {path}: {describe_error(error)}"
    return None


@dataclass(frozen=True, slots=True)
class SavedInputs:
    """Where the failing inputs of a test report were saved.

    ``errors`` describes each input that could not be written; the others were
    saved regardless.
    """

    inputs: dict[tuple[str, str], Path] = field(default_factory=dict)
    shrunk_inputs: dict[tuple[str, str], Path] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def input_path(self, implementation_name: str, case_identifier: str) -> Path | None:
        """Look up the file with the input of a failing case.

        Args:
            implementation_name: The implementation that failed the case.
            case_identifier: The identifier of the failing case.

        Returns:
            The file, or ``None`` if there is none.
        """
        return self.inputs.get((implementation_name, case_identifier))

    def shrunk_input_path(
        self, implementation_name: str, case_identifier: str
    ) -> Path | None:
        """Look up the file with the shrunk input of a failing case.

        Args:
            implementation_name: The implementation that failed the case.
            case_identifier: The identifier of the failing case.

        Returns:
            The file, or ``None`` if there is none.
        """
        return self.shrunk_inputs.get((implementation_name, case_identifier))


def make_safe_file_name(text: str) -> str:
    """Turn ``text`` into a name that is valid on any file system and keeps it readable.

    A name that differs from ``text`` (a character was replaced), that has an
    upper-case letter (it could collide with another name on a file system that
    ignores case), or that is longer than 80 characters is cut to fit and ends
    in a short digest of the whole text, so that two different texts stay
    different. A name that needs none is returned as it is.

    Args:
        text: The text to turn into a file name.

    Returns:
        The file name.
    """
    name = _UNSAFE_CHARACTERS.sub("_", text) or "_"
    if name.startswith("."):
        name = "_" + name[1:]
    if name != text or name != name.lower() or len(name) > MAXIMUM_NAME_LENGTH:
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        name = f"{name[: MAXIMUM_NAME_LENGTH - len(digest) - 1]}-{digest}"
    return name


def save_failing_inputs(
    problem: AnyProblem, report: TestReport, directory: Path
) -> SavedInputs:
    """Write the input of every failing case of ``report`` below ``directory``.

    Each failing outcome gets ``input.bin`` and, when shrinking found a smaller
    input, ``shrunk-input.bin`` next to it.

    Args:
        problem: The problem whose input format the files use.
        report: The test report with the failing outcomes.
        directory: The directory to write below.

    Returns:
        The paths of the written files. A problem whose ``serialize_input``
        raises, or a file that cannot be written, is recorded in
        the ``errors`` of the result.
    """
    inputs: dict[tuple[str, str], Path] = {}
    shrunk_inputs: dict[tuple[str, str], Path] = {}
    errors: list[str] = []
    for outcome in report.outcomes:
        if outcome.status is CaseStatus.PASSED:
            continue
        key = (outcome.implementation_name, outcome.case_identifier)
        case_directory = (
            directory
            / make_safe_file_name(outcome.implementation_name)
            / make_safe_file_name(outcome.case_identifier)
        )
        targets = [(outcome.case.input_data, case_directory / INPUT_FILE_NAME, inputs)]
        if outcome.shrunk is not None:
            shrunk_path = case_directory / SHRUNK_INPUT_FILE_NAME
            targets.append((outcome.shrunk.case.input_data, shrunk_path, shrunk_inputs))
        for input_data, path, saved_paths in targets:
            error = _try_write_input(problem, input_data, path)
            if error is None:
                saved_paths[key] = path
            else:
                errors.append(error)
    return SavedInputs(inputs, shrunk_inputs, tuple(errors))
