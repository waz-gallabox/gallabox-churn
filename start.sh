#!/usr/bin/env bash
# Gallabox Churn local dev startup
#
# Starts PocketBase + runs a quick background sync + starts Next.js.
# Ctrl-C stops everything cleanly.
#
# Usage:
#   ./start.sh           # normal startup
#   ./start.sh --no-sync # skip background sync (faster, stale data)

set -e

REPO="$(cd "$(dirname "$0")" && pwd)"

# ── Load root .env into shell environment ─────────────────────────────────────
# This lets Next.js inherit all vars — no separate frontend/.env.local needed.
if [[ -f "$REPO/.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$REPO/.env"
    set +a
fi
NO_SYNC=false
[[ "$*" == *"--no-sync"* ]] && NO_SYNC=true

# ── Cleanup on exit ───────────────────────────────────────────────────────────
PB_PID=""
SYNC_PID=""

cleanup() {
    echo ""
    echo "Stopping..."
    [[ -n "$SYNC_PID" ]] && kill "$SYNC_PID" 2>/dev/null || true
    [[ -n "$PB_PID"   ]] && kill "$PB_PID"   2>/dev/null || true
    wait 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT INT TERM

# ── 1. Start PocketBase ───────────────────────────────────────────────────────
echo "[start.sh] Starting PocketBase..."
"$REPO/pocketbase" serve >> "$REPO/pb.log" 2>&1 &
PB_PID=$!

# Wait for PocketBase to be ready (poll health endpoint, max 15s)
echo -n "[start.sh] Waiting for PocketBase"
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8090/api/health > /dev/null 2>&1; then
        echo " ready"
        break
    fi
    echo -n "."
    sleep 0.5
done

if ! curl -sf http://127.0.0.1:8090/api/health > /dev/null 2>&1; then
    echo ""
    echo "[start.sh] ERROR: PocketBase did not start in time. Check pb.log."
    exit 1
fi

# ── 2. Background sync ────────────────────────────────────────────────────────
if [[ "$NO_SYNC" == false ]]; then
    echo "[start.sh] Starting quick sync in background (--quick)..."
    python3 "$REPO/sync_all.py" --quick >> "$REPO/sync_all.log" 2>&1 &
    SYNC_PID=$!
    echo "[start.sh] Sync running in background (PID $SYNC_PID) — tail sync_all.log to follow"
else
    echo "[start.sh] Skipping sync (--no-sync)"
fi

# ── 3. Start Next.js (foreground) ─────────────────────────────────────────────
echo "[start.sh] Starting Next.js..."
cd "$REPO/frontend"
npm run dev
