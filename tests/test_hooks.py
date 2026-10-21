"""Tests for calling the hooks of a problem."""

from __future__ import annotations

import pytest

from algorithm_playground.core.hooks import HookError, call_hook


class TestCallHook:
    def test_it_returns_what_the_call_returns(self) -> None:
        assert call_hook("fixtures", lambda: [1, 2]) == [1, 2]

    def test_an_exception_becomes_an_error_that_names_the_hook_and_the_failure(self) -> None:
        def explode() -> None:
            raise ValueError("out of fixtures")

        with pytest.raises(HookError) as raised:
            call_hook("fixtures", explode)
        assert (
            str(raised.value) == "The problem's fixtures hook raised ValueError: out of fixtures."
        )
        assert raised.value.hook == "fixtures"
        assert isinstance(raised.value.__cause__, ValueError)

    def test_an_error_that_already_names_a_hook_is_not_wrapped_again(self) -> None:
        def inner() -> None:
            raise HookError("generators", RuntimeError("inner"))

        with pytest.raises(HookError) as raised:
            call_hook("fixtures", inner)
        assert raised.value.hook == "generators"

    def test_an_interrupt_is_not_swallowed(self) -> None:
        def interrupt() -> None:
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            call_hook("fixtures", interrupt)
