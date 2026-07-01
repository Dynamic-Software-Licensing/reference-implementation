"""Shared data models for the DSL control plane."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


def to_camel_case(snake_str: str) -> str:
    """Convert snake_case to lowerCamelCase."""
    parts = snake_str.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


def serialize(obj: Any) -> dict:
    """Serialize a dataclass to a dict with lowerCamelCase keys."""
    if hasattr(obj, "__dataclass_fields__"):
        return {to_camel_case(k): serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [serialize(item) for item in obj]
    return obj


@dataclass
class Dimension:
    name: str
    max_quantity: int


@dataclass
class Policy:
    heartbeat_seconds: int = 30
    renew_before_seconds: int = 60
    offline_grace_seconds: int = 300
    on_grace_exhausted: str = "DRAIN"


@dataclass
class Entitlement:
    tenant_id: str
    app_id: str
    isv_id: str
    dimensions: list[Dimension] = field(default_factory=list)
    max_leases: int = 1
    active_leases: int = 0
    license_modality: str = "hourly"
    policy: Policy = field(default_factory=Policy)


@dataclass
class Lease:
    lease_id: str
    tenant_id: str
    app_id: str
    isv_id: str
    status: str  # ACTIVE, RENEWED, SHADOW, REVOKED, EXPIRED
    bound_identity: dict = field(default_factory=dict)
    dimensions: list[Dimension] = field(default_factory=list)
    policy: Policy = field(default_factory=Policy)
    work_id: str = ""
    issued_at: str = ""
    expires_at: str = ""
    last_renewed_at: str = ""
    revoked_at: str = ""
    revoke_reason: str = ""
    reissue_id: str = ""
    cutover_token: str = ""


@dataclass
class UsageRecord:
    lease_id: str
    tenant_id: str
    isv_id: str
    product_id: str
    dimension: str
    quantity: float
    granularity: str
    timestamp: str
    work_id: str
    submitted_at: str = ""
