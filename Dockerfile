# Stage 1: Build virtualenv with uv
FROM python:3.12-slim AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

COPY src/ src/
COPY theswarm.yaml* ./
RUN uv sync --no-dev

# Stage 2: Runtime image (no uv, no build deps)
FROM python:3.12-slim AS runner

WORKDIR /app

# git is required at runtime by tools/git.py; curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app /home/botuser

COPY --from=builder --chown=botuser:botuser /app/.venv /app/.venv
COPY --from=builder --chown=botuser:botuser /app/src /app/src
COPY --from=builder --chown=botuser:botuser /app/theswarm.yaml* /app/

USER botuser

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8091

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8091/health || exit 1

CMD ["python", "-m", "theswarm"]
