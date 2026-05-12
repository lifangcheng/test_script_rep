from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import plotly.express as px

from core.types import CoreResult
from utils.io import write_json


def _now_iso() -> str:
    # Keep report generation deterministic by default.
    # If you need wall-clock time, add it via config and plumb through here.
    return "1970-01-01T00:00:00Z"


def build_report_json(
    *,
    decoded_df: pd.DataFrame,
    anomalies: List[Dict[str, Any]],
    diagnosis: Dict[str, Any],
    ai_report: Dict[str, Any] | None = None,
    base_ts: float | None = None,
    base_iso: str | None = None,
) -> Dict[str, Any]:
    time_range = {
        "start": float(decoded_df["timestamp"].min()) if not decoded_df.empty else None,
        "end": float(decoded_df["timestamp"].max()) if not decoded_df.empty else None,
    }

    def _to_iso(ts: float | None) -> str | None:
        if ts is None:
            return None
        try:
            # If it's already an absolute unix timestamp, use it directly.
            if base_ts is None or float(ts) > 1_000_000_000:
                return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
            return datetime.fromtimestamp(base_ts + float(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            return None

    time_range_iso = {"start_iso": _to_iso(time_range["start"]), "end_iso": _to_iso(time_range["end"])}

    # enrich anomalies with iso times if available
    enriched_anomalies: List[Dict[str, Any]] = []
    for a in anomalies:
        a_copy = dict(a)
        a_copy["start_iso"] = _to_iso(a.get("start")) if isinstance(a.get("start"), (int, float)) else None
        a_copy["end_iso"] = _to_iso(a.get("end")) if isinstance(a.get("end"), (int, float)) else None
        if isinstance(a_copy.get("can_id"), int):
            a_copy["can_id_hex"] = hex(a_copy["can_id"])
            del a_copy["can_id"]
        enriched_anomalies.append(a_copy)

    # enrich ai_report per_anomaly with iso times
    if ai_report and isinstance(ai_report, dict):
        per = ai_report.get("per_anomaly")
        if isinstance(per, list):
            new_per = []
            for item in per:
                item_copy = dict(item)
                anom = dict(item_copy.get("anomaly") or {})
                start_iso = _to_iso(anom.get("start")) if isinstance(anom.get("start"), (int, float)) else None
                end_iso = _to_iso(anom.get("end")) if isinstance(anom.get("end"), (int, float)) else None
                if start_iso or end_iso:
                    anom["start_iso"] = start_iso
                    anom["end_iso"] = end_iso
                item_copy["anomaly"] = anom
                new_per.append(item_copy)
            ai_report = dict(ai_report)
            ai_report["per_anomaly"] = new_per

    return {
        "generated_at": _now_iso(),
        "base_time": {"unix": base_ts, "iso": base_iso},
        "time_range": time_range,
        "time_range_iso": time_range_iso,
        "stats": {
            "rows": int(len(decoded_df)),
            "signals": int(decoded_df["signal"].nunique()) if not decoded_df.empty else 0,
            "frames": int(decoded_df["can_id"].nunique()) if not decoded_df.empty else 0,
            "anomalies": int(len(anomalies)),
        },
        "diagnosis": diagnosis,
        "anomalies": enriched_anomalies,
        "ai_report": ai_report,
    }


def build_graph_html(decoded_df: pd.DataFrame, *, max_signals: int = 8) -> str:
    if decoded_df.empty:
        return "<html><body><h3>No data</h3></body></html>"

    # choose top signals by sample count
    top = (
        decoded_df.groupby("signal")["value"].count().sort_values(ascending=False).head(max_signals).index.tolist()
    )
    plot_df = decoded_df[decoded_df["signal"].isin(top)].copy()

    # keep only numeric values for plotly line
    plot_df["value_num"] = pd.to_numeric(plot_df["value"], errors="coerce")
    plot_df = plot_df.dropna(subset=["value_num"])

    if plot_df.empty:
        return "<html><body><h3>No numeric signals to plot</h3></body></html>"

    fig = px.line(
        plot_df,
        x="timestamp",
        y="value_num",
        color="signal",
        title="Top Signals Trend",
        labels={"value_num": "value"},
    )
    fig.update_layout(legend_title_text="signal", template="plotly_white")
    return fig.to_html(include_plotlyjs="cdn", full_html=True)


def build_report_html(report_json: Dict[str, Any]) -> str:
    stats = report_json.get("stats", {})
    diagnosis = report_json.get("diagnosis", {})
    anomalies = report_json.get("anomalies", [])
    ai_report = report_json.get("ai_report") or {}
    time_iso = report_json.get("time_range_iso", {})
    base_time = report_json.get("base_time", {})

    def _fmt_can_id(v: Any) -> str:
        try:
            return hex(int(v))
        except Exception:
            return str(v)

    rows = "".join(
        f"<tr><td>{a.get('kind')}</td><td>{a.get('severity')}</td><td>{a.get('signal')}</td><td>{(a.get('can_id_hex') or _fmt_can_id(a.get('can_id')))}</td>"
        f"<td>{a.get('start')}</td><td>{a.get('end')}</td><td>{a.get('count')}</td>"
        f"<td>{(a.get('rule_name') or a.get('rule_id') or '')}</td>"
        f"<td>{a.get('start_iso')}</td><td>{a.get('end_iso')}</td>"
        f"</tr>"
        for a in anomalies
    )

    ai_rows = ""
    if isinstance(ai_report, dict) and "per_anomaly" in ai_report:
        ai_rows = "".join(
            f"<tr><td>{item.get('anomaly', {}).get('signal')}</td><td>{item.get('anomaly', {}).get('kind')}</td>"
            f"<td><pre>{json.dumps(item.get('analysis', {}), ensure_ascii=False, indent=2)}</pre></td></tr>"
            for item in ai_report.get("per_anomaly", [])
        )

    return f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>CAN Analysis Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    .card {{ border: 1px solid #eee; padding: 12px; border-radius: 8px; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 12px; }}
    th {{ background: #fafafa; text-align: left; }}
  </style>
</head>
<body>
  <h2>CAN Analysis Report</h2>
  <div class=\"card\">
    <div><b>Generated:</b> {report_json.get('generated_at')}</div>
    <div><b>Rows:</b> {stats.get('rows')}</div>
    <div><b>Signals:</b> {stats.get('signals')}</div>
    <div><b>Frames:</b> {stats.get('frames')}</div>
    <div><b>Anomalies:</b> {stats.get('anomalies')}</div>
  </div>

  <div class=\"card\">
    <h3>Diagnosis Summary</h3>
    <pre>{json.dumps(diagnosis, ensure_ascii=False, indent=2)}</pre>
  </div>

  <div class=\"card\">
    <h3>Anomalies</h3>
    <table>
      <thead>
        <tr><th>kind</th><th>severity</th><th>signal</th><th>can_id(hex)</th><th>start</th><th>end</th><th>count</th><th>rule</th><th>start(UTC)</th><th>end(UTC)</th></tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>

  <div class=\"card\">
    <h3>AI Analysis (per anomaly)</h3>
    <table>
      <thead>
        <tr><th>signal</th><th>anomaly</th><th>analysis</th></tr>
      </thead>
      <tbody>
        {ai_rows if ai_rows else '<tr><td colspan="3">No AI analysis</td></tr>'}
      </tbody>
    </table>
  </div>

  <div class=\"card\">
    <h3>Graph</h3>
    <p>Open <code>graph.html</code> for interactive charts.</p>
  </div>
</body>
</html>"""


def generate_reports(
    *,
    output_dir: str,
    decoded_df: pd.DataFrame,
    anomalies: List[Dict[str, Any]],
    diagnosis: Dict[str, Any],
    ai_report: Dict[str, Any] | None = None,
    base_ts: float | None = None,
    base_iso: str | None = None,
) -> CoreResult:
    try:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        report_json = build_report_json(
            decoded_df=decoded_df,
            anomalies=anomalies,
            diagnosis=diagnosis,
            ai_report=ai_report,
            base_ts=base_ts,
            base_iso=base_iso,
        )
        write_json(str(out / "report.json"), report_json)

        # ai_report standalone
        if ai_report is not None:
            write_json(str(out / "ai_report.json"), ai_report)

        report_html = build_report_html(report_json)
        (out / "report.html").write_text(report_html, encoding="utf-8")

        graph_html = build_graph_html(decoded_df)
        (out / "graph.html").write_text(graph_html, encoding="utf-8")

        return CoreResult(ok=True, value={"report_path": str(out / "report.html")})
    except Exception as e:  # noqa: BLE001
        return CoreResult(
            ok=False,
            error={
                "code": "report_generate_failed",
                "message": f"Failed to generate report: {e}",
                "fix": "Check output directory permissions and dependencies (plotly).",
            },
        )
