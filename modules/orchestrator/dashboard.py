"""
Live dashboard — reads the latest run directory and writes a JSON +
HTML view of the pipeline status.
"""
import json
from datetime import datetime
from pathlib import Path


def build_dashboard(run_dir: Path, extra: dict = None) -> dict:
    """Assemble the dashboard payload from a run directory."""
    run_dir = Path(run_dir)
    payload = {
        "run_dir": str(run_dir),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stages": {},
        "summary": {},
    }

    # --- infra stage ---
    inf = run_dir / "infrastructure.json"
    if inf.exists():
        payload["stages"]["infrastructure"] = json.load(inf.open())

    # --- detection stage ---
    det = run_dir / "detection.json"
    if det.exists():
        payload["stages"]["detection"] = json.load(det.open())

    # --- snapshot stage ---
    clean = run_dir / "clean_snapshot.json"
    dirty = run_dir / "dirty_snapshot.json"
    payload["stages"]["snapshot"] = {
        "clean": str(clean) if clean.exists() else None,
        "dirty": str(dirty) if dirty.exists() else None,
    }

    # --- diff stage ---
    comp = run_dir / "comparison.json"
    if comp.exists():
        data = json.load(comp.open())
        payload["stages"]["comparison"] = {
            "total_changes": data.get("total_changes", 0),
            "by_severity": data.get("changes_by_severity", {}),
            "by_area": data.get("changes_by_area", {}),
        }
        payload["summary"]["total_changes"] = data.get("total_changes", 0)
        payload["summary"]["severity"] = data.get("changes_by_severity", {})

    # --- report stage ---
    pdf = run_dir / "comparison.pdf"
    payload["stages"]["report"] = {
        "json": str(comp) if comp.exists() else None,
        "pdf": str(pdf) if pdf.exists() else None,
    }

    if extra:
        payload.update(extra)

    # --- write dashboard ---
    (run_dir / "dashboard.json").write_text(json.dumps(payload, indent=2))

    # --- simple HTML view ---
    html = _render_html(payload)
    (run_dir / "dashboard.html").write_text(html)

    return payload


def _render_html(p: dict) -> str:
    rows = ""
    for stage, val in p["stages"].items():
        rows += f"<tr><td><b>{stage}</b></td><td><pre>{json.dumps(val, indent=2)[:500]}</pre></td></tr>"

    severity = p.get("summary", {}).get("severity", {})
    sev_badge = " ".join(
        f"<span class='badge {k}'>{k}: {v}</span>"
        for k, v in severity.items() if v
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>RTO Eradication — Dashboard</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 30px; background: #0f172a; color: #e2e8f0; }}
 h1   {{ color: #38bdf8; }}
 table{{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
 td   {{ border: 1px solid #334155; padding: 8px; vertical-align: top; }}
 pre  {{ background: #1e293b; padding: 8px; border-radius: 4px; font-size: 11px; max-height: 200px; overflow: auto; }}
 .badge {{ display:inline-block; padding: 3px 8px; border-radius: 4px; margin-right: 6px; font-size: 12px; }}
 .badge.critical {{ background: #dc2626; }}
 .badge.high     {{ background: #ea580c; }}
 .badge.medium   {{ background: #ca8a04; }}
 .badge.low      {{ background: #0d9488; }}
 .meta   {{ color: #94a3b8; font-size: 13px; }}
</style>
</head>
<body>
<h1>RTO Eradication — Live Dashboard</h1>
<p class="meta">Run: {p['run_dir']} &nbsp;|&nbsp; Updated: {p['updated_at']}</p>
<p>Total changes: <b>{p.get('summary', {}).get('total_changes', 0)}</b></p>
<p>{sev_badge}</p>
<table>
 <tr><th>Stage</th><th>Details</th></tr>
 {rows}
</table>
</body>
</html>"""