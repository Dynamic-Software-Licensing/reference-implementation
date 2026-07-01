"""JWKS endpoint handler — serves public signing keys in RFC 7517 format.

Uses only boto3 and standard library (no cryptography package needed).
Parses the DER-encoded RSA public key manually to extract n and e.
"""

import json
import os
import base64
import struct

import boto3


kms_client = boto3.client("kms")
KEY_ID = os.environ["KMS_KEY_ID"]

# Cache the JWKS response
_jwks_cache: dict | None = None


def _int_to_base64url(data: bytes) -> str:
    """Base64url encode bytes without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _parse_der_integer(data: bytes, offset: int) -> tuple:
    """Parse a DER INTEGER and return (integer_bytes, new_offset)."""
    if data[offset] != 0x02:
        raise ValueError(f"Expected INTEGER tag (0x02), got {hex(data[offset])}")
    offset += 1
    length, offset = _parse_der_length(data, offset)
    int_bytes = data[offset:offset + length]
    # Remove leading zero byte if present (DER encoding for positive integers)
    if int_bytes[0] == 0x00:
        int_bytes = int_bytes[1:]
    return int_bytes, offset + length


def _parse_der_length(data: bytes, offset: int) -> tuple:
    """Parse DER length and return (length, new_offset)."""
    if data[offset] & 0x80 == 0:
        return data[offset], offset + 1
    num_bytes = data[offset] & 0x7F
    offset += 1
    length = int.from_bytes(data[offset:offset + num_bytes], 'big')
    return length, offset + num_bytes


def _parse_rsa_public_key_der(der_bytes: bytes) -> tuple:
    """Parse SubjectPublicKeyInfo DER to extract RSA n and e.
    
    Structure:
    SEQUENCE {
        SEQUENCE { OID rsaEncryption, NULL }
        BIT STRING {
            SEQUENCE {
                INTEGER modulus (n)
                INTEGER exponent (e)
            }
        }
    }
    
    Returns (n_bytes, e_bytes).
    """
    offset = 0
    
    # Outer SEQUENCE
    if der_bytes[offset] != 0x30:
        raise ValueError("Expected SEQUENCE")
    offset += 1
    _, offset = _parse_der_length(der_bytes, offset)
    
    # Algorithm SEQUENCE (skip it)
    if der_bytes[offset] != 0x30:
        raise ValueError("Expected algorithm SEQUENCE")
    offset += 1
    alg_len, offset = _parse_der_length(der_bytes, offset)
    offset += alg_len  # Skip algorithm OID + NULL
    
    # BIT STRING
    if der_bytes[offset] != 0x03:
        raise ValueError("Expected BIT STRING")
    offset += 1
    _, offset = _parse_der_length(der_bytes, offset)
    offset += 1  # Skip the "unused bits" byte (always 0x00)
    
    # Inner SEQUENCE containing n and e
    if der_bytes[offset] != 0x30:
        raise ValueError("Expected inner SEQUENCE")
    offset += 1
    _, offset = _parse_der_length(der_bytes, offset)
    
    # INTEGER n (modulus)
    n_bytes, offset = _parse_der_integer(der_bytes, offset)
    
    # INTEGER e (exponent)
    e_bytes, offset = _parse_der_integer(der_bytes, offset)
    
    return n_bytes, e_bytes


def lambda_handler(event, context):
    """Handle GET /.well-known/jwks.json requests."""
    global _jwks_cache

    if _jwks_cache is None:
        response = kms_client.get_public_key(KeyId=KEY_ID)
        der_bytes = response["PublicKey"]
        key_id = KEY_ID

        # Parse the DER to get n and e
        n_bytes, e_bytes = _parse_rsa_public_key_der(der_bytes)

        jwk = {
            "kty": "RSA",
            "kid": key_id,
            "use": "sig",
            "alg": "RS256",
            "n": _int_to_base64url(n_bytes),
            "e": _int_to_base64url(e_bytes),
        }
        _jwks_cache = {"keys": [jwk]}

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(_jwks_cache),
    }
