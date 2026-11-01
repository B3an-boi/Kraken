"""Candle helpers: a quick chart read (pattern + 0-100 score) and tight-range detection."""
from __future__ import annotations


def chart_read(cs):
    """Six numbers → a named pattern and a 0-100 chart score with the reasons behind it."""
    C = [x["c"] for x in cs]; V = [x["v"] for x in cs]; N = len(C)
    mean = lambda a: sum(a) / len(a) if a else 0.0
    m9, m21 = mean(C[-9:]), mean(C[-21:])
    trend = "up" if m9 > m21 else "down" if m9 < m21 else "flat"
    base = mean(C[-24:-19]) if N >= 24 else C[0]
    slope = ((mean(C[-5:]) if N >= 24 else C[-1]) - base) / base if base else None
    vol = mean([(x["h"] - x["l"]) / x["c"] for x in cs[-14:]])
    hi, lo = max(x["h"] for x in cs), min(x["l"] for x in cs)
    dd = (hi - C[-1]) / hi
    vavg = mean(V[-21:-1])
    vr = V[-1] / vavg if vavg else None
    ufl = (C[-1] - lo) / lo if lo else None
    s = slope if slope is not None else 0.0
    if s > 0.25 and dd < 0.12: pat = "Vertical run-up"
    elif s > 0.08 and dd < 0.25: pat = "Uptrend channel"
    elif dd > 0.55 and s < -0.10: pat = "Breakdown"
    elif dd > 0.55 and s > 0.02: pat = "Bounce off the lows"
    elif dd > 0.35 and abs(s) < 0.08: pat = "Distribution at highs"
    elif s < -0.20: pat = "Slow bleed"
    elif abs(s) < 0.05 and vol < 0.05 and ufl is not None and ufl < 0.20: pat = "Basing at lows"
    elif abs(s) < 0.08 and vol > 0.08: pat = "Wide chop"
    else: pat = {"up": "Bullish consolidation", "down": "Bearish consolidation"}.get(trend, "Sideways consolidation")
    score, why = 50, []
    def add(d, w): nonlocal score; score += d; why.append(f"{d:+d} {w}")
    if trend == "up": add(12, "9-bar avg above 21-bar avg")
    elif trend == "down": add(-12, "9-bar avg below 21-bar avg")
    if slope is not None:
        if slope > 0.15: add(15, f"last 20 bars up {slope:+.0%}")
        elif slope > 0.02: add(6, f"mild uptrend {slope:+.0%}")
        elif slope < -0.15: add(-15, f"last 20 bars down {slope:+.0%}")
        elif slope < -0.02: add(-6, f"slow bleed {slope:+.0%}")
    green = cs[-1]["c"] >= cs[-1]["o"]
    if vr is not None:
        if vr > 3: add(8 if green else -10, f"last bar {vr:.1f}x volume, {'green' if green else 'red'}")
        elif vr < 0.3: add(-5, "volume fading")
    if dd > 0.60: add(-15, f"down {dd:.0%} from range high")
    elif dd > 0.30: add(-6, f"down {dd:.0%} from range high")
    elif dd < 0.05: add(8, "at the range high")
    if N > 40 and max(C[-20:]) > max(C[-40:-20]) * 1.02 and mean(V[-20:]) < mean(V[-40:-20]) * 0.7:
        add(-10, "new high on shrinking volume")
    return dict(pattern=pat, score=max(0, min(100, score)), why=why, trend=trend,
                slope=slope, volatility=vol, drawdown=dd, vol_ratio=vr, up_from_low=ufl)



def find_tight_range(cs, min_len: int, max_range: float):
    """Longest trailing window whose (top-low)/mid stays within max_range ("Any tight range" setup).
    cs are 1-minute candles. Returns None if the window is shorter than min_len bars."""
    n = len(cs)
    need = min(min_len, 100)                       # a 1m window is ~2h, so cap the requirement
    if n < need + 5:
        return None
    hi = lo = None
    k = 0
    for i in range(n - 1, -1, -1):
        h, l = cs[i]["h"], cs[i]["l"]
        nh = h if hi is None else max(hi, h)
        nl = l if lo is None else min(lo, l)
        if (nh - nl) / ((nh + nl) / 2) > max_range:
            break
        hi, lo, k = nh, nl, k + 1
    if k < need:
        return None
    base, pre = cs[n - k:], cs[:n - k]
    mean = lambda a: sum(a) / len(a) if a else 0.0
    bvol, pvol = mean([x["v"] for x in base]), mean([x["v"] for x in pre])
    pre_hi = max((x["h"] for x in pre), default=hi)
    last = cs[-1]["c"]
    atr = mean([x["h"] - x["l"] for x in base[-14:]])
    return dict(length=k, top=hi, low=lo, range=(hi - lo) / ((hi + lo) / 2), last=last,
                pos=(last - lo) / (hi - lo) if hi > lo else 0.5,
                pullback=(pre_hi - (hi + lo) / 2) / pre_hi if pre_hi > hi else 0.0,
                bar_usd=bvol, quiet=(bvol < pvol) if pre else True,
                wake=mean([x["v"] for x in base[-5:]]) / bvol if bvol else 0.0,
                broken=last > hi * 1.03, atr=atr, start_ts=base[0]["t"],
                dip_entry=min(x["l"] for x in base[-20:]) + 0.2 * atr,
                breakout_entry=max(x["h"] for x in base[-20:]) * 1.01)


def spark(cs, max_points=150):
    """Downsampled [close, high, low] triples for a thumbnail chart."""
    if not cs:
        return []
    step = max(1, -(-len(cs) // max_points))
    out = []
    for i in range(0, len(cs), step):
        w = cs[i:i + step]
        out.append([w[-1]["c"], max(x["h"] for x in w), min(x["l"] for x in w)])
    return out
