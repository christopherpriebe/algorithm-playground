"""Check that a problem satisfies the :class:`~algorithm_playground.core.problem.Problem` interface.

:func:`validate_problem` exercises a problem the way the harness will, without
running any implementation, and returns a list of findings (empty means
valid). It checks that:

* the problem has a name and a description, a non-negative integer
  ``minimum_size``, a ``debug_generator`` that names one of its generators (or
  ``None``), and ``operation_names`` that are unique text;
* fixtures exist, have non-empty unique names, are accepted by ``check_input``
  and serialize;
* generators exist, have unique names without colons or whitespace, return the
  same input for the same seed, accept the sizes from ``minimum_size`` up, and
  produce inputs that ``check_input`` accepts and that serialize;
* ``deserialize_input``, when a problem provides it, reads back the input that
  ``serialize_input`` wrote;
* ``expected_output``, when a problem provides it, passes ``verify`` and can
  be drawn by ``input_output_frame`` (for the first few inputs);
* ``shrink`` candidates that ``check_input`` accepts serialize and differ from
  their input, and the describe hooks return text.

A problem author calls :func:`assert_valid_problem` from a test::

    def test_my_problem_is_valid():
        assert_valid_problem(MyProblem())
"""

import random
import tempfile
from collections.abc import Callable
from functools import partial
from itertools import islice
from pathlib import Path
from typing import TypeVar

from algorithm_playground.core.cases import AnyFixture, AnyInputGenerator, Fixture, InputGenerator
from algorithm_playground.core.description import describe_error
from algorithm_playground.core.frames import Frame
from algorithm_playground.core.problem import AnyProblem, has_input_reader

__all__ = ["assert_valid_problem", "validate_problem"]

_SAMPLE_SIZE_OFFSETS = (0, 1, 2, 5, 20)
_MAXIMUM_SHRINK_CANDIDATES = 25
_MAXIMUM_FRAME_CHECKS = 3
_DESCRIPTION_LIMIT = 40

ResultT = TypeVar("ResultT")


def _is_valid_generator_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and ":" not in name
        and not any(character.isspace() for character in name)
    )


def validate_problem(problem: AnyProblem, *, seed: int = 0) -> list[str]:
    """Exercise a problem the way the harness will and report what is wrong with it.

    Generators are sampled at a few small sizes.

    Args:
        problem: The problem to check.
        seed: The seed for the generators.

    Returns:
        One message per problem found; an empty list means the problem is valid.
    """
    with tempfile.TemporaryDirectory(prefix="algorithm-playground-validation-") as directory:
        return _Validator(problem, seed, Path(directory) / "input.bin").run()


def assert_valid_problem(problem: AnyProblem, *, seed: int = 0) -> None:
    """Require a problem to be valid, as :func:`validate_problem` judges it.

    Args:
        problem: The problem to check.
        seed: The seed for the generators.

    Raises:
        AssertionError: If :func:`validate_problem` finds anything. The message
            lists every finding.
    """
    findings = validate_problem(problem, seed=seed)
    if findings:
        listing = "\n".join(f"  - {finding}" for finding in findings)
        raise AssertionError(f"Problem '{getattr(problem, 'name', '?')}' is not valid:\n{listing}")


class _Validator:
    """Collect the findings of one validation run."""

    def __init__(self, problem: AnyProblem, seed: int, scratch: Path) -> None:
        self._problem = problem
        self._seed = seed
        self._scratch = scratch
        self._findings: list[str] = []
        self._frames_checked = 0

    def run(self) -> list[str]:
        """Check the problem and return every finding."""
        problem = self._problem
        for attribute in ("name", "description"):
            value = getattr(type(problem), attribute, None)
            if not isinstance(value, str) or not value:
                self._record(f"the class attribute '{attribute}' must be a non-empty string")
        self._check_minimum_size()

        samples: list[tuple[str, object]] = [
            (f"fixture '{fixture.name}'", fixture.input_data) for fixture in self._fixtures()
        ]
        generators = self._generators()
        self._check_debug_generator(generators)
        self._check_operation_names()
        for generator in generators:
            samples.extend(self._generated_samples(generator))

        for subject, input_data in samples:
            self._check_valid(subject, input_data)
            if self._is_serializable(subject, input_data):
                self._check_deserialize_input(subject, input_data)
                self._check_expected_output(subject, input_data)
                self._check_shrink(subject, input_data)
        return self._findings

    def _minimum_size(self) -> int:
        value = getattr(type(self._problem), "minimum_size", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    def _check_minimum_size(self) -> None:
        value = getattr(type(self._problem), "minimum_size", 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            self._record(
                f"the class attribute 'minimum_size' must be an integer of at least 0, got {value!r}"
            )

    def _check_debug_generator(self, generators: list[AnyInputGenerator]) -> None:
        name = getattr(type(self._problem), "debug_generator", None)
        if name is not None and name not in {generator.name for generator in generators}:
            self._record(f"debug_generator {name!r} does not name one of the problem's generators")

    def _check_operation_names(self) -> None:
        names = getattr(type(self._problem), "operation_names", ())
        if (
            not isinstance(names, tuple)
            or not all(isinstance(name, str) and name for name in names)
            or len(set(names)) != len(names)
        ):
            self._record(
                "the class attribute 'operation_names' must be a tuple of unique non-empty text, "
                f"got {names!r}"
            )

    def _record(self, message: str) -> None:
        if message not in self._findings:
            self._findings.append(message)

    def _attempt(self, subject: str, action: Callable[[], ResultT]) -> tuple[bool, ResultT | None]:
        """Run ``action``; record ``subject`` with the error and report failure if it raises."""
        try:
            return True, action()
        except Exception as error:
            self._record(f"{subject}: {describe_error(error)}")
            return False, None

    def _is_serializable(self, subject: str, input_data: object) -> bool:
        succeeded, _ = self._attempt(
            f"{subject} does not serialize",
            lambda: self._problem.serialize_input(input_data, self._scratch),
        )
        return succeeded

    def _check_valid(self, subject: str, input_data: object) -> None:
        reason = self._rejection(f"check_input() raised for {subject}", input_data)
        if reason is not None:
            self._record(f"check_input() rejects {subject}: {reason}")

    def _rejection(self, subject: str, input_data: object) -> str | None:
        """Return why ``check_input`` rejects ``input_data``, or ``None`` if it accepts it."""
        succeeded, reason = self._attempt(subject, lambda: self._problem.check_input(input_data))
        if succeeded and reason is not None and not isinstance(reason, str):
            self._record(f"check_input() must return text or None, got {type(reason).__name__}")
            return None
        return reason if succeeded else None

    def _check_deserialize_input(self, subject: str, input_data: object) -> None:
        if not has_input_reader(self._problem):
            return
        succeeded, read_back = self._attempt(
            f"deserialize_input() raised for {subject}",
            lambda: self._problem.deserialize_input(self._scratch),
        )
        if succeeded and read_back != input_data:
            self._record(
                f"deserialize_input() does not return the input that serialize_input wrote "
                f"for {subject}"
            )

    def _fixtures(self) -> list[AnyFixture]:
        succeeded, listed = self._attempt(
            "fixtures() raised", lambda: list(self._problem.fixtures())
        )
        if not succeeded or listed is None:
            return []
        if not listed:
            self._record("fixtures() returned no fixtures; provide at least one hand-written case")
        fixtures: list[AnyFixture] = []
        names: set[str] = set()
        for fixture in listed:
            if not isinstance(fixture, Fixture):
                self._record(f"fixtures() must yield Fixture objects, got {type(fixture).__name__}")
            elif not isinstance(fixture.name, str) or not fixture.name:
                self._record("a fixture has an empty name")
            elif fixture.name in names:
                self._record(f"the fixture name '{fixture.name}' is used more than once")
            else:
                names.add(fixture.name)
                fixtures.append(fixture)
        return fixtures

    def _generators(self) -> list[AnyInputGenerator]:
        succeeded, listed = self._attempt(
            "generators() raised", lambda: list(self._problem.generators())
        )
        if not succeeded or listed is None:
            return []
        if not listed:
            self._record("generators() returned no generators; provide at least one (the default)")
        generators: list[AnyInputGenerator] = []
        names: set[str] = set()
        for generator in listed:
            if not isinstance(generator, InputGenerator):
                self._record(
                    f"generators() must hold InputGenerator objects, got {type(generator).__name__}"
                )
            elif not _is_valid_generator_name(generator.name):
                self._record(
                    f"the generator name {generator.name!r} must be non-empty and contain "
                    "no colon or whitespace"
                )
            elif generator.name in names:
                self._record(f"the generator name '{generator.name}' is used more than once")
            else:
                names.add(generator.name)
                generators.append(generator)
        return generators

    def _generated_samples(self, generator: AnyInputGenerator) -> list[tuple[str, object]]:
        samples: list[tuple[str, object]] = []
        for offset in _SAMPLE_SIZE_OFFSETS:
            size = self._minimum_size() + offset
            subject = f"generator '{generator.name}' at size {size}"

            generate = partial(self._generate_sample, generator, size)
            succeeded, first = self._attempt(f"{subject} raised", generate)
            if not succeeded:
                continue
            succeeded, second = self._attempt(f"{subject} raised", generate)
            if succeeded and first != second:
                self._record(f"{subject} returned different inputs for the same seed")
            samples.append((subject, first))
        return samples

    def _generate_sample(self, generator: AnyInputGenerator, size: int) -> object:
        return generator.generate(random.Random(self._seed), size)

    def _check_expected_output(self, subject: str, input_data: object) -> None:
        problem = self._problem
        succeeded, expected = self._attempt(
            f"expected_output() raised for {subject}", lambda: problem.expected_output(input_data)
        )
        if not succeeded:
            return
        descriptions = [
            ("describe_input", lambda: problem.describe_input(input_data, limit=_DESCRIPTION_LIMIT))
        ]
        if expected is not None:
            descriptions.append(
                (
                    "describe_output",
                    lambda: problem.describe_output(expected, limit=_DESCRIPTION_LIMIT),
                )
            )
            succeeded, verification = self._attempt(
                f"verify() raised on the expected output of {subject}",
                lambda: problem.verify(input_data, expected),
            )
            if succeeded and verification is not None and not verification.passed:
                self._record(
                    f"verify() rejects expected_output() for {subject}: "
                    f"{verification.message or '(no message)'}"
                )
            self._check_input_output_frame(subject, input_data, expected)
        for hook, describe in descriptions:
            succeeded, text = self._attempt(f"{hook}() raised for {subject}", describe)
            if succeeded and not isinstance(text, str):
                self._record(f"{hook}() must return text, got {type(text).__name__}")

    def _check_input_output_frame(self, subject: str, input_data: object, expected: object) -> None:
        """Draw the first few inputs; drawing is slow and says little more beyond that."""
        if self._frames_checked >= _MAXIMUM_FRAME_CHECKS:
            return
        self._frames_checked += 1
        succeeded, frame = self._attempt(
            f"input_output_frame() raised for {subject}",
            lambda: self._problem.input_output_frame(input_data, expected),
        )
        if succeeded and frame is not None and not isinstance(frame, Frame):
            self._record(
                f"input_output_frame() must return a Frame or None, got {type(frame).__name__}"
            )

    def _check_shrink(self, subject: str, input_data: object) -> None:
        succeeded, candidates = self._attempt(
            f"shrink() raised for {subject}",
            lambda: list(islice(self._problem.shrink(input_data), _MAXIMUM_SHRINK_CANDIDATES)),
        )
        if not succeeded or candidates is None:
            return
        for candidate in candidates:
            if candidate == input_data:
                self._record(
                    f"shrink() yields a candidate equal to its input for {subject}; "
                    "candidates must differ from the input"
                )
            elif self._rejection(
                f"check_input() raised for a shrink candidate of {subject}", candidate
            ):
                continue
            elif not self._is_serializable(f"a shrink candidate of {subject}", candidate):
                break
