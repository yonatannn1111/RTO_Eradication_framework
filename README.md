# RTO Eradication Framework

Automated incident-response pipeline for OpenPLC-based conveyor systems.

## Team

| Member Name | Student ID |
| :--- | :--- |
| Yonatan Getachew Moges | CTC-955-26 |
| Hamere Getachew | CTC-3578-26 |
| Abraham Dejene | CTC-4374-26 |
| Bethel Mekonnen | CTC-7584-26 |
| Kidist Getu | CTC-3909-26 |

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
- The conveyor program  uploaded and running via the OpenPLC web UI at `http://localhost:8080`


--





## Video  Link ==>   https://www.youtube.com/watch?v=fscShh23vYE




