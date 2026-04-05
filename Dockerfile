FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

# Install deps first (cached layer)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

# Copy source and config
COPY src/ src/
COPY theswarm.yaml* ./
RUN uv sync --no-dev

# Non-root user
RUN useradd -m -s /bin/bash botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app /home/botuser
USER botuser

EXPOSE 8091

CMD ["uv", "run", "python", "-m", "theswarm"]
