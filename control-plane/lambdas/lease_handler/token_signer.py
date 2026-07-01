"""JWT token signing via KMS."""

import base64
import json
import os
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import boto3


kms_client = boto3.client("kms")
KMS_KEY_ID = os.environ.get("KMS_KEY_ID", "")


def _decimal_default(obj):
    """JSON serializer for Decimal types from DynamoDB."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_lease_token(
    lease_id: str,
    tenant_id: str,
    app_id: str,
    dimensions: list,
    policy: dict,
    bound_identity: dict,
    issued_at: datetime,
    expires_at: datetime,
) -> str:
    """Sign a lease JWT token using KMS.

    Returns the complete JWT string (header.claims.signature).
    """
    # Header
    header = {
        "alg": "RS256",
        "kid": KMS_KEY_ID,
        "typ": "JWT",
    }

    # Claims
    claims = {
        "iss": "dsl-control-plane",
        "sub": tenant_id,
        "aud": app_id,
        "exp": int(expires_at.timestamp()),
        "nbf": int(issued_at.timestamp()),
        "iat": int(issued_at.timestamp()),
        "jti": str(uuid4()),
        "leaseId": lease_id,
        "tenantId": tenant_id,
        "appId": app_id,
        "dimensions": dimensions,
        "policy": policy,
        "boundIdentity": bound_identity,
    }

    # Encode
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    claims_b64 = _b64url_encode(json.dumps(claims, separators=(",", ":"), default=_decimal_default).encode())
    signing_input = f"{header_b64}.{claims_b64}"

    # Sign via KMS
    response = kms_client.sign(
        KeyId=KMS_KEY_ID,
        Message=signing_input.encode("utf-8"),
        MessageType="RAW",
        SigningAlgorithm="RSASSA_PKCS1_V1_5_SHA_256",
    )
    signature = _b64url_encode(response["Signature"])

    return f"{signing_input}.{signature}"
