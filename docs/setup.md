# Setup

## Prerequisites

- Ubuntu 22.04+ (or any Debian-based distro)
- Python 3.11+
- OpenPLC_v3 installed and running
- Git

## Install

    git clone https://github.com/<team>/RTO_Eradication_framework.git
    cd RTO_Eradication_framework
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

## Run tests

    pytest -v

## Run orchestrator

    python -m modules.orchestrator.main --config config/config.yaml

Dry-run (no attacks):

    python -m modules.orchestrator.main --config config/config.yaml --dry-run