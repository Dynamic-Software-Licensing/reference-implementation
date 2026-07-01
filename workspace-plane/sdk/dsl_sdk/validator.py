"""JWT token validator for DSL lease tokens."""

import json
import time
import base64
from dataclasses import dataclass
from typing import Optional

import jwt
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidSignatureError,
    DecodeError,
)

from .jwks import JWKSFetcher


@dataclass
class TokenClaims:
    """Decoded and validated token claims."""

    lease_id: str
    tenant_id: str
    app_id: str
    dimensions: list[dict]
    policy: dict
    bound_identity: dict
    issued_at: int
    expires_at: int
    jti: str

    @property
    def expires_in_seconds(self) -> int:
        """Seconds until this token expires."""
        return max(0, self.expires_at - int(time.time()))

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class TokenValidator:
    """Validates DSL lease tokens using JWKS public keys."""

    def __init__(self, jwks_fetcher: JWKSFetcher, expected_audience: Optional[str] = None):
        """
        Args:
            jwks_fetcher: JWKS fetcher instance for retrieving public keys.
            expected_audience: If set, validates the 'aud' claim matches.
        """
        self._jwks = jwks_fetcher
        self._audience = expected_audience

    def validate(self, token: str) -> TokenClaims:
        """Validate a JWT token and return its claims.

        Args:
            token: The raw JWT string (header.claims.signature).

        Returns:
            TokenClaims dataclass with decoded claims.

        Raises:
            InvalidTokenError: If the token is invalid, expired, or unverifiable.
        """
        # Decode header to get kid
        try:
            header = self._decode_header(token)
        except Exception as e:
            raise InvalidTokenError(f"Cannot decode token header: {e}")

        kid = header.get("kid")
        if not kid:
            raise InvalidTokenError("Token header missing 'kid' field.")

        # Get the public key
        try:
            public_key = self._jwks.get_key(kid)
        except KeyError:
            # Try one more time after cache invalidation (handles key rotation)
            self._jwks.invalidate()
            try:
                public_key = self._jwks.get_key(kid)
            except KeyError:
                raise InvalidTokenError(f"Unknown signing key: {kid}")

        # Verify signature and decode claims
        decode_options = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_nbf": True,
            "verify_iat": True,
        }
        if self._audience:
            decode_options["verify_aud"] = True
        else:
            decode_options["verify_aud"] = False

        try:
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=self._audience,
                options=decode_options,
            )
        except ExpiredSignatureError:
            raise InvalidTokenError("Token has expired.")
        except InvalidSignatureError:
            raise InvalidTokenError("Token signature verification failed.")
        except DecodeError as e:
            raise InvalidTokenError(f"Token decode error: {e}")
        except Exception as e:
            raise InvalidTokenError(f"Token validation failed: {e}")

        return TokenClaims(
            lease_id=claims.get("leaseId", ""),
            tenant_id=claims.get("tenantId", ""),
            app_id=claims.get("appId", ""),
            dimensions=claims.get("dimensions", []),
            policy=claims.get("policy", {}),
            bound_identity=claims.get("boundIdentity", {}),
            issued_at=claims.get("iat", 0),
            expires_at=claims.get("exp", 0),
            jti=claims.get("jti", ""),
        )

    def decode_without_verification(self, token: str) -> dict:
        """Decode token claims without verifying signature (for display/debugging).

        Security note: This method is intentionally used WITHOUT verification
        to display token contents in the dashboard UI. It is never used for
        authorization decisions. All enforcement uses the verified validate() method.

        Args:
            token: The raw JWT string.

        Returns:
            Dict of all claims.
        """
        return jwt.decode(token, options={"verify_signature": False})  # nosemgrep: python.jwt.security.unverified-jwt-decode

    @staticmethod
    def _decode_header(token: str) -> dict:
        """Decode the JWT header (first segment)."""
        header_segment = token.split(".")[0]
        # Add padding
        padding = 4 - len(header_segment) % 4
        if padding != 4:
            header_segment += "=" * padding
        header_bytes = base64.urlsafe_b64decode(header_segment)
        return json.loads(header_bytes)


class InvalidTokenError(Exception):
    """Raised when token validation fails."""
    pass
