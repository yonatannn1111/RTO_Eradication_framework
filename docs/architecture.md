# Architecture

## High-level flow

    ┌──────────────────┐
    │   Orchestrator   │  modules/orchestrator/
    │     (main)       │
    └────────┬─────────┘
             │  runs 5 stages in order
             ▼
    ┌──────────────────┐
    │ 1. Infrastructure│  modules/ot_infrastructure/
    │    verify PLC    │
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ 2. Snapshot      │  modules/forensics/
    │    capture state │
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ 3. Attack        │  modules/attack_simulation/
    │    run scenario  │
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ 4. Detect        │  modules/forensics/  (diff)
    │    compare state │
    └────────┬─────────┘
             ▼
    ┌──────────────────┐
    │ 5. Report        │  output/last_run.json
    └──────────────────┘

## Module responsibilities

| Module | Owner | Purpose |
|--------|-------|---------|
| `ot_infrastructure` | Student A | Verify PLC reachability, ports open |
| `forensics` | Student B | Snapshot, restore, validate, diff |
| `attack_simulation` | Student C | Modbus attack scripts |
| `scheduler` | Student D | Interval runner + SimPy model |
| `orchestrator` | Student E | Wire stages into one pipeline |
| `tests` | Student F | Smoke + integration tests |

## Data flow

1. Orchestrator loads `config/config.yaml`
2. Infrastructure stage verifies Modbus/S7/HTTPS ports
3. Forensics stage captures a **pre-attack** snapshot
4. Attack stage modifies PLC registers per config
5. Forensics diff compares **pre** vs **post** snapshot
6. Report stage writes JSON summary to `output/last_run.json`