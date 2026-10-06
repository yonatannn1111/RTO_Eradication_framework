#!/bin/bash
# Convenience wrapper for running the orchestrator.
set -e

cd "$(dirname "$0")/.."
source .venv/bin/activate

python -m modules.orchestrator.main --config config/config.yaml "$@"