"""Agent configuration — loads from environment variables or config file."""

import os
from dataclasses import dataclass


@dataclass
class AgentConfig:
    """Configuration for the DSL License Agent."""

    # Control plane endpoints
    api_url: str = ""
    ws_url: str = ""
    jwks_url: str = ""

    # Tenant and application
    tenant_id: str = "tenant-broadcaster-1"
    app_id: str = "app-encoder-pro"
    isv_id: str = "isv-acme"

    # Identity mode
    identity_mode: str = "ec2"  # "ec2" or "kubernetes"

    # Dashboard WebSocket
    dashboard_port: int = 8765

    # API key (simplified auth for demo)
    api_key: str = ""

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Load configuration from environment variables."""
        api_url = os.environ.get("DSL_API_URL", "")
        return cls(
            api_url=api_url,
            ws_url=os.environ.get("DSL_WS_URL", ""),
            jwks_url=os.environ.get("DSL_JWKS_URL", f"{api_url}/.well-known/jwks.json" if api_url else ""),
            tenant_id=os.environ.get("DSL_TENANT_ID", "tenant-broadcaster-1"),
            app_id=os.environ.get("DSL_APP_ID", "app-encoder-pro"),
            isv_id=os.environ.get("DSL_ISV_ID", "isv-acme"),
            identity_mode=os.environ.get("DSL_IDENTITY_MODE", "ec2"),
            dashboard_port=int(os.environ.get("DSL_DASHBOARD_PORT", "8765")),
            api_key=os.environ.get("DSL_API_KEY", ""),
        )
