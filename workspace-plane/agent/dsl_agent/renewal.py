"""Lease renewal scheduler with exponential backoff."""

import time
import random
import threading
from typing import Callable, Optional
from datetime import datetime, timezone


class RenewalScheduler:
    """Schedules and manages lease renewal timing.

    Begins renewal attempts at (expiresAt - renewBeforeSeconds).
    On failure, retries with exponential backoff and jitter.
    """

    def __init__(
        self,
        renew_before_seconds: int = 60,
        initial_backoff_ms: int = 2000,
        max_backoff_ms: int = 30000,
        on_renew: Optional[Callable[[], bool]] = None,
        on_failure: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            renew_before_seconds: Seconds before expiry to start renewal.
            initial_backoff_ms: Initial retry delay in milliseconds.
            max_backoff_ms: Maximum retry delay in milliseconds.
            on_renew: Callback that performs the actual renewal. Returns True on success.
            on_failure: Callback when renewal fails (receives error message).
        """
        self._renew_before = renew_before_seconds
        self._initial_backoff = initial_backoff_ms
        self._max_backoff = max_backoff_ms
        self._on_renew = on_renew
        self._on_failure = on_failure
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._expires_at: float = 0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def schedule(self, expires_at: str) -> None:
        """Schedule renewal for a given expiry time.

        Args:
            expires_at: ISO 8601 expiry timestamp.
        """
        # Stop previous thread if it's a different one (not the current thread)
        self._stop_event.set()
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

        self._expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._renewal_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the renewal scheduler."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _renewal_loop(self) -> None:
        """Main renewal loop: wait until renewal window, then attempt renewal."""
        # Wait until renewal window opens
        renewal_time = self._expires_at - self._renew_before
        now = time.time()
        if renewal_time > now:
            wait_seconds = renewal_time - now
            self._stop_event.wait(timeout=wait_seconds)
            if self._stop_event.is_set():
                return

        # Attempt renewal with backoff
        attempt = 0
        while not self._stop_event.is_set():
            if self._on_renew:
                try:
                    success = self._on_renew()
                    if success:
                        return  # Renewal succeeded, new schedule will be set
                except Exception as e:
                    if self._on_failure:
                        self._on_failure(str(e))

            # Exponential backoff with jitter
            backoff = min(
                self._initial_backoff * (2 ** attempt),
                self._max_backoff,
            )
            jitter = random.uniform(0, backoff * 0.1)
            wait_ms = backoff + jitter
            attempt += 1

            self._stop_event.wait(timeout=wait_ms / 1000)
