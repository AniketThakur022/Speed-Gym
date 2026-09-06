#!/usr/bin/env bash
# RAG content factory demo — see demo/demo_rag.py for what it does and why it is safe.
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./.venv/bin/python demo/demo_rag.py "$@"
