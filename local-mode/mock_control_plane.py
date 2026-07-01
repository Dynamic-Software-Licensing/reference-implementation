"""
DSL Mock Control Plane — Local mode (no AWS required).

A single-file HTTP server implementing the same API as the AWS control plane.
Uses in-memory storage and a local RSA key for JWT signing.

Usage:
    pip install cryptography pyjwt
    python mock_control_plane.py

Then point the dashboard to http://localhost:3000
"""

import json
import time
import uuid
import base64
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

# ─── Cryptography (local RSA key) ────────────────────────────────────────────
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
import jwt as pyjwt

# Generate a local RSA key pair on startup
print("[Mock CP] Generating RSA-2048 signing key...")
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()
KEY_ID = f"local-key-{uuid.uuid4().hex[:8]}"
print(f"[Mock CP] Key ID: {KEY_ID}")

# ─── In-Memory Storage ────────────────────────────────────────────────────────
ENTITLEMENTS = {
    "tenant-broadcaster-1::app-encoder-pro::isv-acme": {
        "tenantId": "tenant-broadcaster-1",
        "appId": "app-encoder-pro",
        "isvId": "isv-acme",
        "dimensions": [
            {"name": "maxChannels", "maxQuantity": 4},
            {"name": "maxFps", "maxQuantity": 60},
        ],
        "maxLeases": 2,
        "activeLeases": 0,
        "licenseModality": "hourly",
        "policy": {
            "heartbeatSeconds": 30,
            "renewBeforeSeconds": 60,
            "offlineGraceSeconds": 300,
            "onGraceExhausted": "DRAIN",
        },
    },
    "tenant-broadcaster-1::app-multiviewer::isv-globex": {
        "tenantId": "tenant-broadcaster-1",
        "appId": "app-multiviewer",
        "isvId": "isv-globex",
        "dimensions": [
            {"name": "maxChannels", "maxQuantity": 10},
            {"name": "maxMosaics", "maxQuantity": 5},
        ],
        "maxLeases": 1,
        "activeLeases": 0,
        "licenseModality": "daily",
        "policy": {
            "heartbeatSeconds": 30,
            "renewBeforeSeconds": 60,
            "offlineGraceSeconds": 300,
            "onGraceExhausted": "DRAIN",
        },
    },
}

LEASES = {}  # leaseId -> lease record
USAGE_RECORDS = []  # list of usage events


# ─── Token Signing ────────────────────────────────────────────────────────────
def sign_token(claims: dict) -> str:
    """Sign a JWT using the local RSA private key.
    
    Note: The JWT payload contains only licensing metadata (dimensions, policy,
    binding identity) — no PII, secrets, or sensitive customer data.
    """
    return pyjwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": KEY_ID})


def get_jwks() -> dict:
    """Return the public key in JWKS format."""
    pub_numbers = PUBLIC_KEY.public_numbers()
    n_bytes = pub_numbers.n.to_bytes((pub_numbers.n.bit_length() + 7) // 8, 'big')
    e_bytes = pub_numbers.e.to_bytes((pub_numbers.e.bit_length() + 7) // 8, 'big')
    return {
        "keys": [{
            "kty": "RSA",
            "kid": KEY_ID,
            "use": "sig",
            "alg": "RS256",
            "n": base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode(),
            "e": base64.urlsafe_b64encode(e_bytes).rstrip(b"=").decode(),
        }]
    }


# ─── Identity Verification ────────────────────────────────────────────────────
def verify_identity(evidence: dict) -> bool:
    """Verify identity evidence structure (simplified for local mode)."""
    if not isinstance(evidence, dict):
        return False
    return any(k in evidence for k in ("aws", "kubernetes", "spiffe", "certificate", "type"))


def extract_binding(evidence: dict) -> dict:
    """Extract binding identity from evidence."""
    if "aws" in evidence:
        doc = evidence["aws"].get("iidDocument", {})
        role_arn = doc.get("assumedRoleArn", "")
        if role_arn:
            return {"type": "aws-role", "roleArn": role_arn, "region": doc.get("region", ""), "accountId": doc.get("accountId", "")}
        return {"type": "ec2-instance", "instanceId": doc.get("instanceId", "")}
    if "kubernetes" in evidence:
        k = evidence["kubernetes"]
        ns, sa = k.get("namespace", ""), k.get("serviceAccount", "")
        return {"type": "kubernetes-sa", "binding": f"system:serviceaccount:{ns}:{sa}", "namespace": ns, "serviceAccount": sa}
    if "spiffe" in evidence:
        s = evidence["spiffe"]
        return {"type": "spiffe", "spiffeId": s.get("spiffeId", ""), "trustDomain": s.get("trustDomain", "")}
    if "certificate" in evidence:
        c = evidence["certificate"]
        return {"type": "x509", "subjectDN": c.get("subjectDN", ""), "issuerDN": c.get("issuerDN", "")}
    return {"type": "unknown"}


def get_binding_key(b: dict) -> str:
    """Extract the primary binding identifier for comparison."""
    t = b.get("type", "")
    if t == "aws-role": return b.get("roleArn", "")
    if t == "ec2-instance": return b.get("instanceId", "")
    if t == "kubernetes-sa": return b.get("binding", "")
    if t == "spiffe": return b.get("spiffeId", "")
    if t == "x509": return b.get("subjectDN", "")
    return str(b)


# ─── API Handlers ─────────────────────────────────────────────────────────────
def handle_issue(body: dict) -> tuple:
    """POST /v1/leases — Issue a new lease."""
    tenant_id = body.get("tenantId", "")
    app_id = body.get("app", "")
    isv_id = body.get("isvId", "isv-acme")
    identity = body.get("identityEvidence")
    work_id = body.get("workId", "")

    if not all([tenant_id, app_id, identity]):
        return 400, problem("validation", "Missing Fields", "tenantId, app, and identityEvidence are required.")

    if not verify_identity(identity):
        return 403, problem("identity-verification-failed", "Identity Verification Failed", "Identity evidence format is invalid.")

    # Look up entitlement
    key = f"{tenant_id}::{app_id}::{isv_id}"
    ent = ENTITLEMENTS.get(key)
    if not ent:
        return 404, problem("entitlement-not-found", "Entitlement Not Found", f"No entitlement for {tenant_id}/{app_id}/{isv_id}")

    # Check quota
    if ent["activeLeases"] >= ent["maxLeases"]:
        return 429, problem("entitlement-exhausted", "Entitlement Exhausted",
                           "All lease slots are currently in use.",
                           category="quota", retryable=True, entitled=ent["maxLeases"], active=ent["activeLeases"])

    # Issue lease
    ent["activeLeases"] += 1
    lease_id = f"L-{uuid.uuid4().hex[:20]}"
    now = datetime.now(timezone.utc)
    policy = ent["policy"]
    ttl = int(policy.get("renewBeforeSeconds", 60)) * 3
    expires_at = now + timedelta(seconds=ttl)
    bound_identity = extract_binding(identity)

    claims = {
        "iss": "dsl-control-plane", "sub": tenant_id, "aud": app_id,
        "exp": int(expires_at.timestamp()), "nbf": int(now.timestamp()), "iat": int(now.timestamp()),
        "jti": str(uuid.uuid4()), "leaseId": lease_id, "tenantId": tenant_id, "appId": app_id,
        "dimensions": ent["dimensions"], "policy": policy, "boundIdentity": bound_identity,
    }
    token = sign_token(claims)

    lease = {
        "leaseId": lease_id, "tenantId": tenant_id, "appId": app_id, "isvId": isv_id,
        "status": "ACTIVE", "boundIdentity": bound_identity, "dimensions": ent["dimensions"],
        "policy": policy, "workId": work_id, "issuedAt": now.isoformat(), "expiresAt": expires_at.isoformat(),
    }
    LEASES[lease_id] = lease

    return 201, {
        "leaseId": lease_id, "app": app_id, "tenantId": tenant_id, "token": token,
        "issuedAt": now.isoformat(), "expiresAt": expires_at.isoformat(),
        "licenseModality": ent["licenseModality"], "dimensions": ent["dimensions"],
        "boundIdentity": bound_identity, "policy": policy,
    }


def handle_renew(lease_id: str, body: dict) -> tuple:
    """POST /v1/leases/{id}/renew — Renew a lease."""
    identity = body.get("identityEvidence")
    if not identity:
        return 400, problem("validation", "Missing Identity Evidence", "identityEvidence is required.")

    lease = LEASES.get(lease_id)
    if not lease:
        return 404, problem("lease-not-found", "Lease Not Found", f"Lease {lease_id} does not exist.")
    if lease["status"] == "REVOKED":
        return 409, problem("lease-revoked", "Lease Revoked", f"Lease {lease_id} has been revoked.")
    if lease["status"] not in ("ACTIVE", "RENEWED"):
        return 409, problem("lease-not-active", "Lease Not Active", f"Lease is in state {lease['status']}.")

    # Verify identity
    new_binding = extract_binding(identity)
    if get_binding_key(new_binding) != get_binding_key(lease["boundIdentity"]):
        return 403, problem("identity-mismatch", "Identity Mismatch",
                           f"Expected: {get_binding_key(lease['boundIdentity'])}, Got: {get_binding_key(new_binding)}")

    # Extend
    now = datetime.now(timezone.utc)
    ttl = int(lease["policy"].get("renewBeforeSeconds", 60)) * 3
    expires_at = now + timedelta(seconds=ttl)
    lease["status"] = "RENEWED"
    lease["expiresAt"] = expires_at.isoformat()

    claims = {
        "iss": "dsl-control-plane", "sub": lease["tenantId"], "aud": lease["appId"],
        "exp": int(expires_at.timestamp()), "nbf": int(now.timestamp()), "iat": int(now.timestamp()),
        "jti": str(uuid.uuid4()), "leaseId": lease_id, "tenantId": lease["tenantId"], "appId": lease["appId"],
        "dimensions": lease["dimensions"], "policy": lease["policy"], "boundIdentity": lease["boundIdentity"],
    }
    token = sign_token(claims)

    return 200, {"leaseId": lease_id, "token": token, "expiresAt": expires_at.isoformat()}


def handle_reissue(lease_id: str, body: dict) -> tuple:
    """POST /v1/leases/{id}/reissue — Create shadow lease."""
    to_identity = body.get("toIdentityEvidence")
    to_work_id = body.get("toWorkId", "")
    if not to_identity:
        return 400, problem("validation", "Missing Fields", "toIdentityEvidence is required.")

    lease = LEASES.get(lease_id)
    if not lease:
        return 404, problem("lease-not-found", "Lease Not Found", f"Lease {lease_id} does not exist.")
    if lease["status"] not in ("ACTIVE", "RENEWED"):
        return 409, problem("lease-not-active", "Lease Not Active", f"Lease is in state {lease['status']}.")

    # Create shadow
    shadow_id = f"L-{uuid.uuid4().hex[:20]}"
    cutover_token = f"ct-{uuid.uuid4().hex[:16]}"
    reissue_id = f"M-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    ttl = int(lease["policy"].get("renewBeforeSeconds", 60)) * 3
    expires_at = now + timedelta(seconds=ttl)
    new_binding = extract_binding(to_identity)

    shadow = {
        "leaseId": shadow_id, "tenantId": lease["tenantId"], "appId": lease["appId"], "isvId": lease["isvId"],
        "status": "SHADOW", "boundIdentity": new_binding, "dimensions": lease["dimensions"],
        "policy": lease["policy"], "workId": to_work_id, "issuedAt": now.isoformat(), "expiresAt": expires_at.isoformat(),
        "reissueId": reissue_id, "cutoverToken": cutover_token, "originalLeaseId": lease_id,
    }
    LEASES[shadow_id] = shadow

    claims = {
        "iss": "dsl-control-plane", "sub": lease["tenantId"], "aud": lease["appId"],
        "exp": int(expires_at.timestamp()), "nbf": int(now.timestamp()), "iat": int(now.timestamp()),
        "jti": str(uuid.uuid4()), "leaseId": shadow_id, "tenantId": lease["tenantId"], "appId": lease["appId"],
        "dimensions": lease["dimensions"], "policy": lease["policy"], "boundIdentity": new_binding,
    }
    token = sign_token(claims)

    return 200, {
        "reissueId": reissue_id, "cutoverToken": cutover_token,
        "toLease": {"leaseId": shadow_id, "token": token, "expiresAt": expires_at.isoformat(),
                    "dimensions": lease["dimensions"], "policy": lease["policy"]},
    }


def handle_finalize_reissue(lease_id: str, body: dict) -> tuple:
    """POST /v1/leases/{id}/finalizeReissue — Activate shadow, revoke original."""
    reissue_id = body.get("reissueId")
    cutover_token = body.get("cutoverToken")
    if not reissue_id or not cutover_token:
        return 400, problem("validation", "Missing Fields", "reissueId and cutoverToken are required.")

    # Find the shadow
    shadow = None
    for l in LEASES.values():
        if l.get("reissueId") == reissue_id and l.get("cutoverToken") == cutover_token:
            shadow = l
            break
    if not shadow:
        return 401, problem("cutover-token-invalid", "Cutover Token Invalid", "Cutover token does not match.")

    # Activate shadow, revoke original
    shadow["status"] = "ACTIVE"
    original = LEASES.get(lease_id)
    if original:
        original["status"] = "REVOKED"
        original["revokedAt"] = datetime.now(timezone.utc).isoformat()
        # Decrement quota (shadow doesn't add to quota since it replaces)
    
    return 200, {"state": "COMPLETED", "revoked": lease_id}


def handle_revoke(lease_id: str, body: dict) -> tuple:
    """DELETE /v1/leases/{id} — Revoke a lease."""
    reason = body.get("reason", "admin_action")
    lease = LEASES.get(lease_id)
    if not lease:
        return 404, problem("lease-not-found", "Lease Not Found", f"Lease {lease_id} does not exist.")
    if lease["status"] == "REVOKED":
        return 409, problem("lease-already-revoked", "Lease Already Revoked", f"Lease {lease_id} already revoked.")

    lease["status"] = "REVOKED"
    lease["revokedAt"] = datetime.now(timezone.utc).isoformat()
    lease["revokeReason"] = reason

    # Decrement active leases
    key = f"{lease['tenantId']}::{lease['appId']}::{lease['isvId']}"
    ent = ENTITLEMENTS.get(key)
    if ent and ent["activeLeases"] > 0:
        ent["activeLeases"] -= 1

    return 204, None


def handle_usage(body: dict) -> tuple:
    """POST /v1/usage-records — Record usage."""
    required = ["leaseId", "tenantId", "productId", "dimension", "quantity", "granularity", "timestamp", "workId"]
    missing = [f for f in required if f not in body]
    if missing:
        return 400, problem("validation", "Missing Fields", f"Required: {', '.join(missing)}")
    USAGE_RECORDS.append(body)
    return 200, {"status": "accepted"}


def handle_reset() -> tuple:
    """POST /v1/admin/reset — Flush all state."""
    LEASES.clear()
    USAGE_RECORDS.clear()
    for ent in ENTITLEMENTS.values():
        ent["activeLeases"] = 0
    return 200, {"status": "reset", "leasesDeleted": "all"}


def handle_observability() -> tuple:
    """GET /v1/admin/observability — Return current licensing posture."""
    overview = []
    for key, ent in ENTITLEMENTS.items():
        # Find active leases for this entitlement
        active_leases = [
            {
                "leaseId": l["leaseId"],
                "status": l["status"],
                "boundIdentity": l.get("boundIdentity", {}),
                "issuedAt": l.get("issuedAt", ""),
                "expiresAt": l.get("expiresAt", ""),
                "workId": l.get("workId", ""),
            }
            for l in LEASES.values()
            if l.get("appId") == ent["appId"]
            and l.get("isvId") == ent["isvId"]
            and l.get("tenantId") == ent["tenantId"]
            and l.get("status") in ("ACTIVE", "RENEWED", "SHADOW")
        ]

        overview.append({
            "appId": ent["appId"],
            "isvId": ent["isvId"],
            "tenantId": ent["tenantId"],
            "dimensions": ent["dimensions"],
            "maxLeases": ent["maxLeases"],
            "activeLeases": ent["activeLeases"],
            "availableLeases": ent["maxLeases"] - ent["activeLeases"],
            "licenseModality": ent["licenseModality"],
            "policy": ent["policy"],
            "leases": active_leases,
        })

    # Recent activity from lease history
    activity = []
    for l in sorted(LEASES.values(), key=lambda x: x.get("issuedAt", ""), reverse=True)[:20]:
        entry = {
            "leaseId": l["leaseId"],
            "appId": l["appId"],
            "isvId": l["isvId"],
            "status": l["status"],
            "issuedAt": l.get("issuedAt", ""),
            "expiresAt": l.get("expiresAt", ""),
        }
        if l.get("revokedAt"):
            entry["revokedAt"] = l["revokedAt"]
            entry["revokeReason"] = l.get("revokeReason", "")
        activity.append(entry)

    return 200, {
        "entitlements": overview,
        "recentActivity": activity,
        "totalLeases": len(LEASES),
        "activeLeases": sum(1 for l in LEASES.values() if l["status"] in ("ACTIVE", "RENEWED")),
        "usageRecords": len(USAGE_RECORDS),
    }


def problem(error_type: str, title: str, detail: str, **ext) -> dict:
    """Build RFC 9457 problem response."""
    return {"type": f"urn:dsl:error:{error_type}", "title": title, "detail": detail, **ext}


# ─── HTTP Server ──────────────────────────────────────────────────────────────
class DSLHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._cors_response(204)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/.well-known/jwks.json":
            self._json_response(200, get_jwks())
        elif path == "/v1/admin/observability":
            status, data = handle_observability()
            self._json_response(status, data)
        else:
            self._json_response(404, problem("not-found", "Not Found", f"No handler for GET {path}"))

    def do_POST(self):
        body = self._read_body()
        path = urlparse(self.path).path

        if path == "/v1/leases":
            status, data = handle_issue(body)
        elif path.endswith("/renew"):
            lease_id = path.split("/v1/leases/")[1].split("/")[0]
            status, data = handle_renew(lease_id, body)
        elif path.endswith("/reissue") and not path.endswith("/finalizeReissue"):
            lease_id = path.split("/v1/leases/")[1].split("/")[0]
            status, data = handle_reissue(lease_id, body)
        elif path.endswith("/finalizeReissue"):
            lease_id = path.split("/v1/leases/")[1].split("/")[0]
            status, data = handle_finalize_reissue(lease_id, body)
        elif path == "/v1/usage-records":
            status, data = handle_usage(body)
        elif path == "/v1/admin/reset":
            status, data = handle_reset()
        else:
            status, data = 404, problem("not-found", "Not Found", f"No handler for POST {path}")

        self._json_response(status, data)

    def do_DELETE(self):
        body = self._read_body()
        path = urlparse(self.path).path

        if "/v1/leases/" in path:
            lease_id = path.split("/v1/leases/")[1].split("/")[0]
            status, data = handle_revoke(lease_id, body)
            self._json_response(status, data)
        else:
            self._json_response(404, problem("not-found", "Not Found", f"No handler for DELETE {path}"))

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            try:
                return json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                return {}
        return {}

    def _json_response(self, status: int, data):
        self._cors_response(status)
        if data is not None:
            body = json.dumps(data).encode()
            self.wfile.write(body)

    def _cors_response(self, status: int):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[Mock CP] {args[0]}")


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    server = HTTPServer(("127.0.0.1", PORT), DSLHandler)
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  DSL Mock Control Plane — Local Mode                        ║
║                                                              ║
║  REST API:  http://localhost:{PORT}                            ║
║  JWKS:      http://localhost:{PORT}/.well-known/jwks.json      ║
║  Key ID:    {KEY_ID}                          ║
║                                                              ║
║  Entitlements loaded:                                        ║
║    - Encoder (app-encoder-pro): 4ch, 60fps, 2 leases        ║
║    - Multiviewer (app-multiviewer): 10ch, 5 mosaics, 1 lease║
║                                                              ║
║  Open the dashboard and set Control Plane URL to:            ║
║  http://localhost:{PORT}                                       ║
╚══════════════════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Mock CP] Shutting down.")
        server.shutdown()
