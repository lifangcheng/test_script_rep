from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Tuple

import ast

import numpy as np
import pandas as pd

from core.types import Anomaly, CoreResult


def _severity(score: float) -> str:
    if score >= 0.9:
        return "critical"
    if score >= 0.6:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.And,
    ast.Or,
    ast.Not,
    ast.UAdd,
    ast.USub,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.Eq,
    ast.NotEq,
    ast.In,
    ast.NotIn,
    ast.List,
    ast.Tuple,
)


def _compile_condition(expr: str):
    expr = expr.strip()

    def _prefix_comparisons(s: str) -> str:
        tokens = s.split()
        out: list[str] = []
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t in {">", ">=", "<", "<=", "==", "!="}:
                out.append("value")
                out.append(t)
            else:
                out.append(t)
            i += 1
        return " ".join(out)

    expr = _prefix_comparisons(expr)
    parsed = ast.parse(expr, mode="eval")
    for node in ast.walk(parsed):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(f"unsupported syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id != "value":
            raise ValueError(f"unsupported name: {node.id}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool, type(None))):
            raise ValueError("unsupported constant")

    code = compile(parsed, "<condition>", "eval")

    def _pred(value: float) -> bool:
        return bool(eval(code, {"__builtins__": {}}, {"value": value}))

    return _pred


def _segments(mask: np.ndarray, ts: np.ndarray, *, min_points: int) -> List[Tuple[int, int]]:
    segs: List[Tuple[int, int]] = []
    start: int | None = None
    for i, hit in enumerate(mask.tolist()):
        if hit and start is None:
            start = i
        elif (not hit) and start is not None:
            if i - start >= min_points:
                segs.append((start, i - 1))
            start = None
    if start is not None and len(mask) - start >= min_points:
        segs.append((start, len(mask) - 1))
    return segs


def detect_anomalies(df: pd.DataFrame, *, config: Dict[str, Any], skills: List[Dict[str, Any]] | None = None) -> CoreResult:
    required = {"timestamp", "signal", "value", "can_id"}
    if not required.issubset(df.columns):
        return CoreResult(
            ok=False,
            error={
                "code": "schema_mismatch",
                "message": f"Input df missing columns: {sorted(required - set(df.columns))}",
                "fix": "Ensure decode output matches unified schema.",
            },
        )

    cfg = config.get("anomaly", {}) if isinstance(config, dict) else {}
    period_tol = float(cfg.get("period_tol", 0.2))
    spike_z = float(cfg.get("spike_z", 6.0))
    freeze_min_points = int(cfg.get("freeze_min_points", 10))
    freeze_enabled = bool(cfg.get("freeze_enabled", True))  # allow disabling freeze detection entirely

    fallback_cfg = config.get("fallback", {}) if isinstance(config, dict) else {}
    variance_z = float(fallback_cfg.get("variance_z", 6.0))
    timeout_mul = float(fallback_cfg.get("timeout_multiplier", 3.0))
    uds_services = fallback_cfg.get("uds_service_ids", [0x19]) or []
    keyword_signals = [str(x).lower() for x in fallback_cfg.get("keyword_signals", ["flt", "warn", "status"])]

    window_cfg = config.get("slice", {}) if isinstance(config, dict) else {}
    window_sec = float(window_cfg.get("window_sec", 2.0))
    window_format = str(window_cfg.get("format", "csv"))
    max_rows = int(window_cfg.get("max_rows", 500))
    min_points = int(window_cfg.get("min_points", 5))

    anomalies: List[Anomaly] = []
    slices: Dict[str, Any] = {}

    for (can_id, signal), g in df.sort_values("timestamp").groupby(["can_id", "signal"], dropna=False):
        sig_lower = str(signal).lower()
        is_keyword_signal = any(k in sig_lower for k in keyword_signals)

        # Skill rules hint: if skills provided, mark matches to whitelist anomaly candidates
        skill_hits = []
        if skills:
            for r in skills:
                if r.get("can_id") is not None and int(r["can_id"]) != int(can_id):
                    continue
                sig_match = r.get("signal") or r.get("signal_name")
                if sig_match and str(sig_match) != str(signal):
                    continue
                skill_hits.append(r)

        def _primary_rule_meta(rules: list[dict] | None):
            if not rules:
                return None, None, None, None
            r0 = rules[0]
            cond = None
            trig = r0.get("trigger")
            if isinstance(trig, dict):
                cond = trig.get("condition")
                if cond is None:
                    cond = trig.get("note")
            return r0.get("source"), r0.get("id"), (r0.get("skill_name") or r0.get("name")), cond
        ts = g["timestamp"].to_numpy(dtype=float)
        vals = g["value"].to_numpy()

        # rule triggers
        if skill_hits:
            for r in skill_hits:
                trig = r.get("trigger") if isinstance(r, dict) else None
                cond = trig.get("condition") if isinstance(trig, dict) else None
                if not cond:
                    continue
                min_points = int(trig.get("min_points", 1)) if isinstance(trig, dict) else 1
                try:
                    pred = _compile_condition(str(cond))
                except Exception:
                    continue

                mask = np.array([
                    isinstance(v, (int, float, np.number)) and np.isfinite(float(v)) and pred(float(v)) for v in vals
                ], dtype=bool)
                for a0, a1 in _segments(mask, ts, min_points=min_points):
                    anomalies.append(
                        Anomaly(
                            kind="rule_trigger",
                            severity=str(r.get("severity") or "high"),
                            signal=str(signal),
                            can_id=int(can_id),
                            start=float(ts[a0]),
                            end=float(ts[a1]),
                            count=int(a1 - a0 + 1),
                            evidence={"rule": {"id": r.get("id"), "name": r.get("skill_name") or r.get("name"), "condition": cond}},
                            rule_source=r.get("source"),
                            rule_id=r.get("id"),
                            rule_name=r.get("skill_name") or r.get("name"),
                            rule_condition=str(cond),
                        )
                    )

        # missing / period deviation
        if len(ts) >= 3:
            dts = np.diff(ts)
            med = float(np.median(dts)) if np.all(np.isfinite(dts)) else 0.0
            if med > 0:
                hi = med * (1.0 + period_tol)
                lo = med * (1.0 - period_tol)
                bad = np.where((dts > hi) | (dts < lo))[0]
                if bad.size:
                    anomalies.append(
                        Anomaly(
                            kind="period_deviation",
                            severity=_severity(min(1.0, bad.size / max(1, len(dts)))),
                            signal=str(signal),
                            can_id=int(can_id),
                            start=float(ts[int(bad[0])]),
                            end=float(ts[int(bad[-1] + 1)]),
                            count=int(bad.size),
                            evidence={"median_period": med, "tol": period_tol},
                            rule_source=(_primary_rule_meta(skill_hits)[0] if skill_hits else None),
                            rule_id=(_primary_rule_meta(skill_hits)[1] if skill_hits else None),
                            rule_name=(_primary_rule_meta(skill_hits)[2] if skill_hits else None),
                            rule_condition=(_primary_rule_meta(skill_hits)[3] if skill_hits else None),
                        )
                    )

                missing = np.where(dts > hi * 2.0)[0]
                if missing.size:
                    anomalies.append(
                        Anomaly(
                            kind="missing",
                            severity=_severity(min(1.0, missing.size / max(1, len(dts)))),
                            signal=str(signal),
                            can_id=int(can_id),
                            start=float(ts[int(missing[0])]),
                            end=float(ts[int(missing[-1] + 1)]),
                            count=int(missing.size),
                            evidence={"median_period": med, "threshold": hi * 2.0},
                            rule_source=(_primary_rule_meta(skill_hits)[0] if skill_hits else None),
                            rule_id=(_primary_rule_meta(skill_hits)[1] if skill_hits else None),
                            rule_name=(_primary_rule_meta(skill_hits)[2] if skill_hits else None),
                            rule_condition=(_primary_rule_meta(skill_hits)[3] if skill_hits else None),
                        )
                    )

        # numeric-only checks
        num_mask = np.array([isinstance(v, (int, float, np.number)) and np.isfinite(float(v)) for v in vals])
        if not np.any(num_mask):
            continue

        vnum = vals[num_mask].astype(float)
        tnum = ts[num_mask]

        # spike (zscore)
        if len(vnum) >= 10:
            mu = float(np.mean(vnum))
            sd = float(np.std(vnum))
            if sd > 0:
                z = np.abs((vnum - mu) / sd)
                idx = np.where(z >= spike_z)[0]
                if idx.size:
                    anomalies.append(
                        Anomaly(
                            kind="spike",
                            severity=_severity(min(1.0, float(np.max(z)) / (spike_z * 2.0))),
                            signal=str(signal),
                            can_id=int(can_id),
                            start=float(tnum[int(idx[0])]),
                            end=float(tnum[int(idx[-1])]),
                            count=int(idx.size),
                            evidence={"mean": mu, "std": sd, "spike_z": spike_z, "max_z": float(np.max(z))},
                            rule_source=(_primary_rule_meta(skill_hits)[0] if skill_hits else None),
                            rule_id=(_primary_rule_meta(skill_hits)[1] if skill_hits else None),
                            rule_name=(_primary_rule_meta(skill_hits)[2] if skill_hits else None),
                            rule_condition=(_primary_rule_meta(skill_hits)[3] if skill_hits else None),
                        )
                    )

        # freeze
        if freeze_enabled and len(vnum) >= freeze_min_points:
            # longest run of equal values
            run_start = 0
            best: Tuple[int, int] = (0, 0)
            for i in range(1, len(vnum)):
                if vnum[i] != vnum[i - 1]:
                    if i - run_start > best[1] - best[0]:
                        best = (run_start, i)
                    run_start = i
            if len(vnum) - run_start > best[1] - best[0]:
                best = (run_start, len(vnum))
            if best[1] - best[0] >= freeze_min_points:
                anomalies.append(
                    Anomaly(
                        kind="freeze",
                        severity=_severity(min(1.0, (best[1] - best[0]) / max(1, len(vnum)))),
                        signal=str(signal),
                        can_id=int(can_id),
                        start=float(tnum[best[0]]),
                        end=float(tnum[best[1] - 1]),
                        count=int(best[1] - best[0]),
                        evidence={"value": float(vnum[best[0]]), "min_points": freeze_min_points},
                        rule_source=skill_hits[0].get("source") if skill_hits else None,
                    )
                )

        # out_of_range (from config ranges)
        ranges = cfg.get("ranges", {})
        r = ranges.get(str(signal)) if isinstance(ranges, dict) else None
        if isinstance(r, dict) and ("min" in r or "max" in r):
            mn = r.get("min", -np.inf)
            mx = r.get("max", np.inf)
            idx = np.where((vnum < float(mn)) | (vnum > float(mx)))[0]
            if idx.size:
                anomalies.append(
                    Anomaly(
                        kind="out_of_range",
                        severity=_severity(min(1.0, idx.size / max(1, len(vnum)))),
                        signal=str(signal),
                        can_id=int(can_id),
                        start=float(tnum[int(idx[0])]),
                        end=float(tnum[int(idx[-1])]),
                        count=int(idx.size),
                        evidence={"min": mn, "max": mx, "examples": vnum[idx[:5]].tolist()},
                        rule_source=skill_hits[0].get("source") if skill_hits else None,
                    )
                )

        # enum_invalid (from config enums)
        enums = cfg.get("enums", {})
        allowed = enums.get(str(signal)) if isinstance(enums, dict) else None
        if isinstance(allowed, list):
            s = set(allowed)
            idx = np.where(~np.isin(vnum, list(s)))[0]
            if idx.size:
                anomalies.append(
                    Anomaly(
                        kind="enum_invalid",
                        severity=_severity(min(1.0, idx.size / max(1, len(vnum)))),
                        signal=str(signal),
                        can_id=int(can_id),
                        start=float(tnum[int(idx[0])]),
                        end=float(tnum[int(idx[-1])]),
                        count=int(idx.size),
                        evidence={"allowed": allowed, "examples": vnum[idx[:5]].tolist()},
                        rule_source=skill_hits[0].get("source") if skill_hits else None,
                    )
                )

    # attach window slices for each anomaly
    def capture_slice(group_df: pd.DataFrame, center_ts: float) -> pd.DataFrame:
        # ensure at least min_points; if not enough, expand to window_sec bounds and min 2s
        window_bound = max(window_sec, 2.0)
        if len(group_df) >= min_points:
            start_ts = center_ts - window_bound
            end_ts = center_ts + window_bound
        else:
            # fallback: double window
            start_ts = center_ts - window_bound
            end_ts = center_ts + window_bound
        return group_df[(group_df["timestamp"] >= start_ts) & (group_df["timestamp"] <= end_ts)].copy()

    enriched: List[Dict[str, Any]] = []
    for a in anomalies:
        center_ts = float(a.start)
        grp = df[(df["can_id"] == a.can_id) & (df["signal"] == a.signal)]
        slice_df = capture_slice(grp, center_ts)
        if max_rows and len(slice_df) > max_rows:
            slice_df = slice_df.iloc[:max_rows]
        if window_format == "json":
            context_data = slice_df.to_dict(orient="records")
        else:
            context_data = slice_df.to_csv(index=False)
        slice_id = f"{a.signal}_{a.can_id}_{int(a.start)}"
        slices[slice_id] = {
            "context_data": context_data,
            "format": window_format,
            "window_sec": window_sec,
        }
        item = asdict(a)
        item["slice_id"] = slice_id
        enriched.append(item)

    payload = {"anomalies": enriched, "slices": slices}
    return CoreResult(ok=True, value=payload)
