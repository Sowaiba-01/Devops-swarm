# syntax=docker/dockerfile:1.7

# ── Build stage ────────────────────────────────────────────────────────
# Compilers live here and are discarded, so the runtime image ships no
# toolchain for an attacker to build with.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


# ── Runtime stage ──────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random

# curl is required by the container healthcheck below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin swarm

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=swarm:swarm . .

# The process runs unprivileged: a container escape via the app should not
# start from uid 0.
USER swarm

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health/live || exit 1

# One worker: WebSocket connections and the run executor are per-process, so a
# second worker would serve a stream that never receives its run's events.
# Scale with replicas behind a sticky-session load balancer, or move the fan-out
# to Redis first.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--timeout-graceful-shutdown", "45"]
