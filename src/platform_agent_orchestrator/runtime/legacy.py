"""Legacy process composition retained until dispatcher/bootstrap migration."""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress
from pathlib import Path
from urllib.parse import quote

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from platform_agent_orchestrator.adapters import DemoPlatformServices
from platform_agent_orchestrator.api import ReadinessReport, create_app
from platform_agent_orchestrator.bootstrap import build_dependencies
from platform_agent_orchestrator.checkpointing import postgres_checkpointer
from platform_agent_orchestrator.dispatcher import DatabaseJobDispatcher
from platform_agent_orchestrator.persistence import DatabaseReplayStore, EventRepository
from platform_agent_orchestrator.security import AdmissionSecurity, ReviewerSecurity
from platform_agent_orchestrator.settings import ApplicationSettings, RuntimeRole
from platform_agent_orchestrator.side_effects import DatabaseSideEffectStore, DurableNotifier
from platform_agent_orchestrator.telemetry import PublicEventLogger, ServiceMetrics
from platform_agent_orchestrator.worker import RegistryExecution, Worker

WORKER_READY_PATH = Path("/tmp/platform-agent-worker-ready")


class DatabaseReadinessProbe:
    def __init__(self, sessions: async_sessionmaker, settings: ApplicationSettings) -> None:
        self._sessions = sessions
        self._settings = settings

    async def check(self) -> ReadinessReport:
        try:
            async with self._sessions() as session:
                revision = await session.scalar(sa.text("SELECT version_num FROM alembic_version"))
            persistence = "ready" if revision == "0002_feedback" else "schema_mismatch"
        except Exception:
            persistence = "unavailable"
        authentication = (
            "ready" if self._settings.webhook_signing_secret is not None else "unconfigured"
        )
        ready = persistence == "ready" and authentication == "ready"
        return ReadinessReport(
            ready=ready,
            checks={
                "configuration": "ready",
                "authentication": authentication,
                "persistence": persistence,
                "replay_store": persistence,
            },
        )


def _runtime_settings() -> ApplicationSettings:
    values = dict(os.environ)
    database_password = _read_secret(values.get("ORCHESTRATOR_DATABASE_PASSWORD_FILE"))
    if "ORCHESTRATOR_DATABASE_URL" not in values and database_password is not None:
        user = values.get("ORCHESTRATOR_DATABASE_USER", "platform_agent")
        host = values.get("ORCHESTRATOR_DATABASE_HOST", "postgres")
        database = values.get("ORCHESTRATOR_DATABASE_NAME", "platform_agent")
        values["ORCHESTRATOR_DATABASE_URL"] = (
            f"postgresql+psycopg://{quote(user, safe='')}:{quote(database_password, safe='')}"
            f"@{host}/{database}"
        )
    if "CHECKPOINT_DATABASE_URL" not in values and database_password is not None:
        user = values.get("ORCHESTRATOR_DATABASE_USER", "platform_agent")
        host = values.get("ORCHESTRATOR_DATABASE_HOST", "postgres")
        database = values.get("CHECKPOINT_DATABASE_NAME", "platform_agent_checkpoints")
        values["CHECKPOINT_DATABASE_URL"] = (
            f"postgresql://{quote(user, safe='')}:{quote(database_password, safe='')}"
            f"@{host}/{database}"
        )
    for setting, file_setting in (
        ("PLATFORM_WEBHOOK_SIGNING_SECRET", "PLATFORM_WEBHOOK_SIGNING_SECRET_FILE"),
        ("PLATFORM_REVIEWER_SIGNING_SECRET", "PLATFORM_REVIEWER_SIGNING_SECRET_FILE"),
    ):
        secret = _read_secret(values.get(file_setting))
        if setting not in values and secret is not None:
            values[setting] = secret
    return ApplicationSettings.from_env(values)


def _read_secret(path: str | None) -> str | None:
    if path is None:
        return None
    value = Path(path).read_text().strip()
    if not value or len(value) > 4096:
        raise ValueError(f"secret file is empty or oversized: {path}")
    return value


def build_api_app():
    settings = _runtime_settings()
    if settings.role != RuntimeRole.API:
        raise ValueError("API process requires PLATFORM_RUNTIME_ROLE=api")
    assert settings.database_url is not None
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    metrics = ServiceMetrics()
    event_logger = PublicEventLogger()
    repository = EventRepository(sessions, metrics=metrics, event_logger=event_logger)
    replay = DatabaseReplayStore(sessions)
    return create_app(
        settings=settings,
        admission_security=AdmissionSecurity(settings, replay),
        reviewer_security=ReviewerSecurity(settings, replay),
        event_repository=repository,
        readiness=DatabaseReadinessProbe(sessions, settings),
        service_metrics=metrics,
        public_event_logger=event_logger,
        async_shutdown=engine.dispose,
    )


async def run_worker(stop_event: asyncio.Event | None = None) -> None:
    settings = _runtime_settings()
    if settings.role != RuntimeRole.WORKER:
        raise ValueError("worker process requires PLATFORM_RUNTIME_ROLE=worker")
    assert settings.database_url is not None
    assert settings.checkpoint_database_url is not None
    metrics = ServiceMetrics()
    event_logger = PublicEventLogger()
    async_engine = create_async_engine(
        settings.database_url.get_secret_value(), pool_pre_ping=True
    )
    sessions = async_sessionmaker(async_engine, expire_on_commit=False)
    repository = EventRepository(sessions, metrics=metrics, event_logger=event_logger)
    sync_engine = sa.create_engine(
        settings.database_url.get_secret_value(), pool_pre_ping=True
    )
    side_effect_store = DatabaseSideEffectStore(
        sessionmaker(sync_engine, expire_on_commit=False),
        metrics=metrics,
        event_logger=event_logger,
    )
    demo = DemoPlatformServices()
    services = demo.as_services(
        notifier=DurableNotifier(side_effect_store, demo.notifier, settings.scope_id)
    )
    dependencies = build_dependencies(settings)
    stop = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    if stop_event is None:
        for name in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError):
                loop.add_signal_handler(name, stop.set)

    try:
        with postgres_checkpointer(settings.checkpoint_database_url) as checkpointer:
            checkpointer.get({"configurable": {"thread_id": "worker-health"}})
            WORKER_READY_PATH.write_text("ready\n")
            flow_dispatcher = dependencies.dispatcher(
                checkpointer=checkpointer,
                services=services,
            )
            worker = Worker(
                worker_id="local-worker-1",
                dispatcher=DatabaseJobDispatcher(repository),
                executor=RegistryExecution(repository, flow_dispatcher),
                outcomes=repository,
                metrics=metrics,
                event_logger=event_logger,
            )
            while not stop.is_set():
                completed = await worker.run_once()
                if completed == 0:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.5)
                    except TimeoutError:
                        pass
            await worker.shutdown()
    finally:
        WORKER_READY_PATH.unlink(missing_ok=True)
        dependencies.shutdown()
        await async_engine.dispose()
        sync_engine.dispose()


def worker_main() -> None:
    asyncio.run(run_worker())


def checkpoint_migrate_main() -> None:
    settings = _runtime_settings()
    if settings.role != RuntimeRole.MIGRATION:
        raise ValueError("migration process requires PLATFORM_RUNTIME_ROLE=migration")
    if settings.checkpoint_database_url is None:
        raise ValueError("checkpoint migration requires CHECKPOINT_DATABASE_URL")
    with postgres_checkpointer(settings.checkpoint_database_url, setup=True):
        pass
