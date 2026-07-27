"""PII and credential masking applied before telemetry leaves the process."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"
MAX_STRING_LENGTH = 2_048
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "secret",
    "secret_key",
    "token",
}

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), f"Bearer {REDACTED}"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), REDACTED),
    (re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*([:=])\s*"
            r"([^\s,;]+)"
        ),
        rf"\1\2{REDACTED}",
    ),
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        REDACTED,
    ),
)

_CONTENT_ATTRIBUTE_MARKERS = (
    "langfuse.observation.input",
    "langfuse.observation.output",
    "gen_ai.prompt",
    "gen_ai.completion",
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "message.content",
    "tool.arguments",
    "tool.result",
)


def redact_text(value: str) -> str:
    masked = value
    for pattern, replacement in _PATTERNS:
        masked = pattern.sub(replacement, masked)
    if len(masked) > MAX_STRING_LENGTH:
        return f"{masked[:MAX_STRING_LENGTH]}...[TRUNCATED]"
    return masked


def redact_value(value: Any, *, key: str | None = None) -> Any:
    normalized_key_parts = re.split(r"[.\[\]/:]", key.lower().replace("-", "_")) if key else []
    if any(part in SENSITIVE_KEYS for part in normalized_key_parts):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {item_key: redact_value(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def is_content_attribute(name: str) -> bool:
    normalized = name.lower()
    return any(marker in normalized for marker in _CONTENT_ATTRIBUTE_MARKERS)


def build_otel_masker(*, capture_content: bool):
    """Build Langfuse v4's batch masker while keeping Langfuse optional."""

    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    def mask_otel_spans(*, params):
        patches: dict[str, Any] = {}
        for identifier, span in params.spans.items():
            deleted: list[str] = []
            replacements: dict[str, Any] = {}
            for name, value in span.attributes.items():
                if not capture_content and is_content_attribute(name):
                    deleted.append(name)
                    continue
                masked = redact_value(value, key=name)
                if masked != value:
                    replacements[name] = masked
            if deleted or replacements:
                patches[identifier] = OtelSpanPatch(
                    delete_attributes=tuple(deleted),
                    set_attributes=replacements,
                )
        if not patches:
            return None
        return MaskOtelSpansResult(span_patches=patches)

    return mask_otel_spans
