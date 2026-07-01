"""Lease handler — issue, renew, reissue, finalize, and revoke leases."""

import json
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from token_signer import sign_lease_token
from identity_verifier import verify_identity_evidence, extract_binding

import boto3
from botocore.exceptions import ClientError


def _decimal_default(obj):
    """JSON serializer for Decimal types from DynamoDB."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _to_json(obj) -> str:
    """Serialize to JSON handling DynamoDB Decimal types."""
    return json.dumps(obj, default=_decimal_default)


dynamodb = boto3.resource("dynamodb")
entitlements_table = dynamodb.Table(os.environ["ENTITLEMENTS_TABLE"])
leases_table = dynamodb.Table(os.environ["LEASES_TABLE"])
connections_table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])

WS_API_ENDPOINT = os.environ.get("WS_API_ENDPOINT", "")


def lambda_handler(event, context):
    """Route requests based on HTTP method and path."""
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("requestContext", {}).get("http", {}).get("path", "")
    path_params = event.get("pathParameters") or {}
    lease_id = path_params.get("leaseId")

    try:
        body = json.loads(event.get("body", "{}")) if event.get("body") else {}
    except json.JSONDecodeError:
        return _error(400, "validation", "Invalid JSON", "Request body is not valid JSON.")

    if method == "POST" and path == "/v1/leases":
        return _issue_lease(body)
    elif method == "POST" and path == "/v1/admin/reset":
        return _reset_all()
    elif method == "GET" and path == "/v1/admin/observability":
        return _observability()
    elif method == "POST" and path.endswith("/renew"):
        return _renew_lease(lease_id, body)
    elif method == "POST" and path.endswith("/reissue"):
        return _reissue_lease(lease_id, body)
    elif method == "POST" and path.endswith("/finalizeReissue"):
        return _finalize_reissue(lease_id, body)
    elif method == "DELETE" and lease_id:
        return _revoke_lease(lease_id, body)

    return _error(404, "not-found", "Not Found", f"No handler for {method} {path}")


def _issue_lease(body: dict) -> dict:
    """Issue a new lease."""
    # Validate required fields
    required = ["app", "tenantId", "identityEvidence", "workId"]
    missing = [f for f in required if f not in body]
    if missing:
        return _error(400, "validation", "Missing Fields", f"Required: {', '.join(missing)}")

    tenant_id = body["tenantId"]
    app_id = body["app"]
    isv_id = body.get("isvId", "isv-acme")  # Default for demo
    identity_evidence = body["identityEvidence"]
    work_id = body["workId"]

    # Verify identity evidence format
    if not verify_identity_evidence(identity_evidence):
        return _error(403, "identity-verification-failed", "Identity Verification Failed",
                      "Identity evidence format is invalid or unverifiable.")

    # Look up entitlement
    pk = f"TENANT#{tenant_id}"
    sk = f"APP#{app_id}#ISV#{isv_id}"

    try:
        resp = entitlements_table.get_item(Key={"PK": pk, "SK": sk})
    except ClientError as e:
        return _error(500, "internal", "Internal Error", str(e))

    entitlement = resp.get("Item")
    if not entitlement:
        return _error(404, "entitlement-not-found", "Entitlement Not Found",
                      f"No entitlement found for tenant={tenant_id}, app={app_id}, isv={isv_id}")

    # Check quota — atomic increment with condition
    max_leases = int(entitlement["maxLeases"])
    try:
        entitlements_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET activeLeases = activeLeases + :one",
            ConditionExpression="activeLeases < :max",
            ExpressionAttributeValues={":one": 1, ":max": max_leases},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _error(429, "entitlement-exhausted", "Entitlement Exhausted",
                          "All lease slots for this entitlement are currently in use.",
                          category="quota", retryable=True,
                          entitled=max_leases, active=max_leases)
        raise

    # Create lease
    import uuid, secrets
    lease_id = f"L-{uuid.uuid4().hex[:20]}"
    now = datetime.now(timezone.utc)
    policy = entitlement.get("policy", {})
    ttl_seconds = int(policy.get("renewBeforeSeconds", 60)) * 3  # Token TTL = 3x renewal window
    expires_at = now + timedelta(seconds=ttl_seconds)
    bound_identity = extract_binding(identity_evidence)

    lease_item = {
        "PK": f"LEASE#{lease_id}",
        "SK": "META",
        "leaseId": lease_id,
        "tenantId": tenant_id,
        "appId": app_id,
        "isvId": isv_id,
        "status": "ACTIVE",
        "boundIdentity": bound_identity,
        "dimensions": entitlement.get("dimensions", []),
        "policy": policy,
        "workId": work_id,
        "issuedAt": now.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "lastRenewedAt": "",
        "revokedAt": "",
        "revokeReason": "",
        "reissueId": "",
        "cutoverToken": "",
        "GSI1PK": f"TENANT#{tenant_id}#APP#{app_id}",
        "GSI1SK": f"STATUS#ACTIVE#LEASE#{lease_id}",
    }
    leases_table.put_item(Item=lease_item)

    # Sign token
    token = sign_lease_token(
        lease_id=lease_id,
        tenant_id=tenant_id,
        app_id=app_id,
        dimensions=entitlement.get("dimensions", []),
        policy=policy,
        bound_identity=bound_identity,
        issued_at=now,
        expires_at=expires_at,
    )

    return {
        "statusCode": 201,
        "headers": {"Content-Type": "application/json"},
        "body": _to_json({
            "leaseId": lease_id,
            "app": app_id,
            "tenantId": tenant_id,
            "token": token,
            "issuedAt": now.isoformat(),
            "expiresAt": expires_at.isoformat(),
            "licenseModality": entitlement.get("licenseModality", "hourly"),
            "dimensions": entitlement.get("dimensions", []),
            "boundIdentity": bound_identity,
            "policy": policy,
        }),
    }


def _renew_lease(lease_id: str, body: dict) -> dict:
    """Renew an existing lease."""
    if not lease_id:
        return _error(400, "validation", "Missing Lease ID", "leaseId is required in the URL path.")

    identity_evidence = body.get("identityEvidence")
    if not identity_evidence:
        return _error(400, "validation", "Missing Identity Evidence", "identityEvidence is required.")

    # Fetch lease
    resp = leases_table.get_item(Key={"PK": f"LEASE#{lease_id}", "SK": "META"})
    lease = resp.get("Item")
    if not lease:
        return _error(404, "lease-not-found", "Lease Not Found", f"Lease {lease_id} does not exist.")

    # Check status
    status = lease["status"]
    if status == "REVOKED":
        return _error(409, "lease-revoked", "Lease Revoked",
                      f"Lease {lease_id} has been revoked and cannot be renewed.",
                      category="conflict", retryable=False)
    if status not in ("ACTIVE", "RENEWED"):
        return _error(409, "lease-not-active", "Lease Not Active",
                      f"Lease {lease_id} is in state {status} and cannot be renewed.")

    # Verify identity matches binding — compare the logical binding key only
    new_binding = extract_binding(identity_evidence)
    stored_binding = lease.get("boundIdentity", {})

    def get_binding_key(b):
        """Extract the primary binding identifier regardless of platform type."""
        t = b.get("type", "")
        if t == "aws-role":
            return b.get("roleArn", "")
        elif t == "ec2-instance":
            return b.get("instanceId", "")
        elif t == "kubernetes-sa":
            return b.get("binding", "")
        elif t == "spiffe":
            return b.get("spiffeId", "")
        elif t == "x509":
            return b.get("subjectDN", "")
        # Fallback: compare entire dict as string
        return str(b)

    if get_binding_key(new_binding) != get_binding_key(stored_binding):
        return _error(403, "identity-mismatch", "Identity Mismatch",
                      f"Workload identity does not match the lease binding. "
                      f"Expected: {get_binding_key(stored_binding)}, "
                      f"Got: {get_binding_key(new_binding)}",
                      category="identity", retryable=False)

    # Extend lease
    now = datetime.now(timezone.utc)
    policy = lease.get("policy", {})
    ttl_seconds = int(policy.get("renewBeforeSeconds", 60)) * 3
    expires_at = now + timedelta(seconds=ttl_seconds)

    leases_table.update_item(
        Key={"PK": f"LEASE#{lease_id}", "SK": "META"},
        UpdateExpression="SET #s = :status, expiresAt = :exp, lastRenewedAt = :now, GSI1SK = :gsk",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "RENEWED",
            ":exp": expires_at.isoformat(),
            ":now": now.isoformat(),
            ":gsk": f"STATUS#RENEWED#LEASE#{lease_id}",
        },
    )

    # Sign new token
    token = sign_lease_token(
        lease_id=lease_id,
        tenant_id=lease["tenantId"],
        app_id=lease["appId"],
        dimensions=lease.get("dimensions", []),
        policy=policy,
        bound_identity=stored_binding,
        issued_at=now,
        expires_at=expires_at,
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": _to_json({
            "leaseId": lease_id,
            "token": token,
            "expiresAt": expires_at.isoformat(),
        }),
    }


def _reissue_lease(lease_id: str, body: dict) -> dict:
    """Create a shadow lease for failover (phase 1)."""
    if not lease_id:
        return _error(400, "validation", "Missing Lease ID", "leaseId is required.")

    to_identity = body.get("toIdentityEvidence")
    to_work_id = body.get("toWorkId", "")
    if not to_identity:
        return _error(400, "validation", "Missing Identity", "toIdentityEvidence is required.")

    # Fetch original lease
    resp = leases_table.get_item(Key={"PK": f"LEASE#{lease_id}", "SK": "META"})
    lease = resp.get("Item")
    if not lease:
        return _error(404, "lease-not-found", "Lease Not Found", f"Lease {lease_id} does not exist.")
    if lease["status"] not in ("ACTIVE", "RENEWED"):
        return _error(409, "lease-not-active", "Lease Not Active",
                      f"Lease {lease_id} cannot be reissued from state {lease['status']}.")

    # Create shadow lease
    import uuid, secrets
    shadow_id = f"L-{uuid.uuid4().hex[:20]}"
    cutover_token = f"ct-{secrets.token_hex(16)}"
    reissue_id = f"M-{secrets.token_hex(4)}"
    now = datetime.now(timezone.utc)
    policy = lease.get("policy", {})
    ttl_seconds = int(policy.get("renewBeforeSeconds", 60)) * 3
    expires_at = now + timedelta(seconds=ttl_seconds)
    new_binding = extract_binding(to_identity)

    shadow_item = {
        "PK": f"LEASE#{shadow_id}",
        "SK": "META",
        "leaseId": shadow_id,
        "tenantId": lease["tenantId"],
        "appId": lease["appId"],
        "isvId": lease["isvId"],
        "status": "SHADOW",
        "boundIdentity": new_binding,
        "dimensions": lease.get("dimensions", []),
        "policy": policy,
        "workId": to_work_id,
        "issuedAt": now.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "lastRenewedAt": "",
        "revokedAt": "",
        "revokeReason": "",
        "reissueId": reissue_id,
        "cutoverToken": cutover_token,
        "GSI1PK": f"TENANT#{lease['tenantId']}#APP#{lease['appId']}",
        "GSI1SK": f"STATUS#SHADOW#LEASE#{shadow_id}",
    }
    leases_table.put_item(Item=shadow_item)

    # Sign shadow token
    token = sign_lease_token(
        lease_id=shadow_id,
        tenant_id=lease["tenantId"],
        app_id=lease["appId"],
        dimensions=lease.get("dimensions", []),
        policy=policy,
        bound_identity=new_binding,
        issued_at=now,
        expires_at=expires_at,
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": _to_json({
            "reissueId": reissue_id,
            "cutoverToken": cutover_token,
            "toLease": {
                "leaseId": shadow_id,
                "token": token,
                "expiresAt": expires_at.isoformat(),
                "dimensions": lease.get("dimensions", []),
                "policy": policy,
            },
        }),
    }


def _finalize_reissue(lease_id: str, body: dict) -> dict:
    """Finalize a reissue — activate shadow, revoke original (phase 2)."""
    reissue_id = body.get("reissueId")
    cutover_token = body.get("cutoverToken")
    if not reissue_id or not cutover_token:
        return _error(400, "validation", "Missing Fields", "reissueId and cutoverToken are required.")

    # Find the shadow lease by scanning (simplified for demo)
    # In production, you'd use a GSI or store the mapping
    resp = leases_table.get_item(Key={"PK": f"LEASE#{lease_id}", "SK": "META"})
    original = resp.get("Item")
    if not original:
        return _error(404, "lease-not-found", "Lease Not Found", f"Original lease {lease_id} not found.")

    # Find shadow by reissue_id (scan — acceptable for demo)
    scan_resp = leases_table.scan(
        FilterExpression="reissueId = :rid AND cutoverToken = :ct",
        ExpressionAttributeValues={":rid": reissue_id, ":ct": cutover_token},
    )
    shadows = scan_resp.get("Items", [])
    if not shadows:
        return _error(401, "cutover-token-invalid", "Cutover Token Invalid",
                      "Cutover token does not match or has expired.")

    shadow = shadows[0]

    # Activate shadow
    leases_table.update_item(
        Key={"PK": f"LEASE#{shadow['leaseId']}", "SK": "META"},
        UpdateExpression="SET #s = :status, GSI1SK = :gsk",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "ACTIVE",
            ":gsk": f"STATUS#ACTIVE#LEASE#{shadow['leaseId']}",
        },
    )

    # Revoke original
    now = datetime.now(timezone.utc)
    leases_table.update_item(
        Key={"PK": f"LEASE#{lease_id}", "SK": "META"},
        UpdateExpression="SET #s = :status, revokedAt = :now, revokeReason = :reason, GSI1SK = :gsk",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "REVOKED",
            ":now": now.isoformat(),
            ":reason": "reissue_cutover",
            ":gsk": f"STATUS#REVOKED#LEASE#{lease_id}",
        },
    )

    # Decrement quota
    _decrement_active_leases(original["tenantId"], original["appId"], original["isvId"])

    # Push revocation to original agent
    _push_revocation(lease_id, "reissue_cutover")

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": _to_json({
            "state": "COMPLETED",
            "revoked": lease_id,
        }),
    }


def _revoke_lease(lease_id: str, body: dict) -> dict:
    """Revoke an active lease."""
    reason = body.get("reason", "admin_action")

    resp = leases_table.get_item(Key={"PK": f"LEASE#{lease_id}", "SK": "META"})
    lease = resp.get("Item")
    if not lease:
        return _error(404, "lease-not-found", "Lease Not Found", f"Lease {lease_id} does not exist.")
    if lease["status"] == "REVOKED":
        return _error(409, "lease-already-revoked", "Lease Already Revoked",
                      f"Lease {lease_id} has already been revoked.")

    now = datetime.now(timezone.utc)
    leases_table.update_item(
        Key={"PK": f"LEASE#{lease_id}", "SK": "META"},
        UpdateExpression="SET #s = :status, revokedAt = :now, revokeReason = :reason, GSI1SK = :gsk",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "REVOKED",
            ":now": now.isoformat(),
            ":reason": reason,
            ":gsk": f"STATUS#REVOKED#LEASE#{lease_id}",
        },
    )

    # Decrement active leases on entitlement
    _decrement_active_leases(lease["tenantId"], lease["appId"], lease["isvId"])

    # Push revocation via WebSocket
    _push_revocation(lease_id, reason)

    return {
        "statusCode": 204,
        "headers": {},
        "body": "",
    }


def _decrement_active_leases(tenant_id: str, app_id: str, isv_id: str):
    """Decrement the active lease counter on the entitlement."""
    pk = f"TENANT#{tenant_id}"
    sk = f"APP#{app_id}#ISV#{isv_id}"
    try:
        entitlements_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="SET activeLeases = activeLeases - :one",
            ConditionExpression="activeLeases > :zero",
            ExpressionAttributeValues={":one": 1, ":zero": 0},
        )
    except ClientError:
        pass  # Best effort


def _push_revocation(lease_id: str, reason: str):
    """Push revocation event to connected agents via WebSocket."""
    if not WS_API_ENDPOINT:
        return

    # Find connections subscribed to this lease
    try:
        resp = connections_table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": f"LEASE#{lease_id}"},
        )
    except ClientError:
        return

    if not resp.get("Items"):
        return

    # Push to each connection
    api_client = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=WS_API_ENDPOINT,
    )
    message = json.dumps({"event": "revoked", "leaseId": lease_id, "reason": reason})

    for item in resp["Items"]:
        conn_id = item["connectionId"]
        try:
            api_client.post_to_connection(
                ConnectionId=conn_id,
                Data=message.encode("utf-8"),
            )
        except ClientError:
            # Connection stale — clean up
            connections_table.delete_item(
                Key={"PK": f"CONN#{conn_id}", "SK": "META"}
            )


def _observability() -> dict:
    """GET /v1/admin/observability — Return current licensing posture."""
    # Get all entitlements
    ent_scan = entitlements_table.scan()
    entitlements = ent_scan.get("Items", [])

    # Get all leases
    lease_scan = leases_table.scan()
    all_leases = lease_scan.get("Items", [])

    overview = []
    for ent in entitlements:
        app_id = ent.get("appId", "")
        isv_id = ent.get("isvId", "")
        tenant_id = ent.get("tenantId", "")

        active_leases = [
            {
                "leaseId": l.get("leaseId", ""),
                "status": l.get("status", ""),
                "boundIdentity": l.get("boundIdentity", {}),
                "issuedAt": l.get("issuedAt", ""),
                "expiresAt": l.get("expiresAt", ""),
                "workId": l.get("workId", ""),
            }
            for l in all_leases
            if l.get("appId") == app_id
            and l.get("isvId") == isv_id
            and l.get("tenantId") == tenant_id
            and l.get("status") in ("ACTIVE", "RENEWED", "SHADOW")
        ]

        max_leases = int(ent.get("maxLeases", 0))
        active_count = int(ent.get("activeLeases", 0))
        overview.append({
            "appId": app_id,
            "isvId": isv_id,
            "tenantId": tenant_id,
            "dimensions": ent.get("dimensions", []),
            "maxLeases": max_leases,
            "activeLeases": active_count,
            "availableLeases": max_leases - active_count,
            "licenseModality": ent.get("licenseModality", ""),
            "policy": ent.get("policy", {}),
            "leases": active_leases,
        })

    # Recent activity
    activity = sorted(
        [l for l in all_leases],
        key=lambda x: x.get("issuedAt", ""),
        reverse=True,
    )[:20]

    recent = []
    for l in activity:
        entry = {
            "leaseId": l.get("leaseId", ""),
            "appId": l.get("appId", ""),
            "isvId": l.get("isvId", ""),
            "status": l.get("status", ""),
            "issuedAt": l.get("issuedAt", ""),
            "expiresAt": l.get("expiresAt", ""),
        }
        if l.get("revokedAt"):
            entry["revokedAt"] = l["revokedAt"]
            entry["revokeReason"] = l.get("revokeReason", "")
        recent.append(entry)

    total = len(all_leases)
    active = sum(1 for l in all_leases if l.get("status") in ("ACTIVE", "RENEWED"))

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": _to_json({
            "entitlements": overview,
            "recentActivity": recent,
            "totalLeases": total,
            "activeLeases": active,
        }),
    }


def _reset_all() -> dict:
    """Reset all leases and entitlement counters (demo-only endpoint)."""
    # Delete all leases
    deleted = 0
    scan = leases_table.scan()
    for item in scan.get("Items", []):
        leases_table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        deleted += 1

    # Reset all entitlement counters to 0
    ent_scan = entitlements_table.scan()
    for item in ent_scan.get("Items", []):
        entitlements_table.update_item(
            Key={"PK": item["PK"], "SK": item["SK"]},
            UpdateExpression="SET activeLeases = :zero",
            ExpressionAttributeValues={":zero": 0},
        )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": _to_json({"status": "reset", "leasesDeleted": deleted}),
    }


def _error(status: int, error_type: str, title: str, detail: str, **ext) -> dict:
    """Build RFC 9457 error response."""
    body = {
        "type": f"urn:dsl:error:{error_type}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    body.update(ext)
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/problem+json"},
        "body": _to_json(body),
    }
