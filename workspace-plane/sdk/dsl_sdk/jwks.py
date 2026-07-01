"""JWKS fetcher with local caching."""

import time
from typing import Optional

import httpx
from jwt.algorithms import RSAAlgorithm


class JWKSFetcher:
    """Fetches and caches JWKS public keys from the control plane."""

    def __init__(self, jwks_url: str, cache_ttl: int = 3600):
        """
        Args:
            jwks_url: URL of the /.well-known/jwks.json endpoint.
            cache_ttl: Cache lifetime in seconds (default 1 hour).
        """
        self._jwks_url = jwks_url
        self._cache_ttl = cache_ttl
        self._keys: dict[str, any] = {}  # kid -> public key object
        self._last_fetch: float = 0

    def get_key(self, kid: str):
        """Get the public key for a given key ID.

        If the kid is not in the cache, refreshes the cache from the endpoint.

        Args:
            kid: Key identifier from the JWT header.

        Returns:
            RSA public key object for signature verification.

        Raises:
            KeyError: If the kid is not found even after refresh.
        """
        # Try cache first
        if kid in self._keys and not self._is_cache_expired():
            return self._keys[kid]

        # Refresh cache
        self._fetch_keys()

        if kid not in self._keys:
            raise KeyError(f"Key ID '{kid}' not found in JWKS endpoint at {self._jwks_url}")

        return self._keys[kid]

    def _is_cache_expired(self) -> bool:
        return (time.time() - self._last_fetch) > self._cache_ttl

    def _fetch_keys(self):
        """Fetch JWKS from the endpoint and parse keys."""
        response = httpx.get(self._jwks_url, timeout=10)
        response.raise_for_status()
        jwks = response.json()

        self._keys = {}
        for key_data in jwks.get("keys", []):
            kid = key_data.get("kid")
            if kid:
                # Convert JWK to RSA public key using PyJWT's built-in parser
                public_key = RSAAlgorithm.from_jwk(key_data)
                self._keys[kid] = public_key

        self._last_fetch = time.time()

    def invalidate(self):
        """Force cache invalidation (e.g., on key rotation detection)."""
        self._last_fetch = 0
        self._keys = {}
