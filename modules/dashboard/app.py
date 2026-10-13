"""
Streamlit dashboard for the RTO Eradication Framework.

Run with:
    streamlit run modules/dashboard/app.py

Or from the module:
    python -m modules.dashboard.app

"""
import sys
from pathlib import Path

# Streamlit runs this file as a script, so the repo root isn't on sys.path.
# Add it explicitly so `modules.dashboard.*` imports resolve.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



import time
from datetime import datetime

import streamlit as st

from modules.dashboard.config import DashboardConfig
from modules.dashboard.reader import gather_all


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="OT Incident Response Dashboard",
    page_icon="🛡️",
    layout="wide",
)

cfg = DashboardConfig()

st.title("🛡️ OT Incident Response Dashboard")
st.caption(
    f"Auto-refresh every {cfg.refresh_seconds}s · "
    f"Conveyor {cfg.conveyor_url} · "
    f"Scheduler {cfg.scheduler_url} · "
    f"Safety {cfg.safety_url}"
)

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

data = gather_all(cfg)

conveyor  = data["conveyor"]
scheduler = data["scheduler"]
safety    = data["safety"]
alerts    = data["alerts"]

# ---------------------------------------------------------------------------
# Top row — service liveness
# ---------------------------------------------------------------------------

st.markdown("### Service status")
c1, c2, c3, c4 = st.columns(4)

def _badge(payload):
    return "🟢 up" if "error" not in payload else f"🔴 {payload['error']}"

c1.metric("Conveyor API",   _badge(conveyor))
c2.metric("Scheduler Bridge", _badge(scheduler))
c3.metric("Safety Scheduler", _badge(safety))
c4.metric("Last fetch", data["fetched_at"])

# ---------------------------------------------------------------------------
# PLC status — one card per belt
# ---------------------------------------------------------------------------

st.markdown("### PLCs")

belts = {}
if "belts" in conveyor:
    belts = conveyor["belts"]

safety_belts = safety.get("belts", {}) if "belts" in safety else {}

if not belts:
    st.warning("No belt data — conveyor API unreachable or empty.")
else:
    cols = st.columns(len(belts))
    for col, (belt_id, info) in zip(cols, belts.items()):
        with col:
            status = info.get("status", "unknown")
            # infection classification from safety scheduler
            action = safety_belts.get(belt_id, {}).get("action", "—")
            infected = action in ("NOW", "WAIT")

            badge = "🔴 INFECTED" if infected else "🟢 CLEAN"
            st.markdown(f"#### {belt_id} · {badge}")

            st.metric("Queue", f"{info.get('queue', 0)} bags")
            st.metric("Speed", f"{info.get('speed', 0.0)} bags/s")
            st.metric("Motor", "running" if info.get("motor", 0) else "stopped")
            st.metric("Bags processed", info.get("bags_processed", 0))

            # scheduler recommendation
            if action != "—":
                if action == "NOW":
                    st.error(f"⏱ Safety: **{action}** — eradicate immediately")
                elif action == "WAIT":
                    mins = safety_belts.get(belt_id, {}).get("minutes", "?")
                    st.warning(f"⏱ Safety: **{action} {mins} min**")
                elif action == "DELAY":
                    st.info(f"⏱ Safety: **{action}** — no urgency")
                else:
                    st.text(f"⏱ Safety: {action}")

# ---------------------------------------------------------------------------
# Scheduler bridge — queue state
# ---------------------------------------------------------------------------

st.markdown("### Scheduler bridge")

if "error" in scheduler:
    st.warning(f"Scheduler bridge unreachable: {scheduler['error']}")
else:
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Worker", "🟢 alive" if scheduler.get("worker_alive") else "🔴 down")
    s2.metric("Queue size", scheduler.get("queue_size", 0))
    counts = scheduler.get("task_counts", {})
    s3.metric("Processing", counts.get("processing", 0))
    s4.metric("Total tasks", scheduler.get("total_tasks", 0))

    if counts:
        st.bar_chart(counts)

# ---------------------------------------------------------------------------
# Forensic alerts
# ---------------------------------------------------------------------------

st.markdown("### Forensic alerts")

if not alerts:
    st.info("No alerts in the latest orchestrator run.")
else:
    import pandas as pd

    df = pd.DataFrame(alerts)[
        ["timestamp", "register", "baseline", "observed", "severity", "run_dir"]
    ].rename(columns={
        "timestamp": "Time",
        "register": "Register",
        "baseline": "Baseline",
        "observed": "Observed",
        "severity": "Severity",
        "run_dir": "Run",
    })
    st.dataframe(df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Footer + auto-refresh
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    f"Page rendered at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — "
    f"refreshing in {cfg.refresh_seconds}s"
)

# Streamlit-native periodic refresh (no user interaction needed)
time.sleep(cfg.refresh_seconds)
st.rerun()