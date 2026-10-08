"""
Snapshot comparison and report generation.

Loads a 'clean' and a 'dirty' snapshot (from Task 6's capture format),
compares byte-by-byte, rates each change's severity, and exports a
report as JSON and PDF.
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Severity model
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

# Byte offset -> (register name, severity, description)
# OpenPLC maps %MWn to bytes n*2 and n*2+1 (INT = 2 bytes, big-endian)
SEVERITY_MAP = {
    "DB1": {
        (0, 1):   ("MW0 - MotorCmd",     "critical", "Motor control flag"),
        (2, 3):   ("MW1 - SpeedSet",     "high",     "T1 timer preset (belt speed)"),
        (4, 5):   ("MW2 - TimerVal",     "low",      "T1 elapsed (runtime value)"),
        (6, 7):   ("MW3 - BagCount",     "medium",   "C1 bag counter"),
        (8, 9):   ("MW4 - StatusReg",    "critical", "Status bitfield (running/timer/bag)"),
        (10, 11): ("MW5 - BagSensor",    "low",      "Bag sensor input"),
    },
    "DB2": {},        # no known mapping — default severity applies
    "Merker": {},     # no known mapping — default severity applies
}

DEFAULT_SEVERITY = "medium"


def _classify(area: str, offset: int) -> tuple:
    """Return (register_label, severity, description) for a byte offset."""
    area_map = SEVERITY_MAP.get(area, {})
    # offsets are grouped in pairs (INT = 2 bytes)
    pair_start = (offset // 2) * 2
    for (lo, hi), info in area_map.items():
        if lo <= offset <= hi:
            return info
    return (f"{area}[{offset}]", DEFAULT_SEVERITY, "Unmapped byte")


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------

@dataclass
class Change:
    area: str
    offset: int
    register: str
    description: str
    severity: str
    old_value: int
    new_value: int
    difference: int


@dataclass
class ComparisonReport:
    timestamp: str
    clean_file: str
    dirty_file: str
    clean_timestamp: str
    dirty_timestamp: str
    plc_ip: str
    total_changes: int
    changes_by_severity: dict
    changes_by_area: dict
    changes: list = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def _pair_iter(a: list, b: list):
    """Yield (offset, a_val, b_val) for the shorter of the two lists."""
    for i, (x, y) in enumerate(zip(a, b)):
        yield i, x, y


def compare_snapshots(clean_file: str, dirty_file: str) -> ComparisonReport:
    """
    Load two snapshots and return a ComparisonReport.
    """
    with open(clean_file) as f:
        clean = json.load(f)
    with open(dirty_file) as f:
        dirty = json.load(f)

    changes: list[Change] = []
    changes_by_severity = {k: 0 for k in SEVERITY_ORDER}
    changes_by_area = {}

    clean_areas = clean.get("areas", {})
    dirty_areas = dirty.get("areas", {})

    for area in clean_areas:
        c_bytes = clean_areas[area] or []
        d_bytes = dirty_areas.get(area) or []
        changes_by_area[area] = 0

        for offset, c_val, d_val in _pair_iter(c_bytes, d_bytes):
            if c_val == d_val:
                continue

            register, severity, description = _classify(area, offset)

            changes.append(Change(
                area=area,
                offset=offset,
                register=register,
                description=description,
                severity=severity,
                old_value=c_val,
                new_value=d_val,
                difference=d_val - c_val,
            ))
            changes_by_severity[severity] = changes_by_severity.get(severity, 0) + 1
            changes_by_area[area] += 1

    report = ComparisonReport(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        clean_file=str(Path(clean_file).name),
        dirty_file=str(Path(dirty_file).name),
        clean_timestamp=clean.get("timestamp", "?"),
        dirty_timestamp=dirty.get("timestamp", "?"),
        plc_ip=clean.get("plc_ip", dirty.get("plc_ip", "?")),
        total_changes=len(changes),
        changes_by_severity=changes_by_severity,
        changes_by_area=changes_by_area,
        changes=changes,
    )
    return report


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

def export_json(report: ComparisonReport, path: str) -> str:
    """Write the report to JSON."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        json.dump(report.to_dict(), f, indent=2)
    return str(out)


def export_pdf(report: ComparisonReport, path: str) -> str:
    """Write the report to PDF using reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    mono = ParagraphStyle("Mono", parent=body, fontName="Courier", fontSize=8)

    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="Snapshot Comparison Report",
    )

    story = []
    story.append(Paragraph("Snapshot Comparison Report", h1))
    story.append(Spacer(1, 4 * mm))

    # --- Meta table ---
    meta = [
        ["Comparison time", report.timestamp],
        ["Clean snapshot",  f"{report.clean_file}  ({report.clean_timestamp})"],
        ["Dirty snapshot",  f"{report.dirty_file}  ({report.dirty_timestamp})"],
        ["PLC IP",          report.plc_ip],
        ["Total changes",   str(report.total_changes)],
    ]
    t = Table(meta, colWidths=[45 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f7")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    # --- Summary by severity ---
    story.append(Paragraph("Summary by Severity", h2))
    sev_rows = [["Severity", "Count"]]
    for sev in ("critical", "high", "medium", "low", "info"):
        sev_rows.append([sev.upper(), str(report.changes_by_severity.get(sev, 0))])
    st = Table(sev_rows, colWidths=[40 * mm, 30 * mm])
    st.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe5f1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(st)
    story.append(Spacer(1, 6 * mm))

    # --- Summary by area ---
    story.append(Paragraph("Summary by Area", h2))
    area_rows = [["Area", "Changes"]]
    for area, count in report.changes_by_area.items():
        area_rows.append([area, str(count)])
    at = Table(area_rows, colWidths=[40 * mm, 30 * mm])
    at.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe5f1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(at)
    story.append(PageBreak())

    # --- Detailed changes ---
    story.append(Paragraph("Detailed Changes", h2))
    story.append(Spacer(1, 2 * mm))

    if not report.changes:
        story.append(Paragraph("No changes detected — snapshots are identical.", body))
    else:
        header = ["Area", "Off", "Register", "Sev", "Old", "New", "Δ"]
        rows = [header]
        for ch in report.changes:
            rows.append([
                ch.area,
                str(ch.offset),
                ch.register,
                ch.severity[0].upper(),
                f"{ch.old_value:#04x}",
                f"{ch.new_value:#04x}",
                f"{ch.difference:+d}",
            ])
        tt = Table(rows, colWidths=[16 * mm, 12 * mm, 55 * mm, 10 * mm, 18 * mm, 18 * mm, 14 * mm],
                   repeatRows=1)
        tt.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe5f1")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Courier"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f7f9fc")]),
        ]))
        story.append(tt)

    doc.build(story)
    return str(out)

    # ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Compare two PLC snapshots and export a report."
    )
    p.add_argument("clean", help="Path to clean snapshot JSON")
    p.add_argument("dirty", help="Path to dirty snapshot JSON")
    p.add_argument("--out-dir", default="output", help="Output directory")
    args = p.parse_args()

    report = compare_snapshots(args.clean, args.dirty)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = Path(args.out_dir) / f"comparison_{stamp}.json"
    pdf_path  = Path(args.out_dir) / f"comparison_{stamp}.pdf"

    export_json(report, str(json_path))
    export_pdf(report, str(pdf_path))

    print(f"Total changes : {report.total_changes}")
    for sev, n in report.changes_by_severity.items():
        if n:
            print(f"  {sev:8s} {n}")
    print(f"JSON report   : {json_path}")
    print(f"PDF report    : {pdf_path}")