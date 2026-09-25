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

# Stage: compile the V2 stylesheet with the standalone Tailwind binary
# (no node in any image; version pinned to match scripts/build-css.sh)
FROM debian:bookworm-slim AS css
WORKDIR /css
ADD https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.3/tailwindcss-linux-x64 /usr/local/bin/tailwindcss
RUN chmod +x /usr/local/bin/tailwindcss
COPY src/theswarm/presentation/web/templates/ templates/
COPY src/theswarm/presentation/web/static/v2/ static/v2/
# input.css resolves @source ../../templates/v2 relative to itself
RUN tailwindcss -i static/v2/input.css -o app.css --minify

# Stage 2: Runtime image (no uv, no build deps)
FROM python:3.12-slim AS runner

WORKDIR /app

# git for tools/git.py, curl for the healthcheck. No Node: the Claude Agent
# SDK's wheel bundles its own Claude Code binary (V2 runtime; the npm install
# of @anthropic-ai/claude-code left in M7, after fourteen prod cycles on it).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv at runtime: the Dev and QA agents build the target's venv with
# `uv venv --seed` (V2 M5); seconds instead of the minute python -m venv
# takes, and no more installs into this image's system python.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ~/.swarm-workspaces exists in the image so the named volume mounted there
# (docker-compose.yml) is created owned by botuser: Docker copies the image
# directory's ownership into an empty volume on first mount.
RUN useradd -m -s /bin/bash botuser \
    && mkdir -p /app/data /home/botuser/.swarm-workspaces \
    && chown -R botuser:botuser /app /home/botuser

COPY --from=builder --chown=botuser:botuser /app/.venv /app/.venv
COPY --from=builder --chown=botuser:botuser /app/src /app/src
COPY --from=builder --chown=botuser:botuser /app/docs /app/docs
COPY --from=builder --chown=botuser:botuser /app/theswarm.yaml* /app/
COPY --from=css --chown=botuser:botuser /css/app.css /app/src/theswarm/presentation/web/static/v2/app.css

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
