"""Usage record handler — accepts and stores metered usage events."""

import json
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


dynamodb = boto3.resource("dynamodb")
usage_table = dynamodb.Table(os.environ["USAGE_TABLE"])


def lambda_handler(event, context):
    """Handle POST /v1/usage-records."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return _error(400, "validation", "Invalid JSON", "Request body is not valid JSON.")

    # Validate required fields
    required = ["leaseId", "tenantId", "productId", "dimension", "quantity", "granularity", "timestamp", "workId"]
    missing = [f for f in required if f not in body]
    if missing:
        return _error(
            400, "validation", "Missing Fields",
            f"Required fields missing: {', '.join(missing)}",
        )

    # Build record
    lease_id = body["leaseId"]
    timestamp = body["timestamp"]
    dimension = body["dimension"]

    item = {
        "PK": f"LEASE#{lease_id}",
        "SK": f"TS#{timestamp}#DIM#{dimension}",
        "tenantId": body["tenantId"],
        "isvId": body.get("isvId", ""),
        "productId": body["productId"],
        "dimension": dimension,
        "quantity": body["quantity"],
        "granularity": body["granularity"],
        "workId": body["workId"],
        "submittedAt": datetime.now(timezone.utc).isoformat(),
    }

    # Idempotent write — conditional put (only if not already exists)
    try:
        usage_table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Duplicate — silently accept (idempotent)
            pass
        else:
            raise

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"status": "accepted"}),
    }


def _error(status: int, category: str, title: str, detail: str) -> dict:
    """Return RFC 9457 problem+json error."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/problem+json"},
        "body": json.dumps({
            "type": f"urn:dsl:error:{category}",
            "title": title,
            "status": status,
            "detail": detail,
            "category": category,
            "retryable": False,
        }),
    }
