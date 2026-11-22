#!/usr/bin/env bash
# Publish the demo to a Hugging Face Space.
#
#   one-time:  pip install -U huggingface_hub   &&   hf auth login   (a token with "write" access)
#              create a Space at https://huggingface.co/new-space  →  SDK: Docker  →  "Blank"
#   then:      bash deploy/huggingface/push_space.sh <hf-username>/<space-name>
#
# Stop the API server first: the embedded Qdrant folder is copied and must not be in use.
set -euo pipefail
SPACE="${1:?usage: push_space.sh <hf-username>/<space-name>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "staging Space files in $STAGE"
mkdir -p "$STAGE/deploy/huggingface/data"
cp -r "$ROOT/backend" "$STAGE/backend"
rm -rf "$STAGE/backend/.venv" "$STAGE/backend/data" "$STAGE/backend/.pytest_cache"
find "$STAGE/backend" -name __pycache__ -type d -prune -exec rm -rf {} +
cp -r "$ROOT/frontend" "$STAGE/frontend"
rm -rf "$STAGE/frontend/node_modules" "$STAGE/frontend/.next" "$STAGE/frontend/tsconfig.tsbuildinfo"
cp "$ROOT/deploy/huggingface/Dockerfile" "$STAGE/Dockerfile"
cp "$ROOT/deploy/huggingface/start.sh" "$STAGE/deploy/huggingface/start.sh"
cp "$ROOT/deploy/huggingface/SPACE_README.md" "$STAGE/README.md"

# read-only data snapshot: database + vector index (model weights are downloaded by the Space itself)
# SQLite backup API = consistent copy even with a write-ahead log present
python - "$ROOT/backend/data/secrag.db" "$STAGE/deploy/huggingface/data/secrag.db" <<'EOF'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
EOF
cp -r "$ROOT/backend/data/qdrant" "$STAGE/deploy/huggingface/data/qdrant"
rm -f "$STAGE/deploy/huggingface/data/qdrant/.lock"

du -sh "$STAGE"
hf upload "$SPACE" "$STAGE" . --repo-type space --commit-message "Deploy demo"
echo "done: https://huggingface.co/spaces/$SPACE (build logs are on the Space page)"
