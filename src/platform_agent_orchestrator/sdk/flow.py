"""Runtime-neutral flow definition API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from platform_agent_orchestrator.core.events import DomainEvent

from .nodes import NodeContext, NodeOutcome


class FlowMetadata(BaseModel):
    """Discovery and compatibility metadata declared by a flow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    event_types: frozenset[str] = Field(min_length=1)
    required_capabilities: frozenset[str] = Field(default_factory=frozenset)
    optional_capabilities: frozenset[str] = Field(default_factory=frozenset)
    tags: frozenset[str] = Field(default_factory=frozenset)


NodeResult: TypeAlias = dict[str, Any] | NodeOutcome
NodeCallable: TypeAlias = Callable[
    [dict[str, Any], NodeContext],
    Awaitable[NodeResult] | NodeResult,
]


@dataclass(frozen=True)
class NodeSpec:
    """A named node and its provider-neutral handler."""

    name: str
    handler: NodeCallable


@dataclass(frozen=True)
class EdgeSpec:
    """An unconditional transition between two node names."""

    source: str
    target: str


@dataclass(frozen=True)
class ConditionalRoute:
    """A state-based route whose keys map to destination node names."""

    source: str
    router: Callable[[dict[str, Any]], str]
    routes: Mapping[str, str]


@dataclass
class FlowDefinition:
    """Small graph specification compiled by a selected workflow runtime."""

    state_schema: type
    entrypoint: str
    nodes: list[NodeSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)
    conditional_routes: list[ConditionalRoute] = field(default_factory=list)


class Flow(Protocol):
    """Public flow interface implemented by builtin and external plugins."""

    @property
    def metadata(self) -> FlowMetadata:
        """Return flow discovery and compatibility metadata."""

        ...

    def accepts(self, event: DomainEvent) -> bool:
        """Return whether this flow should receive an event."""

        ...

    def define(self) -> FlowDefinition:
        """Return a runtime-neutral definition of the flow."""

        ...


class BaseFlow:
    """Convenience base with namespaced event matching."""

    metadata: FlowMetadata

    def accepts(self, event: DomainEvent) -> bool:
        """Match an event against the flow's declared trigger types."""

        return event.type in self.metadata.event_types
