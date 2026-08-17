FROM python:3.12.11-slim-bookworm AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.lock ./
RUN python -m pip install --prefix=/runtime --requirement requirements.lock

FROM python:3.12.11-slim-bookworm AS runtime

ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="platform-agent-orchestrator" \
      org.opencontainers.image.revision="${SOURCE_REVISION}"

ENV PATH=/runtime/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 orchestrator \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin orchestrator

COPY --from=dependencies /runtime /runtime
WORKDIR /app
COPY alembic.ini pyproject.toml README.md ./
COPY migrations ./migrations
COPY src ./src
COPY deploy ./deploy

USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "platform_agent_orchestrator.runtime.process:build_api_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
