"""Usage record buffering and submission."""

import threading
import time
from datetime import datetime, timezone
from typing import Optional, Callable

from .client import ControlPlaneClient, ControlPlaneError


class UsageBuffer:
    """Buffers usage records locally and submits them in batches."""

    def __init__(
        self,
        client: ControlPlaneClient,
        flush_interval: int = 60,
        on_submitted: Optional[Callable[[list], None]] = None,
    ):
        """
        Args:
            client: Control plane HTTP client.
            flush_interval: Seconds between flush attempts.
            on_submitted: Callback when records are successfully submitted.
        """
        self._client = client
        self._flush_interval = flush_interval
        self._on_submitted = on_submitted
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def record(
        self,
        lease_id: str,
        tenant_id: str,
        product_id: str,
        dimension: str,
        quantity: float,
        granularity: str = "minutes",
        work_id: str = "",
    ) -> None:
        """Buffer a usage record.

        Args:
            lease_id: Active lease ID.
            tenant_id: Tenant identifier.
            product_id: Application identifier.
            dimension: Metered dimension name.
            quantity: Amount consumed.
            granularity: Time granularity.
            work_id: Correlation identifier.
        """
        record = {
            "leaseId": lease_id,
            "tenantId": tenant_id,
            "productId": product_id,
            "dimension": dimension,
            "quantity": quantity,
            "granularity": granularity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "workId": work_id,
        }
        with self._lock:
            self._buffer.append(record)

    def start(self) -> None:
        """Start the background flush loop."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the flush loop and attempt a final flush."""
        self._stop_event.set()
        self._flush()  # Final flush

    def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._flush_interval)
            if not self._stop_event.is_set():
                self._flush()

    def _flush(self) -> None:
        """Submit all buffered records to the control plane."""
        with self._lock:
            if not self._buffer:
                return
            to_submit = self._buffer.copy()
            self._buffer.clear()

        try:
            results = self._client.submit_usage(to_submit)
            if self._on_submitted:
                self._on_submitted(to_submit)
        except ControlPlaneError:
            # Re-buffer on failure
            with self._lock:
                self._buffer = to_submit + self._buffer
