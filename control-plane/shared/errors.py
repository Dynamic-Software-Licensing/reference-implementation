"""RFC 9457 Problem Details error response builder."""

import json
from typing import Any


def problem_response(
    status: int,
    error_type: str,
    title: str,
    detail: str,
    **extensions: Any,
) -> dict:
    """Build an API Gateway-compatible response following RFC 9457.

    Args:
        status: HTTP status code.
        error_type: Error identifier (appended to urn:dsl:error:).
        title: Short human-readable summary.
        detail: Human-readable explanation of this specific occurrence.
        **extensions: Additional RFC 9457 extension members.

    Returns:
        API Gateway Lambda proxy response dict.
    """
    body = {
        "type": f"urn:dsl:error:{error_type}",
        "title": title,
        "status": status,
        "detail": detail,
        **extensions,
    }
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/problem+json",
        },
        "body": json.dumps(body),
    }
