"""Submit an authenticated event and verify durable worker completion."""

from __future__ import annotations

import json
import secrets
import time
import urllib.request
from pathlib import Path
from typing import Any

from platform_agent_orchestrator.security import webhook_signature

BASE_URL = "http://127.0.0.1:8080"
KEY_ID = "sample-sre-alert-agent"
SCOPE_ID = "sock-shop-sample"
WORKFLOW = "alert"
TERMINAL_STATUSES = frozenset(
    {
        "succeeded",
        "rejected",
        "failed_terminal",
        "dead_lettered",
        "quarantined",
    }
)


def _signed_headers(*, secret: str, method: str, path: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    return {
        "Content-Type": "application/json",
        "X-Webhook-Key-Id": KEY_ID,
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Nonce": nonce,
        "X-Webhook-Signature": webhook_signature(
            secret=secret,
            key_id=KEY_ID,
            timestamp=timestamp,
            nonce=nonce,
            method=method,
            path=path,
            workflow=WORKFLOW,
            scope_id=SCOPE_ID,
            body=body,
        ),
        "X-Workflow": WORKFLOW,
        "X-Team-Scope": SCOPE_ID,
    }


def _request_json(
    *,
    base_url: str,
    secret: str,
    method: str,
    path: str,
    body: bytes = b"",
) -> dict[str, Any]:
    headers = _signed_headers(secret=secret, method=method, path=path, body=body)
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body if method == "POST" else None,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status not in {200, 202}:
            raise RuntimeError(f"smoke request returned HTTP {response.status}")
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise RuntimeError("smoke request returned a non-object response")
    return payload


def submit_event(*, base_url: str, secret: str) -> str:
    path = "/v1/events"
    body = json.dumps(
        {
            "schema_version": "1",
            "type": "monitoring.alert.received",
            "source": KEY_ID,
            "subject": "orders-high-errors",
            "idempotency_key": f"sample:compose-smoke:{secrets.token_hex(12)}",
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
    payload = _request_json(
        base_url=base_url,
        secret=secret,
        method="POST",
        path=path,
        body=body,
    )
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError("event admission response did not contain a run ID")
    return run_id


def wait_for_success(
    *,
    base_url: str,
    secret: str,
    run_id: str,
    timeout_seconds: float = 45,
    poll_interval_seconds: float = 0.25,
) -> None:
    path = f"/v1/runs/{run_id}"
    deadline = time.monotonic() + timeout_seconds
    last_status = "unknown"
    while time.monotonic() < deadline:
        payload = _request_json(
            base_url=base_url,
            secret=secret,
            method="GET",
            path=path,
        )
        status = payload.get("status")
        if not isinstance(status, str):
            raise RuntimeError("run response did not contain a status")
        last_status = status
        if status == "succeeded":
            return
        if status in TERMINAL_STATUSES:
            raise RuntimeError(f"smoke run reached terminal status {status!r}")
        time.sleep(poll_interval_seconds)
    raise TimeoutError(
        f"smoke run did not complete within {timeout_seconds:g}s; last status {last_status!r}"
    )


def main() -> None:
    secret = Path(".local-secrets/webhook_signing_secret").read_text().strip()
    run_id = submit_event(base_url=BASE_URL, secret=secret)
    wait_for_success(base_url=BASE_URL, secret=secret, run_id=run_id)
    print(f"smoke run {run_id} succeeded")


if __name__ == "__main__":
    main()
