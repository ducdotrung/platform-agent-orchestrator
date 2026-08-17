"""Capability facade for the provider-neutral memory port."""

from __future__ import annotations

from dataclasses import dataclass

from platform_agent_orchestrator.core.capabilities import CapabilityRequest, CapabilityResult
from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.memory import MemoryQuery, MemoryRecord
from platform_agent_orchestrator.ports.memory import MemoryPort, MemoryPortError


@dataclass(frozen=True)
class MemoryCapabilityProvider:
    """Expose a typed memory port through the generic capability registry."""

    memory: MemoryPort

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"memory.recall", "memory.record", "memory.feedback"})

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        try:
            if request.capability == "memory.recall":
                query = MemoryQuery.model_validate(request.arguments)
                items = await self.memory.recall(query, context=context)
                return CapabilityResult(
                    success=True,
                    data={
                        "memories": [item.model_dump(mode="json") for item in items]
                    },
                )
            if request.capability == "memory.record":
                record = MemoryRecord.model_validate(request.arguments)
                memory_id = await self.memory.record(record, context=context)
                return CapabilityResult(
                    success=True,
                    data={"memory_id": memory_id, "receipt": memory_id},
                )
            if request.capability == "memory.feedback":
                memory_id = str(request.arguments.get("memory_id", "")).strip()
                useful = request.arguments.get("useful")
                reason = request.arguments.get("reason")
                if not memory_id:
                    raise ValueError("memory.feedback requires a memory_id")
                if not isinstance(useful, bool):
                    raise TypeError("memory.feedback useful must be a boolean")
                if reason is not None and not isinstance(reason, str):
                    raise TypeError("memory.feedback reason must be a string or null")
                await self.memory.feedback(
                    memory_id,
                    useful=useful,
                    reason=reason,
                    context=context,
                )
                return CapabilityResult(
                    success=True,
                    data={"memory_id": memory_id, "accepted": True},
                )
        except (KeyError, MemoryPortError, TypeError, ValueError) as error:
            return CapabilityResult(success=False, error=str(error))
        return CapabilityResult(
            success=False,
            error=f"unsupported memory capability: {request.capability}",
        )
