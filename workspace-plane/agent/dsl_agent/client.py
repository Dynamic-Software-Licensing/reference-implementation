"""HTTP client for the DSL Control Plane REST API."""

import uuid
from typing import Optional

import httpx

from .config import AgentConfig


class ControlPlaneClient:
    """Synchronous HTTP client for control plane API calls."""

    def __init__(self, config: AgentConfig):
        self._base_url = config.api_url.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            "X-Tenant-Id": config.tenant_id,
        }
        if config.api_key:
            self._headers["X-Api-Key"] = config.api_key

    def _trace_headers(self) -> dict:
        """Generate W3C Trace Context headers."""
        trace_id = uuid.uuid4().hex
        parent_id = uuid.uuid4().hex[:16]
        return {"traceparent": f"00-{trace_id}-{parent_id}-01"}

    def issue_lease(
        self,
        tenant_id: str,
        app_id: str,
        isv_id: str,
        identity_evidence: dict,
        work_id: str,
        dimensions: Optional[list] = None,
    ) -> dict:
        """Request a new lease (POST /v1/leases)."""
        body = {
            "app": app_id,
            "tenantId": tenant_id,
            "isvId": isv_id,
            "identityEvidence": identity_evidence,
            "workId": work_id,
        }
        if dimensions:
            body["dimensions"] = dimensions

        response = httpx.post(
            f"{self._base_url}/v1/leases",
            json=body,
            headers={**self._headers, **self._trace_headers()},
            timeout=15,
        )
        return self._handle_response(response)

    def renew_lease(self, lease_id: str, identity_evidence: dict, work_id: str = "") -> dict:
        """Renew an active lease (POST /v1/leases/{leaseId}/renew)."""
        body = {"identityEvidence": identity_evidence}
        if work_id:
            body["workId"] = work_id

        response = httpx.post(
            f"{self._base_url}/v1/leases/{lease_id}/renew",
            json=body,
            headers={**self._headers, **self._trace_headers()},
            timeout=15,
        )
        return self._handle_response(response)

    def reissue_lease(self, lease_id: str, to_identity_evidence: dict, to_work_id: str) -> dict:
        """Start a reissue (POST /v1/leases/{leaseId}/reissue)."""
        body = {
            "toIdentityEvidence": to_identity_evidence,
            "toWorkId": to_work_id,
        }
        response = httpx.post(
            f"{self._base_url}/v1/leases/{lease_id}/reissue",
            json=body,
            headers={**self._headers, **self._trace_headers()},
            timeout=15,
        )
        return self._handle_response(response)

    def finalize_reissue(self, lease_id: str, reissue_id: str, cutover_token: str) -> dict:
        """Finalize a reissue (POST /v1/leases/{leaseId}/finalizeReissue)."""
        body = {
            "reissueId": reissue_id,
            "cutoverToken": cutover_token,
        }
        response = httpx.post(
            f"{self._base_url}/v1/leases/{lease_id}/finalizeReissue",
            json=body,
            headers={**self._headers, **self._trace_headers()},
            timeout=15,
        )
        return self._handle_response(response)

    def revoke_lease(self, lease_id: str, reason: str = "admin_action") -> dict:
        """Revoke a lease (DELETE /v1/leases/{leaseId})."""
        response = httpx.request(
            "DELETE",
            f"{self._base_url}/v1/leases/{lease_id}",
            json={"reason": reason},
            headers={**self._headers, **self._trace_headers()},
            timeout=15,
        )
        if response.status_code == 204:
            return {"status": "revoked"}
        return self._handle_response(response)

    def submit_usage(self, records: list[dict]) -> list[dict]:
        """Submit usage records (POST /v1/usage-records)."""
        results = []
        for record in records:
            response = httpx.post(
                f"{self._base_url}/v1/usage-records",
                json=record,
                headers={**self._headers, **self._trace_headers()},
                timeout=10,
            )
            results.append(self._handle_response(response))
        return results

    def _handle_response(self, response: httpx.Response) -> dict:
        """Parse response and raise on errors."""
        if response.status_code >= 400:
            try:
                error_body = response.json()
            except Exception:
                error_body = {"detail": response.text}
            raise ControlPlaneError(
                status_code=response.status_code,
                error_type=error_body.get("type", "unknown"),
                title=error_body.get("title", "Error"),
                detail=error_body.get("detail", "Unknown error"),
                body=error_body,
            )
        if response.status_code == 204:
            return {}
        return response.json()


class ControlPlaneError(Exception):
    """Raised when the control plane returns an error response."""

    def __init__(self, status_code: int, error_type: str, title: str, detail: str, body: dict):
        super().__init__(f"[{status_code}] {title}: {detail}")
        self.status_code = status_code
        self.error_type = error_type
        self.title = title
        self.detail = detail
        self.body = body

    @property
    def retryable(self) -> bool:
        return self.body.get("retryable", False)
