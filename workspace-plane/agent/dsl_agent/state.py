"""Agent state machine and event emitter."""

import time
from enum import Enum
from typing import Callable, Optional
from datetime import datetime, timezone


class AgentState(str, Enum):
    IDLE = "IDLE"
    REQUESTING = "REQUESTING"
    ACTIVE = "ACTIVE"
    RENEWING = "RENEWING"
    GRACE = "GRACE"
    EXHAUSTED = "EXHAUSTED"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"


class AgentStateMachine:
    """Manages agent lifecycle state and emits events for the dashboard."""

    TRANSITIONS = {
        AgentState.IDLE: [AgentState.REQUESTING],
        AgentState.REQUESTING: [AgentState.ACTIVE, AgentState.STOPPED],
        AgentState.ACTIVE: [AgentState.RENEWING, AgentState.GRACE, AgentState.DRAINING],
        AgentState.RENEWING: [AgentState.ACTIVE, AgentState.GRACE],
        AgentState.GRACE: [AgentState.ACTIVE, AgentState.EXHAUSTED],
        AgentState.EXHAUSTED: [AgentState.DRAINING, AgentState.STOPPED],
        AgentState.DRAINING: [AgentState.STOPPED],
        AgentState.STOPPED: [AgentState.IDLE],
    }

    def __init__(self):
        self._state = AgentState.IDLE
        self._listeners: list[Callable] = []
        self._history: list[dict] = []

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def history(self) -> list[dict]:
        return self._history

    def transition(self, new_state: AgentState, reason: str = "") -> bool:
        """Attempt a state transition.

        Args:
            new_state: Target state.
            reason: Human-readable reason for the transition.

        Returns:
            True if transition succeeded, False if invalid.
        """
        allowed = self.TRANSITIONS.get(self._state, [])
        if new_state not in allowed:
            return False

        old_state = self._state
        self._state = new_state
        entry = {
            "from": old_state.value,
            "to": new_state.value,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._history.append(entry)

        for listener in self._listeners:
            try:
                listener("state_change", entry)
            except Exception:
                pass

        return True

    def on_event(self, callback: Callable) -> None:
        """Register a listener for state change events."""
        self._listeners.append(callback)

    def emit(self, event_type: str, data: dict) -> None:
        """Emit an arbitrary event to all listeners."""
        for listener in self._listeners:
            try:
                listener(event_type, data)
            except Exception:
                pass
