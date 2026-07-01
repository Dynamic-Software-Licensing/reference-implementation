"""Grace period state machine."""

import time
import threading
from typing import Callable, Optional


class GracePeriodManager:
    """Manages the offline grace period countdown.

    When the license agent cannot renew and the token expires, the grace
    period begins. The application continues operating during this window.
    If connectivity returns before grace expires, normal operation resumes.
    """

    def __init__(
        self,
        grace_seconds: int,
        on_tick: Optional[Callable[[int], None]] = None,
        on_exhausted: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            grace_seconds: Total grace period duration.
            on_tick: Called every second with remaining seconds.
            on_exhausted: Called when grace period reaches zero.
        """
        self._grace_seconds = grace_seconds
        self._on_tick = on_tick
        self._on_exhausted = on_exhausted
        self._active = False
        self._remaining = 0
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def remaining_seconds(self) -> int:
        return self._remaining

    def start(self) -> None:
        """Start the grace period countdown."""
        if self._active:
            return

        self._active = True
        self._remaining = self._grace_seconds
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._countdown, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Cancel the grace period (connectivity restored)."""
        self._active = False
        self._stop_event.set()

    def _countdown(self) -> None:
        """Internal countdown loop."""
        start_time = time.monotonic()

        while self._remaining > 0 and not self._stop_event.is_set():
            self._stop_event.wait(timeout=1.0)
            if self._stop_event.is_set():
                break

            elapsed = time.monotonic() - start_time
            self._remaining = max(0, self._grace_seconds - int(elapsed))

            if self._on_tick:
                try:
                    self._on_tick(self._remaining)
                except Exception:
                    pass

        if self._remaining <= 0 and self._active:
            self._active = False
            if self._on_exhausted:
                try:
                    self._on_exhausted()
                except Exception:
                    pass
