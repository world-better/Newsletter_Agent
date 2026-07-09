#!/bin/bash
# ── 任意门聚合简报 · 容器启动脚本 ─────────────────────────
# Starts FastAPI (backend) + Streamlit (frontend) in one container.
# Traps SIGTERM for graceful shutdown.

set -e

cleanup() {
    echo "[shutdown] Stopping services..."
    kill "$API_PID" 2>/dev/null || true
    kill "$WEB_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true
    echo "[shutdown] Done."
}
trap cleanup EXIT INT TERM

echo "=================================="
echo "  任意门聚合简报"
echo "=================================="

# ── Backend (FastAPI) ──
echo "[api] Starting on :8001..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --log-level info &
API_PID=$!

# Wait for backend
echo "[api] Waiting for readiness..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:8001/ >/dev/null 2>&1; then
        echo "[api] Ready ✓"
        break
    fi
    sleep 1
done

# ── Frontend (Streamlit) ──
echo "[web] Starting on :8501..."
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
AGENT_API_BASE="http://127.0.0.1:8001" \
python -m streamlit run web/app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false &
WEB_PID=$!

echo ""
echo "  API:  http://0.0.0.0:8001"
echo "  Web:  http://0.0.0.0:8501"
echo "  Press Ctrl+C to stop."
echo ""

# Wait for either process to exit
wait -n "$API_PID" "$WEB_PID" 2>/dev/null || true
