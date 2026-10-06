#!/bin/bash
# Take a quick snapshot from the command line.
set -e

cd "$(dirname "$0")/.."
source .venv/bin/activate

python -c "
from modules.forensics import capture
snap = capture('127.0.0.1', tcp_port=1102)
print(f'saved: {snap[\"path\"]}')
print(f'hash:  {snap[\"sha256_hash\"]}')
"