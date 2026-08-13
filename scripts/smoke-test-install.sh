#!/usr/bin/env bash
set -Eeuo pipefail
INSTALL_DIR=${UNIVERSAL_DASHBOARD_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/universal-dashboard-agent}
API_PORT=${DASHBOARD_SMOKE_PORT:-8000}
WEB_PORT=${DASHBOARD_SMOKE_WEB_PORT:-13000}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR=$2; shift 2 ;;
    --port) API_PORT=$2; shift 2 ;;
    --web-port) WEB_PORT=$2; shift 2 ;;
    *) printf 'Usage: %s [--install-dir DIR] [--port PORT] [--web-port PORT]\n' "$0" >&2; exit 2 ;;
  esac
done
PYTHON=$INSTALL_DIR/.venv/bin/python
[[ -x "$PYTHON" ]] || { printf 'Installed Python environment not found: %s\n' "$INSTALL_DIR" >&2; exit 1; }
set -a
. "$INSTALL_DIR/config/local.env"
set +a
export DASHBOARD_LOCAL_AUTH_TOKEN=$($PYTHON -c 'import secrets; print(secrets.token_urlsafe(32))')
export DASHBOARD_HERMES_RUNTIME=$INSTALL_DIR/.hermes-runtime
export DASHBOARD_ALLOWED_ORIGINS=http://127.0.0.1:$WEB_PORT
export DASHBOARD_API_ORIGIN=http://127.0.0.1:$API_PORT
TASK_TEMP=$(mktemp -d)
API_PID=
WEB_PID=
cleanup() {
  [[ -z "$WEB_PID" ]] || kill "$WEB_PID" 2>/dev/null || true
  [[ -z "$API_PID" ]] || kill "$API_PID" 2>/dev/null || true
  wait "$WEB_PID" "$API_PID" 2>/dev/null || true
  rm -rf "$TASK_TEMP"
}
trap cleanup EXIT
start_api() {
  (cd "$INSTALL_DIR" && "$PYTHON" -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port "$API_PORT") >"$TASK_TEMP/api.log" 2>&1 &
  API_PID=$!
  for _ in {1..60}; do curl --silent --fail "http://127.0.0.1:$API_PORT/health" >/dev/null && return; sleep 0.25; done
  cat "$TASK_TEMP/api.log" >&2; return 1
}
start_web() {
  if [[ -f "$INSTALL_DIR/dashboard/web/.next/standalone/server.js" ]]; then
    NODE=$INSTALL_DIR/runtime/node/bin/node
    (cd "$INSTALL_DIR/dashboard/web" && HOSTNAME=127.0.0.1 PORT=$WEB_PORT "$NODE" .next/standalone/server.js) >"$TASK_TEMP/web.log" 2>&1 &
  else
    (cd "$INSTALL_DIR/dashboard/web" && npm run start -- -H 127.0.0.1 -p "$WEB_PORT") >"$TASK_TEMP/web.log" 2>&1 &
  fi
  WEB_PID=$!
  for _ in {1..60}; do curl --silent --fail "http://127.0.0.1:$WEB_PORT" >/dev/null && return; sleep 0.25; done
  cat "$TASK_TEMP/web.log" >&2; return 1
}
"$PYTHON" -m automation.release.diagnostics --root "$INSTALL_DIR" --runtime "$INSTALL_DIR/.hermes-runtime" --node "${INSTALL_DIR}/runtime/node/bin/node" --browser-path "$INSTALL_DIR/.playwright"
start_api
[[ $(curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:$API_PORT/api/hermes/status") == 401 ]]
curl --silent --fail -H "Authorization: Bearer $DASHBOARD_LOCAL_AUTH_TOKEN" "http://127.0.0.1:$API_PORT/api/hermes/status" | "$PYTHON" -c 'import json,sys; value=json.load(sys.stdin); assert "ready" in value and "gateway_authenticated" in value'
start_web
curl --silent --fail "http://127.0.0.1:$WEB_PORT" >"$TASK_TEMP/index.html"
grep -q 'Local dashboard workspace\|Área de trabalho local' "$TASK_TEMP/index.html"
ASSET_PATH=$(grep -o '/_next/static/[^" ]*\.js' "$TASK_TEMP/index.html" | head -1)
[[ -n "$ASSET_PATH" ]]
curl --silent --fail "http://127.0.0.1:$WEB_PORT$ASSET_PATH" >/dev/null
curl --silent --fail "http://127.0.0.1:$WEB_PORT/backend/api/hermes/status" >/dev/null
kill "$API_PID"; wait "$API_PID" || true; API_PID=
start_api
curl --silent --fail -H "Authorization: Bearer $DASHBOARD_LOCAL_AUTH_TOKEN" "http://127.0.0.1:$API_PORT/api/providers" >/dev/null
printf 'PASS: Hermes/API/web loopback, auth, browser proxy, shutdown, and restart checks passed.\n'
