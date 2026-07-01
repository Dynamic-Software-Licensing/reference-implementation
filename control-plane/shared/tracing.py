"""W3C Trace Context propagation helpers."""

import uuid
import re
from typing import Optional


TRACEPARENT_REGEX = re.compile(
    r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)


def extract_trace_context(headers: dict) -> dict:
    """Extract W3C Trace Context from request headers.

    Args:
        headers: HTTP request headers (case-insensitive keys).

    Returns:
        Dict with traceparent and tracestate values (or empty strings).
    """
    normalized = {k.lower(): v for k, v in (headers or {}).items()}
    return {
        "traceparent": normalized.get("traceparent", ""),
        "tracestate": normalized.get("tracestate", ""),
    }


def generate_traceparent() -> str:
    """Generate a new W3C traceparent header value."""
    version = "00"
    trace_id = uuid.uuid4().hex
    parent_id = uuid.uuid4().hex[:16]
    trace_flags = "01"  # sampled
    return f"{version}-{trace_id}-{parent_id}-{trace_flags}"


def propagate_trace_headers(
    incoming_headers: dict,
    response_headers: Optional[dict] = None,
) -> dict:
    """Propagate trace context from request to response headers.

    If the request has a traceparent, include it in the response.
    If not, generate a new one.

    Args:
        incoming_headers: Request headers.
        response_headers: Existing response headers to extend.

    Returns:
        Response headers dict with trace context included.
    """
    if response_headers is None:
        response_headers = {}

    ctx = extract_trace_context(incoming_headers)
    traceparent = ctx["traceparent"]

    if not traceparent or not TRACEPARENT_REGEX.match(traceparent):
        traceparent = generate_traceparent()

    response_headers["traceparent"] = traceparent
    if ctx["tracestate"]:
        response_headers["tracestate"] = ctx["tracestate"]

    return response_headers
