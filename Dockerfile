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
COPY docs/ docs/
RUN uv sync --no-dev

# Stage 2: Runtime image (no uv, no build deps)
FROM python:3.12-slim AS runner

WORKDIR /app

# git for tools/git.py, curl for healthcheck, Node.js for the Claude Code CLI
# (Node ≥18 is required by @anthropic-ai/claude-code; NodeSource ships 20.x).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /root/.npm

RUN useradd -m -s /bin/bash botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app /home/botuser

COPY --from=builder --chown=botuser:botuser /app/.venv /app/.venv
COPY --from=builder --chown=botuser:botuser /app/src /app/src
COPY --from=builder --chown=botuser:botuser /app/docs /app/docs
COPY --from=builder --chown=botuser:botuser /app/theswarm.yaml* /app/

# Chromium's shared libraries, for the QA agent's screenshot and video
# capture. Needs root, so it runs before the USER switch; the browser itself
# is fetched afterwards as botuser.
RUN /app/.venv/bin/playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

USER botuser

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Only the headless shell, which is what `chromium.launch(headless=True)`
# actually executes — the full Chromium build is ~800MB more for a UI this
# image never opens. Installed as botuser so it lands in the cache of the
# user the app runs as.
RUN playwright install chromium-headless-shell

EXPOSE 8091

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8091/health || exit 1

CMD ["python", "-m", "theswarm"]
