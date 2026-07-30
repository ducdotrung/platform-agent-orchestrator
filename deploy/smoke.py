"""Submit one authenticated synthetic Sock Shop event to the local API."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from platform_agent_orchestrator.security import webhook_signature


def main() -> None:
    path = "/v1/events"
    body = json.dumps(
        {
            "schema_version": "1",
            "type": "alert.received",
            "source": "sample-sre-alert-agent",
            "subject": "orders-high-errors",
            "idempotency_key": f"sample:compose-smoke:{int(time.time())}",
            "payload": {
                "alert_id": "orders-high-errors",
                "title": "Synthetic orders error rate",
                "service": "orders",
                "severity": "critical",
                "environment": "sample",
                "count": 42,
                "users": 7,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    timestamp = str(int(time.time()))
    nonce = secrets_nonce()
    secret = Path(".local-secrets/webhook_signing_secret").read_text().strip()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Key-Id": "sample-sre-alert-agent",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Nonce": nonce,
        "X-Webhook-Signature": webhook_signature(
            secret=secret,
            key_id="sample-sre-alert-agent",
            timestamp=timestamp,
            nonce=nonce,
            method="POST",
            path=path,
            workflow="alert",
            scope_id="sock-shop-sample",
            body=body,
        ),
        "X-Workflow": "alert",
        "X-Team-Scope": "sock-shop-sample",
    }
    request = urllib.request.Request(f"http://127.0.0.1:8080{path}", body, headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status not in {200, 202}:
            raise RuntimeError(f"smoke request returned {response.status}")


def secrets_nonce() -> str:
    import secrets

    return secrets.token_urlsafe(24)


if __name__ == "__main__":
    main()
