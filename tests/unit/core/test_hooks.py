"""Tests for calling the hooks of a problem."""

import pytest

from algorithm_playground.core.hooks import HookError, call_hook


class TestCallHook:
    def test_it_returns_what_the_call_returns(self) -> None:
        """Test the value the hook returns is passed on."""
        assert call_hook("fixtures", lambda: [1, 2]) == [1, 2]

    def test_an_exception_becomes_an_error_that_names_the_hook_and_the_failure(self) -> None:
        """Test an exception from a hook is reported as an error naming the hook and the cause."""

        def explode() -> None:
            raise ValueError("out of fixtures")

        with pytest.raises(
            HookError, match=r"^The problem's fixtures hook raised ValueError: out of fixtures\.$"
        ) as raised:
            call_hook("fixtures", explode)

        assert raised.value.hook == "fixtures"
        assert isinstance(raised.value.__cause__, ValueError)

    def test_an_error_that_already_names_a_hook_is_not_wrapped_again(self) -> None:
        """Test an error that already names a hook keeps the name of that hook."""

        def inner() -> None:
            raise HookError("generators", RuntimeError("inner"))

        with pytest.raises(HookError, match="generators hook raised RuntimeError: inner") as raised:
            call_hook("fixtures", inner)

        assert raised.value.hook == "generators"

    def test_an_interrupt_is_not_swallowed(self) -> None:
        """Test a keyboard interrupt from a hook propagates unchanged."""

        def interrupt() -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            call_hook("fixtures", interrupt)
