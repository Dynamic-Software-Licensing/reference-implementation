"""CLI entry point for the DSL License Agent."""

import time
import uuid
import click

from .config import AgentConfig
from .identity import collect_identity
from .client import ControlPlaneClient, ControlPlaneError
from .state import AgentStateMachine, AgentState
from .renewal import RenewalScheduler
from .grace import GracePeriodManager
from .usage import UsageBuffer
from .dashboard_ws import DashboardServer


@click.group()
@click.pass_context
def cli(ctx):
    """DSL License Agent — Reference Implementation."""
    ctx.ensure_object(dict)
    config = AgentConfig.from_env()
    ctx.obj["config"] = config


@cli.command()
@click.pass_context
def start(ctx):
    """Start the license agent (normal flow: issue → renew loop)."""
    config: AgentConfig = ctx.obj["config"]

    if not config.api_url:
        click.echo("ERROR: DSL_API_URL environment variable is required.")
        click.echo("  export DSL_API_URL=https://your-api-id.execute-api.us-east-1.amazonaws.com")
        raise SystemExit(1)

    click.echo(f"[Agent] Starting DSL License Agent")
    click.echo(f"  API URL:  {config.api_url}")
    click.echo(f"  Tenant:   {config.tenant_id}")
    click.echo(f"  App:      {config.app_id}")
    click.echo(f"  ISV:      {config.isv_id}")
    click.echo(f"  Identity: {config.identity_mode}")
    click.echo()

    # Initialize components
    client = ControlPlaneClient(config)
    state_machine = AgentStateMachine()
    dashboard = DashboardServer(port=config.dashboard_port)
    dashboard.start()
    click.echo(f"[Dashboard] WebSocket server started on ws://localhost:{config.dashboard_port}")

    # Wire state machine events to dashboard
    state_machine.on_event(lambda event_type, data: dashboard.emit(event_type, data))

    # Collect identity evidence
    state_machine.transition(AgentState.REQUESTING, "Collecting identity and requesting lease")
    identity = collect_identity(config.identity_mode)
    dashboard.emit("identity_collected", {"identity": identity, "mode": config.identity_mode})
    click.echo(f"[Agent] Identity collected ({config.identity_mode}): {identity.get('type', 'unknown')}")

    # Issue lease
    work_id = f"deploy-{uuid.uuid4().hex[:12]}"
    try:
        result = client.issue_lease(
            tenant_id=config.tenant_id,
            app_id=config.app_id,
            isv_id=config.isv_id,
            identity_evidence=identity,
            work_id=work_id,
        )
    except ControlPlaneError as e:
        click.echo(f"[Agent] Lease issuance FAILED: {e.title} — {e.detail}")
        dashboard.emit("error", {"error": e.body})
        state_machine.transition(AgentState.STOPPED, f"Issuance failed: {e.title}")
        raise SystemExit(1)

    lease_id = result["leaseId"]
    token = result["token"]
    expires_at = result["expiresAt"]
    policy = result.get("policy", {})

    state_machine.transition(AgentState.ACTIVE, "Lease issued successfully")
    dashboard.emit("lease_issued", result)
    dashboard.emit("token_decoded", {"token": token, "leaseId": lease_id})

    click.echo(f"[Agent] Lease issued: {lease_id}")
    click.echo(f"  Expires: {expires_at}")
    click.echo(f"  Dimensions: {result.get('dimensions', [])}")
    click.echo()

    # Grace period manager
    grace_seconds = policy.get("offlineGraceSeconds", 300)
    grace = GracePeriodManager(
        grace_seconds=grace_seconds,
        on_tick=lambda remaining: dashboard.emit("grace_tick", {"remaining": remaining}),
        on_exhausted=lambda: _handle_exhausted(state_machine, dashboard, policy),
    )

    # Renewal function
    def do_renew() -> bool:
        nonlocal token, expires_at
        state_machine.transition(AgentState.RENEWING, "Renewal attempt")
        try:
            result = client.renew_lease(lease_id, identity, work_id)
            token = result["token"]
            expires_at = result["expiresAt"]

            if grace.is_active:
                grace.cancel()
                dashboard.emit("grace_exit", {"leaseId": lease_id})

            state_machine.transition(AgentState.ACTIVE, "Renewal succeeded")
            dashboard.emit("renewed", {"leaseId": lease_id, "expiresAt": expires_at})
            dashboard.emit("token_decoded", {"token": token, "leaseId": lease_id})
            click.echo(f"[Agent] Renewed — expires: {expires_at}")

            # Reschedule
            scheduler.schedule(expires_at)
            return True
        except ControlPlaneError as e:
            click.echo(f"[Agent] Renewal failed: {e.title}")
            dashboard.emit("error", {"error": e.body, "context": "renewal"})

            # If not retryable (revoked, identity mismatch), enter draining
            if not e.retryable:
                state_machine.transition(AgentState.DRAINING, f"Non-retryable: {e.title}")
                return True  # Stop retrying

            # Enter grace if not already
            if not grace.is_active and state_machine.state != AgentState.GRACE:
                state_machine.transition(AgentState.GRACE, "Renewal failed, entering grace")
                dashboard.emit("grace_enter", {"graceSeconds": grace_seconds, "leaseId": lease_id})
                grace.start()

            return False

    # Start renewal scheduler
    renew_before = policy.get("renewBeforeSeconds", 60)
    scheduler = RenewalScheduler(
        renew_before_seconds=renew_before,
        on_renew=do_renew,
        on_failure=lambda msg: click.echo(f"[Agent] Renewal error: {msg}"),
    )
    scheduler.schedule(expires_at)
    click.echo(f"[Agent] Renewal scheduled ({renew_before}s before expiry)")

    # Usage buffer
    usage = UsageBuffer(
        client,
        flush_interval=30,
        on_submitted=lambda records: dashboard.emit("usage_submitted", {"records": records}),
    )
    usage.start()

    # Main loop — keep alive
    click.echo("[Agent] Running. Press Ctrl+C to stop.")
    click.echo()
    try:
        while state_machine.state not in (AgentState.STOPPED, AgentState.EXHAUSTED):
            time.sleep(1)

            # Simulate usage every 10 seconds
            if state_machine.state in (AgentState.ACTIVE, AgentState.RENEWING, AgentState.GRACE):
                if int(time.time()) % 10 == 0:
                    usage.record(
                        lease_id=lease_id,
                        tenant_id=config.tenant_id,
                        product_id=config.app_id,
                        dimension="CHANNELS",
                        quantity=1,
                        work_id=work_id,
                    )
    except KeyboardInterrupt:
        click.echo("\n[Agent] Shutting down...")
    finally:
        scheduler.stop()
        usage.stop()


@cli.command()
@click.option("--lease-id", required=True, help="Lease ID to revoke")
@click.pass_context
def revoke(ctx, lease_id):
    """Revoke a lease (admin action)."""
    config: AgentConfig = ctx.obj["config"]
    client = ControlPlaneClient(config)
    try:
        client.revoke_lease(lease_id, reason="admin_action")
        click.echo(f"[Agent] Lease {lease_id} revoked.")
    except ControlPlaneError as e:
        click.echo(f"[Agent] Revocation failed: {e.title} — {e.detail}")


@cli.command()
@click.pass_context
def disconnect(ctx):
    """Simulate network disconnection (for grace period demo)."""
    click.echo("[Agent] Simulating network disconnection...")
    click.echo("  (In the real system, renewal would fail and grace period would begin)")
    click.echo("  Use 'dsl-agent start' with DSL_API_URL set to an unreachable host to simulate.")


def _handle_exhausted(state_machine: AgentStateMachine, dashboard: DashboardServer, policy: dict):
    """Handle grace period exhaustion."""
    action = policy.get("onGraceExhausted", "DRAIN")
    state_machine.transition(AgentState.EXHAUSTED, f"Grace exhausted — action: {action}")
    dashboard.emit("exhausted", {"action": action})


if __name__ == "__main__":
    cli()
