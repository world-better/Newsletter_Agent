# ── 任意门聚合简报 · Dockerfile ────────────────────────────
# Hot-plug safe: does NOT import app modules, only runs scripts.
# Swap agent framework → change requirements.txt, not this file.
#
# Secrets (.env) are NOT copied — inject via platform env vars:
#   OPENROUTER_API_KEY    (required)
#   OPENROUTER_MODEL_ID   (default: deepseek/deepseek-v4-flash)
# ─────────────────────────────────────────────────────────────

FROM python:3.12-slim

WORKDIR /app

# System deps (curl for healthcheck + start.sh readiness check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (layered: code changes don't invalidate pip cache)
COPY app/ ./app/
COPY web/ ./web/
RUN chmod +x web/start.sh

# Health check via FastAPI root endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/ || exit 1

EXPOSE 8001 8501

CMD ["/bin/bash", "web/start.sh"]
