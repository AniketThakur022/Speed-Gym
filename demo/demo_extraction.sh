#!/usr/bin/env bash
# Vedic Math Speed Gym — DATA EXTRACTION demo.
# Read-only against the corpus; everything it writes lands in demo/output/.
# Re-runnable: run it as many times as you like.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 demo/demo_extraction.py "$@"
