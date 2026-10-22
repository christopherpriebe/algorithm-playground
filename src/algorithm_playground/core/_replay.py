"""Replaying events to recover the state after each of them.

Many traces are a list of events that change a state: swaps in an array, edges
added to a graph, cells of a table filled in. To show the state after any event
without storing a copy per event, :class:`StateTimeline` keeps a checkpoint
every so many events and replays only the short stretch after the nearest one.
A problem supplies the starting state, the events, and ``apply``, which says
what a run of events does to a state.
"""

from collections.abc import Callable, Sequence
from typing import Generic, TypeVar

__all__ = ["DEFAULT_CHECKPOINT_INTERVAL", "StateTimeline"]

StateT = TypeVar("StateT")
EventT = TypeVar("EventT")

DEFAULT_CHECKPOINT_INTERVAL = 256


class StateTimeline(Generic[StateT, EventT]):
    """The state after any number of events, recovered from stored checkpoints.

    A checkpoint is stored every ``checkpoint_interval`` events, so memory is
    proportional to the number of events divided by the interval, and a lookup
    replays fewer than ``checkpoint_interval`` events. Choose an interval about
    the size of the state to balance the two.

    Args:
        start_state: The state before the first event.
        events: The events, in order.
        apply: Returns the state after a sequence of events (a slice of
            ``events``) has happened to a state. It must not modify the state
            it receives, because that may be a checkpoint; an immutable state
            such as a tuple makes that easy.
        checkpoint_interval: The number of events between two checkpoints.

    Attributes:
        final_state: The state after every event.

    Raises:
        ValueError: If ``checkpoint_interval`` is below 1.
    """

    def __init__(
        self,
        start_state: StateT,
        events: Sequence[EventT],
        apply: Callable[[StateT, Sequence[EventT]], StateT],
        *,
        checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
    ) -> None:
        if checkpoint_interval < 1:
            message = (
                f"The checkpoint interval must be at least 1, got {checkpoint_interval}"
            )
            raise ValueError(message)
        self._events = events
        self._apply = apply
        self._interval = checkpoint_interval
        state = start_state
        self._checkpoints = [state]
        position = 0
        while position + checkpoint_interval <= len(events):
            state = apply(state, events[position : position + checkpoint_interval])
            position += checkpoint_interval
            self._checkpoints.append(state)
        self.final_state = (
            apply(state, events[position:]) if position < len(events) else state
        )

    def state_after(self, event_count: int) -> StateT:
        """Return the state after the first ``event_count`` events.

        Args:
            event_count: The number of events that have happened, from ``0``
                to the number of events.

        Returns:
            The state, recovered from the nearest checkpoint.

        Raises:
            IndexError: If ``event_count`` is negative or exceeds the number of
                events.
        """
        if not 0 <= event_count <= len(self._events):
            message = (
                f"{event_count} events were not recorded: {len(self._events)} were"
            )
            raise IndexError(message)
        base = event_count // self._interval
        replayed = self._events[base * self._interval : event_count]
        state = self._checkpoints[base]
        return self._apply(state, replayed) if len(replayed) else state
