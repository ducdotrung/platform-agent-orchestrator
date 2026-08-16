"""Declarative plugin manifest models and YAML parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ManifestModel(BaseModel):
    """Strict base model for declarative plugin metadata."""

    model_config = ConfigDict(extra="forbid")


class ManifestMetadata(ManifestModel):
    """Plugin identity declared by a manifest."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ManifestCapabilities(ManifestModel):
    """Required and optional capabilities for one flow."""

    required: frozenset[str] = Field(default_factory=frozenset)
    optional: frozenset[str] = Field(default_factory=frozenset)


class ManifestFlow(ManifestModel):
    """Declarative discovery and compatibility data for one flow."""

    name: str = Field(min_length=1)
    triggers: frozenset[str] = Field(min_length=1)
    capabilities: ManifestCapabilities = Field(default_factory=ManifestCapabilities)


class ManifestPermissions(ManifestModel):
    """Declared capability permission patterns for review and validation."""

    read: frozenset[str] = Field(default_factory=frozenset)
    write: frozenset[str] = Field(default_factory=frozenset)


class PluginManifest(ManifestModel):
    """Validated metadata and permissions for a flow plugin package."""

    api_version: Literal["platform-agent/v1"] = Field(alias="apiVersion")
    kind: Literal["FlowPlugin"]
    metadata: ManifestMetadata
    flows: tuple[ManifestFlow, ...] = Field(min_length=1)
    permissions: ManifestPermissions = Field(default_factory=ManifestPermissions)


def parse_manifest(content: str | bytes) -> PluginManifest:
    """Parse and validate a YAML plugin manifest."""

    document = yaml.safe_load(content)
    if not isinstance(document, dict):
        raise ValueError("plugin manifest must contain a YAML mapping")
    return PluginManifest.model_validate(document)


def load_manifest(path: str | Path) -> PluginManifest:
    """Load and validate a UTF-8 YAML plugin manifest from disk."""

    return parse_manifest(Path(path).read_text(encoding="utf-8"))
