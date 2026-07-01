"""Sample Media Processor Application.

A simulated media processing application that demonstrates:
- Consuming a license token from the SDK
- Enforcing dimension limits (max channels)
- Responding to lifecycle events (revocation, grace period)
- Reporting usage back to the agent
"""

import time
import click
from dsl_sdk.license_state import DslLicense
from dsl_sdk.validator import InvalidTokenError


class MediaProcessor:
    """Simulated media encoder with channel-based licensing."""

    def __init__(self, license: DslLicense):
        self._license = license
        self._active_channels: dict[str, bool] = {}
        self._draining = False

        # Register lifecycle callbacks
        license.on_revoked(self._on_revoked)
        license.on_grace_enter(self._on_grace_enter)
        license.on_renewed(self._on_renewed)
        license.on_expired(self._on_expired)

    @property
    def max_channels(self) -> int:
        """Licensed maximum channel count."""
        return self._license.dimensions.get("maxChannels", 0)

    @property
    def active_channels(self) -> int:
        """Current number of active channels."""
        return len(self._active_channels)

    @property
    def is_draining(self) -> bool:
        return self._draining

    def start_channel(self, channel_id: str) -> bool:
        """Start a processing channel.

        Args:
            channel_id: Unique identifier for the channel.

        Returns:
            True if started successfully, False if at dimension limit or draining.
        """
        if self._draining:
            print(f"  [App] REJECTED channel '{channel_id}' — application is draining")
            return False

        if not self._license.is_valid:
            print(f"  [App] REJECTED channel '{channel_id}' — no valid license")
            return False

        if self.active_channels >= self.max_channels:
            print(f"  [App] REJECTED channel '{channel_id}' — at limit ({self.active_channels}/{self.max_channels})")
            return False

        self._active_channels[channel_id] = True
        print(f"  [App] Started channel '{channel_id}' ({self.active_channels}/{self.max_channels})")
        return True

    def stop_channel(self, channel_id: str) -> None:
        """Stop a processing channel."""
        if channel_id in self._active_channels:
            del self._active_channels[channel_id]
            print(f"  [App] Stopped channel '{channel_id}' ({self.active_channels}/{self.max_channels})")

    def drain(self) -> None:
        """Finish active work, stop accepting new channels."""
        self._draining = True
        print(f"  [App] DRAINING — refusing new channels, {self.active_channels} still active")

    def stop(self) -> None:
        """Immediate stop — all channels terminated."""
        self._active_channels.clear()
        self._draining = True
        print("  [App] STOPPED — all channels terminated")

    def _on_revoked(self, **kwargs):
        reason = kwargs.get("reason", "unknown")
        print(f"  [App] ⚠️  License REVOKED (reason: {reason}) — draining...")
        self.drain()

    def _on_grace_enter(self, **kwargs):
        remaining = kwargs.get("grace_seconds_remaining", 0)
        print(f"  [App] ⚠️  Entering GRACE PERIOD ({remaining}s remaining)")

    def _on_renewed(self, **kwargs):
        self._draining = False
        print(f"  [App] ✓ License renewed — normal operation resumed")

    def _on_expired(self, **kwargs):
        action = kwargs.get("exhaustion_action", "DRAIN")
        print(f"  [App] ✗ License EXPIRED — executing {action}")
        if action == "STOP":
            self.stop()
        else:
            self.drain()
