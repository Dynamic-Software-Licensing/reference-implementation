"""License state management — main SDK interface for applications."""

from typing import Callable, Optional

from .validator import TokenValidator, TokenClaims, InvalidTokenError
from .jwks import JWKSFetcher


class DslLicense:
    """Main SDK interface for the application.

    Provides access to current license state, dimensions, and lifecycle events.
    """

    def __init__(self, jwks_url: str, expected_audience: Optional[str] = None):
        """
        Args:
            jwks_url: URL of the JWKS endpoint.
            expected_audience: Expected 'aud' claim value (application ID).
        """
        self._jwks = JWKSFetcher(jwks_url)
        self._validator = TokenValidator(self._jwks, expected_audience)
        self._claims: Optional[TokenClaims] = None
        self._raw_token: str = ""
        self._callbacks: dict[str, list[Callable]] = {
            "revoked": [],
            "grace_enter": [],
            "grace_exit": [],
            "renewed": [],
            "expired": [],
        }

    def validate_token(self, token: str) -> TokenClaims:
        """Validate a new token and update the current license state.

        Args:
            token: Raw JWT string from the license agent.

        Returns:
            TokenClaims with the validated claims.

        Raises:
            InvalidTokenError: If validation fails.
        """
        claims = self._validator.validate(token)
        self._claims = claims
        self._raw_token = token
        return claims

    @property
    def dimensions(self) -> dict[str, int]:
        """Currently granted dimensions as {name: maxQuantity}.

        Returns empty dict if no valid token is loaded.
        """
        if not self._claims:
            return {}
        return {
            d.get("name", ""): d.get("maxQuantity", 0)
            for d in self._claims.dimensions
        }

    @property
    def is_valid(self) -> bool:
        """Whether the current token is valid (loaded and not expired)."""
        return self._claims is not None and not self._claims.is_expired

    @property
    def expires_in_seconds(self) -> int:
        """Seconds until current token expires. Returns 0 if no token."""
        if not self._claims:
            return 0
        return self._claims.expires_in_seconds

    @property
    def lease_id(self) -> str:
        """Current lease ID, or empty string if no token."""
        return self._claims.lease_id if self._claims else ""

    @property
    def policy(self) -> dict:
        """Current policy from the token."""
        return self._claims.policy if self._claims else {}

    @property
    def bound_identity(self) -> dict:
        """The identity this lease is bound to."""
        return self._claims.bound_identity if self._claims else {}

    @property
    def raw_token(self) -> str:
        """The raw JWT string (for display/debugging)."""
        return self._raw_token

    def decode_for_display(self) -> dict:
        """Decode the current token without verification (for dashboard display)."""
        if not self._raw_token:
            return {}
        return self._validator.decode_without_verification(self._raw_token)

    # ─── Event Callbacks ──────────────────────────────────────────────────

    def on_revoked(self, callback: Callable) -> None:
        """Register callback for revocation events."""
        self._callbacks["revoked"].append(callback)

    def on_grace_enter(self, callback: Callable) -> None:
        """Register callback for grace period entry."""
        self._callbacks["grace_enter"].append(callback)

    def on_grace_exit(self, callback: Callable) -> None:
        """Register callback for grace period exit (renewal success)."""
        self._callbacks["grace_exit"].append(callback)

    def on_renewed(self, callback: Callable) -> None:
        """Register callback for successful renewal."""
        self._callbacks["renewed"].append(callback)

    def on_expired(self, callback: Callable) -> None:
        """Register callback for token expiry (grace exhausted)."""
        self._callbacks["expired"].append(callback)

    def emit(self, event: str, **kwargs) -> None:
        """Emit an event to registered callbacks.

        Args:
            event: Event name (revoked, grace_enter, grace_exit, renewed, expired).
            **kwargs: Event-specific data passed to callbacks.
        """
        for cb in self._callbacks.get(event, []):
            try:
                cb(**kwargs)
            except Exception:
                pass  # Don't let callback errors crash the SDK
