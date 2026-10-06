#!/bin/bash
# Setup helper — creates venv and installs deps.
set -e

echo "[setup] creating virtualenv..."
python3 -m venv .venv

echo "[setup] activating and installing deps..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "[setup] done. Activate with:  source .venv/bin/activate"