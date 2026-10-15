# RTO Eradication Framework

Automated incident-response pipeline for OpenPLC-based conveyor systems.

**Headline results:** 100% forensic recovery · 0.06 s average downtime · 0 mis-sorted bags · 102 automated tests

---

## Team

| Member | Primary Module | Branch |
|--------|----------------|--------|
| Yonatan | `modules/ot_infrastructure/`, `modules/forensics/` | `feature/ot-infrastructure` |
| Bethel | `modules/attack_simulation/`, `modules/forensics/` | `feature/attack-simulation` |
| Hamere | `modules/safety/`, `modules/scheduler/` | `feature/scheduler` |
| Abreham | `modules/orchestrator/` | `feature/orchestrator` |
| Kedest | `modules/orchestrator/`, `modules/cost/` | `feature/orchestrator` |

---

## What it does

The framework runs alongside a live OpenPLC instance and:

1. **Detects** unauthorized register changes (via `RegisterWatcher` polling `%MW0`–`%MW5`)
2. **Captures** a pre-eradication snapshot with SHA-256 integrity
3. **Queries** the safety scheduler for a safe window (`NOW` / `WAIT N` / `DELAY`)
4. **Restores** the PLC from a trusted baseline with retry + validation
5. **Validates** byte-for-byte that the PLC matches the trusted state
6. **Logs** every event to SQLite and JSONL for audit
7. **Resists reinfection** — the loop continues until the attacker is stopped

It handles **multiple PLCs in parallel** via asyncio, and provides a **Streamlit dashboard** for live observation.

---

## Branch Structure

    main                     (production-ready, protected)
     └── dev                 (integration branch)
          ├── feature/ot-infrastructure
          ├── feature/forensics-engine
          ├── feature/attack-simulation
          ├── feature/scheduler
          └── feature/orchestrator

---

## Setup

### Clone

    git clone https://github.com/yonatanannn1111/RTO_Eradication_framework.git
    cd RTO_Eradication_framework

### Automated setup

    ./scripts/setup.sh

### Manual setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

---

## Prerequisites

- Ubuntu 22.04+ (or any Debian-based Linux)
- Python 3.11+
- [OpenPLC_v3](https://github.com/thiagoralves/OpenPLC_v3) installed and running on `localhost`
- The conveyor program (Tasks 4–7) uploaded and running via the OpenPLC web UI at `http://localhost:8080`

---

## Run Tests

    pytest -v

Expected: **102 passed** across the full suite (unit + integration + E2E).

Run just the end-to-end suite:

    pytest tests/e2e/ -v

Run just the attack scenarios:

    pytest tests/test_scenarios.py -v

---

## Run the Pipeline

### Full incident-response orchestrator (Tasks 16 + 27)

    python -m modules.orchestrator.full_orchestrator \
      --plc 127.0.0.1 \
      --trusted-snapshot snapshots/trusted_baseline.json \
      --max-cycles 2

Dry-run (no attacks):

    python -m modules.orchestrator.main --config config/config.yaml --dry-run

### Scheduler-orchestrator connector (Task 26)

    python -m modules.orchestrator.scheduler_connector \
      --plc 127.0.0.1 \
      --trusted-snapshot snapshots/trusted_baseline.json \
      --poll-interval 5 \
      --max-actions 3

### Safety scheduler (Task 20)

    python -m modules.safety.api --plc 127.0.0.1 --interval 5 --port 5003

### Conveyor status API (Task 17)

    python -m modules.conveyor_api.app --plc 127.0.0.1 --port 5001

### Streamlit dashboard (Task 21)

    streamlit run modules/dashboard/app.py --server.port 8501

Then open [http://localhost:8501](http://localhost:8501).

### Attack scenario test harness (Task 29)

    python -m scenarios --trusted-snapshot snapshots/trusted_baseline.json

---

## Repository Layout

    RTO_Eradication_framework/
    ├── .github/workflows/ci.yml          # GitHub Actions CI
    ├── config/
    │   ├── config.yaml                   # orchestrator configuration
    │   └── cost.yaml                     # cost function weights + thresholds
    ├── docs/                             # architecture, setup, module docs
    │   ├── README.md
    │   ├── architecture.md
    │   ├── setup.md
    │   ├── modules.md
    │   └── testing.md
    ├── modules/
    │   ├── ot_infrastructure/            # PLC reachability checks
    │   ├── forensics/                    # snapshot, restore, diff, bridge, dispatch
    │   │   ├── snapshot.py
    │   │   ├── restore.py
    │   │   ├── diff.py
    │   │   ├── compare.py
    │   │   ├── watcher.py
    │   │   ├── bridge.py
    │   │   ├── dispatch.py
    │   │   └── pre_eradication.py
    │   ├── attack_simulation/            # attacks + persistent reinfection
    │   │   ├── attacks.py
    │   │   ├── variants.py
    │   │   ├── reinfect.py
    │   │   ├── logger.py
    │   │   └── api.py
    │   ├── scheduler/                    # SimPy twin, bridge, connector
    │   │   ├── runner.py
    │   │   ├── simpy_model.py
    │   │   ├── plc_source.py
    │   │   ├── twin.py
    │   │   └── bridge.py
    │   ├── safety/                       # safe-window scheduler + API
    │   │   ├── window.py
    │   │   ├── scheduler.py
    │   │   └── api.py
    │   ├── cost/                         # urgency scoring
    │   │   ├── config.py
    │   │   └── function.py
    │   ├── conveyor_api/                 # real-time belt status REST API
    │   │   ├── reader.py
    │   │   └── app.py
    │   ├── dashboard/                    # Streamlit monitoring UI
    │   │   ├── config.py
    │   │   ├── reader.py
    │   │   └── app.py
    │   └── orchestrator/                 # the pipeline + full orchestrator
    │       ├── main.py
    │       ├── dashboard.py
    │       ├── scheduler_connector.py
    │       ├── full_orchestrator.py
    │       ├── resilience_loop.py
    │       └── events_db.py
    ├── scenarios/                        # Task 29 attack scenario harness
    │   ├── metrics.py
    │   ├── runner.py
    │   ├── scenario_1_timer.py
    │   ├── scenario_2_counter.py
    │   ├── scenario_3_flag.py
    │   ├── scenario_4_multi_plc.py
    │   ├── scenario_5_reinfection.py
    │   └── __main__.py
    ├── scripts/
    │   ├── setup.sh
    │   ├── run_orchestrator.sh
    │   ├── snapshot.sh
    │   └── attacks.sh
    ├── snapshots/                        # trusted baselines + incident snapshots
    ├── output/                           # run artifacts (gitignored)
    │   ├── run_<timestamp>/
    │   ├── resilience_<timestamp>/
    │   ├── scenarios/
    │   └── orchestrator_events.db
    ├── logs/                             # runtime logs (gitignored)
    ├── tests/                            # pytest suite (102 tests)
    │   ├── e2e/                          # end-to-end integration tests
    │   └── test_*.py
    ├── requirements.txt
    ├── pytest.ini
    ├── .gitignore
    └── README.md

---

## Configuration

All configuration lives in `config/`. The orchestrator reads `config/config.yaml`:

    plc:
      ip: "127.0.0.1"
      modbus_port: 502
      s7_port: 1102
      https_port: 8443

    snapshot:
      db1_size: 100
      db2_size: 100
      merker_size: 100

    scheduler_url:  "http://127.0.0.1:5002"
    safety_url:     "http://127.0.0.1:5003"
    belt_id:        "plc_a"
    trusted_snapshot: "snapshots/trusted_baseline.json"

    output_dir: "output"

    cost_inputs:
      queue_length: 8
      flights_affected: 2
      belt_criticality: high
      wait_minutes: 0

The cost function's weights and thresholds live in `config/cost.yaml` — edit to retune the urgency model without touching code.

---

## Register Map (Conveyor Program)

| Modbus address | OpenPLC | R/W | Purpose |
|---|---|---|---|
| 0 | `%MW0` | R/W | Motor control — 0=stop, 1=run |
| 1 | `%MW1` | R/W | Belt speed setpoint (ms) |
| 2 | `%MW2` | R   | Timer T1 elapsed (ms) |
| 3 | `%MW3` | R   | Bag counter C1 |
| 4 | `%MW4` | R   | Status flags (bit0=run, bit1=timer, bit2=bag) |
| 5 | `%MW5` | R/W | Bag sensor — 0/1 |

---

## Metrics — Attack Scenario Results

| Scenario | Forensic Recovery | Downtime | Mis-sorted Bags |
|---|---|---|---|
| 1 — Timer Attack | 100% | 0.06 s | 0 |
| 2 — Counter Attack | 100% | 0.05 s | 0 |
| 3 — Flag Attack | 100% | 0.05 s | 0 |
| 4 — Multi-PLC | 100% | 0.06 s | 0 |
| 5 — Reinfection | 100% | 0.06 s | 0 |
| **Average** | **100%** | **0.06 s** | **0** |

Full results: `output/scenarios/summary_table.{csv,md}`

---

## Documentation

- [Architecture](docs/architecture.md) — high-level design and data flow
- [Setup](docs/setup.md) — full environment setup
- [Modules](docs/modules.md) — one-page description of each module
- [Testing](docs/testing.md) — test strategy and how to run the suite

---

## Contributing

1. Branch off `dev`: `git checkout -b feature/your-module dev`
2. Commit early and often with descriptive messages
3. Run `pytest -v` before pushing — CI must stay green
4. Open a PR into `dev` and request a review
5. After review, squash-merge into `dev`
6. `dev` merges into `main` at milestones

---

## Security Notes

This framework is designed for **lab and educational use**. In production OT environments:

- **Modbus has no authentication** — never expose port 502 to the public internet
- Use a VPN (Tailscale, WireGuard) for remote access, not port forwarding
- Segment PLCs onto isolated VLANs with firewall rules restricting Modbus clients
- Change the OpenPLC web UI password from the default `openplc`/`openplc`
- The attack simulation modules are for defensive testing only — never run them against a live production system


