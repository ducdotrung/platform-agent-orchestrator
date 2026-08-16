from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.sdk import load_manifest, parse_manifest

VALID_MANIFEST = """
apiVersion: platform-agent/v1
kind: FlowPlugin
metadata:
  name: builtin.alert
  version: 2.0.0
flows:
  - name: alert-analysis
    triggers:
      - monitoring.alert.received
    capabilities:
      required:
        - knowledge.search
        - notification.send
      optional:
        - memory.recall
permissions:
  read:
    - knowledge.*
    - memory.recall
  write:
    - notification.send
"""


def test_parse_manifest_validates_yaml_metadata_and_permissions() -> None:
    manifest = parse_manifest(VALID_MANIFEST)

    assert manifest.api_version == "platform-agent/v1"
    assert manifest.metadata.name == "builtin.alert"
    assert manifest.flows[0].triggers == frozenset({"monitoring.alert.received"})
    assert manifest.flows[0].capabilities.required == frozenset(
        {"knowledge.search", "notification.send"}
    )
    assert manifest.permissions.write == frozenset({"notification.send"})


def test_load_manifest_reads_utf8_yaml_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    path.write_text(VALID_MANIFEST, encoding="utf-8")

    assert load_manifest(path).metadata.version == "2.0.0"


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        VALID_MANIFEST.replace("platform-agent/v1", "platform-agent/v2"),
        VALID_MANIFEST.replace("kind: FlowPlugin", "kind: PythonExpression"),
        VALID_MANIFEST.replace("    triggers:\n      - monitoring.alert.received\n", ""),
        VALID_MANIFEST + "executable: __import__('os')\n",
    ],
)
def test_manifest_rejects_invalid_or_executable_shapes(content: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        parse_manifest(content)
