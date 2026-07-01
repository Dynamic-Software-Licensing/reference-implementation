"""WebSocket connection handler for revocation push channel."""

import json
import os
from datetime import datetime, timezone

import boto3


dynamodb = boto3.resource("dynamodb")
connections_table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])


def lambda_handler(event, context):
    """Handle WebSocket $connect, $disconnect, and $default routes."""
    route_key = event.get("requestContext", {}).get("routeKey")
    connection_id = event.get("requestContext", {}).get("connectionId")

    if route_key == "$connect":
        return _handle_connect(event, connection_id)
    elif route_key == "$disconnect":
        return _handle_disconnect(connection_id)
    elif route_key == "$default":
        return _handle_message(event, connection_id)

    return {"statusCode": 400}


def _handle_connect(event, connection_id: str) -> dict:
    """Register a new WebSocket connection."""
    # Extract tenant from query string (simplified auth for demo)
    query_params = event.get("queryStringParameters") or {}
    tenant_id = query_params.get("tenantId", "unknown")

    connections_table.put_item(
        Item={
            "PK": f"CONN#{connection_id}",
            "SK": "META",
            "connectionId": connection_id,
            "tenantId": tenant_id,
            "leaseId": "",
            "connectedAt": datetime.now(timezone.utc).isoformat(),
            "GSI1PK": "UNSUBSCRIBED",
            "GSI1SK": f"CONN#{connection_id}",
        }
    )
    return {"statusCode": 200}


def _handle_disconnect(connection_id: str) -> dict:
    """Remove a WebSocket connection record."""
    connections_table.delete_item(
        Key={"PK": f"CONN#{connection_id}", "SK": "META"}
    )
    return {"statusCode": 200}


def _handle_message(event, connection_id: str) -> dict:
    """Handle subscription messages from the agent."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return {"statusCode": 400}

    action = body.get("action")

    if action == "subscribe" and "leaseId" in body:
        lease_id = body["leaseId"]
        connections_table.update_item(
            Key={"PK": f"CONN#{connection_id}", "SK": "META"},
            UpdateExpression="SET leaseId = :lid, GSI1PK = :gpk, GSI1SK = :gsk",
            ExpressionAttributeValues={
                ":lid": lease_id,
                ":gpk": f"LEASE#{lease_id}",
                ":gsk": f"CONN#{connection_id}",
            },
        )
        return {"statusCode": 200}

    return {"statusCode": 200}
