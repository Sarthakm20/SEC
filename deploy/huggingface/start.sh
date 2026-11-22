#!/bin/sh
# Start FastAPI (internal) and the Next.js UI (public, :7860). If either exits, the container exits.
set -e
cd /app
uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --workers 1 &
API=$!
PORT=7860 HOSTNAME=0.0.0.0 node web/server.js &
WEB=$!
# POSIX sh has no `wait -n`; poll both children instead
while kill -0 "$API" 2>/dev/null && kill -0 "$WEB" 2>/dev/null; do sleep 5; done
echo "a process exited; stopping container" >&2
kill "$API" "$WEB" 2>/dev/null || true
exit 1
