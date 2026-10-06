#!/bin/bash
# Run the attack loop against a local PLC.
set -e

cd "$(dirname "$0")/.."
source .venv/bin/activate

python -c "
from modules.attack_simulation import run_attacks
run_attacks('127.0.0.1', interval=10)
"