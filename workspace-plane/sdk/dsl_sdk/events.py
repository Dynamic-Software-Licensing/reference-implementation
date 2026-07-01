"""Event types for the DSL SDK lifecycle."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class LeaseRevokedEvent:
    """Emitted when the lease is revoked by the control plane."""
    lease_id: str
    reason: str


@dataclass
class GraceEnterEvent:
    """Emitted when the agent enters the grace period."""
    lease_id: str
    grace_seconds_remaining: int


@dataclass
class GraceExitEvent:
    """Emitted when connectivity is restored and lease is renewed."""
    lease_id: str


@dataclass
class LeaseRenewedEvent:
    """Emitted when the lease is successfully renewed."""
    lease_id: str
    new_expiry: str


@dataclass
class LeaseExpiredEvent:
    """Emitted when grace period is exhausted and the lease is terminal."""
    lease_id: str
    exhaustion_action: str  # DRAIN, DEGRADE, or STOP
