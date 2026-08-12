#!/usr/bin/env bash
set -Eeuo pipefail
INSTALL_DIR=${UNIVERSAL_DASHBOARD_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/universal-dashboard-agent}
API_PORT=${DASHBOARD_SMOKE_PORT:-18000}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR=$2; shift 2 ;;
    --port) API_PORT=$2; shift 2 ;;
    *) printf 'Usage: %s [--install-dir DIR] [--port PORT]\n' "$0" >&2; exit 2 ;;
  esac
done
[[ -x "$INSTALL_DIR/.venv/bin/python" ]] || { printf 'Installed Python environment not found: %s\n' "$INSTALL_DIR" >&2; exit 1; }
if [[ -f "$INSTALL_DIR/config/local.env" ]]; then
  set -a
  . "$INSTALL_DIR/config/local.env"
  set +a
fi
export DASHBOARD_LOCAL_AUTH_TOKEN=$($INSTALL_DIR/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')
"$INSTALL_DIR/.venv/bin/python" -m automation.release.diagnostics --root "$INSTALL_DIR" --runtime "$INSTALL_DIR/.hermes-runtime" --no-node --no-browser
cd "$INSTALL_DIR"
"$INSTALL_DIR/.venv/bin/python" -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port "$API_PORT" >/tmp/universal-dashboard-smoke.log 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; }
trap cleanup EXIT
for _ in {1..30}; do
  if curl --silent --fail "http://127.0.0.1:$API_PORT/health" >/dev/null; then
    printf 'PASS: API health responded on 127.0.0.1:%s\n' "$API_PORT"
    exit 0
  fi
  sleep 1
done
printf 'FAIL: API did not respond; log follows:\n' >&2
cat /tmp/universal-dashboard-smoke.log >&2
exit 1
