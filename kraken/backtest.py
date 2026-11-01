"""Learning stats from labeled Base Hunter snapshots: win rate by bucket and 'what-if' filters, so
settings can be tuned from your own results instead of guesses."""
from __future__ import annotations
import math

BUCKETS = {
    "score": ("Rule score", lambda s, x: s.get("rule", 0), [0, 30, 45, 60, 75, 101], "{:.0f}"),
    "base_range": ("Base range", lambda s, x: x.get("base_range", 0), [0, 0.06, 0.10, 0.14, 0.20, 9], "pct"),
    "base_len": ("Base length (min)", lambda s, x: x.get("base_len", 0), [0, 60, 120, 240, 480, 1e9], "{:.0f}"),
    "pump_x": ("Launch pump ×", lambda s, x: 10 ** x.get("pump_x_log", 0), [0, 2.5, 5, 10, 25, 1e9], "{:.1f}"),
    "retrace": ("Retrace", lambda s, x: x.get("retrace", 0), [0, 0.6, 0.75, 0.85, 0.92, 1.01], "pct"),
    "vol_decay": ("Base vol / pump vol", lambda s, x: x.get("vol_decay", 1), [0, 0.05, 0.1, 0.2, 0.3, 9], "pct"),
    "flow": ("Smart-money net $ in base", lambda s, x: math.copysign(10 ** abs(x.get("flow_in_base", 0)) - 1, x.get("flow_in_base", 0)),
             [-1e12, -1, 1, 1000, 10000, 1e12], "{:,.0f}"),
}


def _fmt(v, f):
    if f == "pct":
        return f"{v * 100:.0f}%"
    return f.format(v) if abs(v) < 1e8 else "∞"


def _win(lab: dict, tp, sl, base_tp, base_sl):
    if abs(tp - base_tp) < 1e-9 and abs(sl - base_sl) < 1e-9:
        return lab["win"]
    up, dd = lab.get("max_up") or 0, lab.get("max_dd") or 0
    return int(up >= tp and dd < sl)          # approximate: order of touches inside the window is unknown


def run(labeled: list, label_rule: dict, f: dict | None = None) -> dict:
    f = f or {}
    tp = float(f.get("tp") or label_rule["tp"])
    sl = float(f.get("sl") or label_rule["sl"])
    keep = []
    for s, l in labeled:
        x = s.get("x") or {}
        if f.get("min_score") is not None and s.get("rule", 0) < float(f["min_score"]):
            continue
        if f.get("max_range") is not None and x.get("base_range", 0) > float(f["max_range"]):
            continue
        if f.get("min_base_len") is not None and x.get("base_len", 0) < float(f["min_base_len"]):
            continue
        if f.get("min_pump") is not None and 10 ** x.get("pump_x_log", 0) < float(f["min_pump"]):
            continue
        if f.get("min_retrace") is not None and x.get("retrace", 0) < float(f["min_retrace"]):
            continue
        if f.get("max_vol_ratio") is not None and x.get("vol_decay", 1) > float(f["max_vol_ratio"]):
            continue
        keep.append((s, l, _win(l, tp, sl, label_rule["tp"], label_rule["sl"])))
    n = len(keep)
    wins = sum(w for *_, w in keep)
    ev = sum((tp if w else -min(sl, l.get("max_dd") or sl)) for _, l, w in keep) / n if n else None
    out = dict(n=n, total=len(labeled), wins=wins, win_rate=wins / n if n else None, avg_outcome=ev,
               approx=not (abs(tp - label_rule["tp"]) < 1e-9 and abs(sl - label_rule["sl"]) < 1e-9),
               tp=tp, sl=sl, buckets={})
    for key, (label, get, edges, fmt) in BUCKETS.items():
        rows = []
        for lo, hi in zip(edges, edges[1:]):
            grp = [w for s, l, w in keep if lo <= get(s, s.get("x") or {}) < hi]
            if grp:
                rows.append(dict(range=f"{_fmt(lo, fmt)} – {_fmt(hi, fmt)}", n=len(grp), win_rate=sum(grp) / len(grp)))
        out["buckets"][key] = dict(label=label, rows=rows)
    return out
