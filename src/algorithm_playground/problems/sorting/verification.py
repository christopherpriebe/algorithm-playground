"""The sorting verifier: the output must be the input in ascending order."""

from __future__ import annotations

from algorithm_playground.core.problem import VerificationResult


def verify_sorted(input_values: list[int], output: list[int]) -> VerificationResult:
    """Check that ``output`` holds the values of ``input_values`` in ascending order.

    A failure names the index of the first difference in ``focus``, so that a
    report of a long array shows the place that matters.
    """
    expected = sorted(input_values)
    if len(output) != len(input_values):
        return VerificationResult(
            passed=False,
            message=f"Output length {len(output)} does not match input length {len(input_values)}",
            focus=_first_difference_index(expected, output),
            category="wrong length",
        )
    if output != expected:
        index = _first_difference_index(expected, output)
        return VerificationResult(
            passed=False,
            message=(
                f"Output is not sorted ascending; first mismatch at index {index}: "
                f"expected {expected[index]}, got {output[index]}"
            ),
            focus=index,
            category="not sorted",
        )
    return VerificationResult(passed=True)


def _first_difference_index(expected: list[int], actual: list[int]) -> int:
    for index, (expected_value, actual_value) in enumerate(zip(expected, actual, strict=False)):
        if expected_value != actual_value:
            return index
    return min(len(expected), len(actual))
