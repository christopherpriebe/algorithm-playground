"""The sorting verifier: the output must be the input in ascending order."""

from algorithm_playground.core._problem import VerificationResult

__all__ = ["verify_sorted"]


def _find_first_difference(expected: list[int], actual: list[int]) -> int:
    """Return the first index where the lists differ, or the shorter length if one is a prefix."""
    # The lists may differ in length; the shorter one ends the comparison.
    for index, (expected_value, actual_value) in enumerate(
        zip(expected, actual, strict=False)
    ):
        if expected_value != actual_value:
            return index
    return min(len(expected), len(actual))


def verify_sorted(input_values: list[int], output: list[int]) -> VerificationResult:
    """Check that the output holds the values of the input in ascending order.

    A failure names the index of the first difference in ``focus``, so that a
    report of a long array shows the place that matters.

    Args:
        input_values: The array that was sorted.
        output: The array the executable produced.

    Returns:
        A passing result, or a failure with the message, focus and category
        ``"wrong length"`` or ``"not sorted"``.
    """
    expected = sorted(input_values)
    if len(output) != len(input_values):
        return VerificationResult(
            passed=False,
            message=f"Output length {len(output)} does not match input length {len(input_values)}",
            focus=_find_first_difference(expected, output),
            category="wrong length",
        )
    if output != expected:
        index = _find_first_difference(expected, output)
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
