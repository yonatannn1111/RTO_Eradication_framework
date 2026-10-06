# RTO Eradication Framework

OT security toolkit for OpenPLC-based industrial control systems.

## Team

| Member | Module | Branch |
|--------|--------|--------|
| yonatan | `modules/ot_infrastructure/` | `feature/ot-infrastructure` |
| bethel| `modules/forensics/` | `feature/forensics-engine` |
| hamere | `modules/attack_simulation/` | `feature/attack-simulation` |
| aberham | `modules/scheduler/` | `feature/scheduler` |
| kedest | `modules/orchestrator/` | `feature/orchestrator` |


## Branch Structure

    main
     └── dev
          ├── feature/ot-infrastructure
          ├── feature/forensics-engine
          ├── feature/attack-simulation
          ├── feature/scheduler
          └── feature/orchestrator

## Setup

    git clone https://github.com/<team>/RTO_Eradication_framework.git
    cd RTO_Eradication_framework
    ./scripts/setup.sh

Or manually:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

## Run Tests

    pytest -v

## Run the Pipeline

    ./scripts/run_orchestrator.sh

Dry-run (no attacks):

    python -m modules.orchestrator.main --config config/config.yaml --dry-run

## Repository Layout

    RTO_Eradication_framework/
    ├── .github/workflows/ci.yml
    ├── config/config.yaml
    ├── docs/              # architecture, setup, module docs
    ├── modules/
    │   ├── ot_infrastructure/
    │   ├── forensics/
    │   ├── attack_simulation/
    │   ├── scheduler/
    │   └── orchestrator/
    ├── scripts/           # helper shell scripts
    ├── tests/             # pytest suite
    ├── requirements.txt
    ├── .gitignore
    └── README.md

## Documentation

- [Architecture](docs/architecture.md)
- [Setup](docs/setup.md)
- [Modules](docs/modules.md)
- [Testing](docs/testing.md)

