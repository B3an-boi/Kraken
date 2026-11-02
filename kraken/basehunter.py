"""
basehunter.py — Base Hunter: find coins resting in a tight range after their first pump, and learn
from what happened next.

Pure logic only (no gmgn-cli, no FastAPI): kraken.hunter feeds it rows / candles / trades and
kraken.server wires the background loops. Everything here is deterministic and testable offline.

  features()      one candidate → numeric feature dict (base shape, chart read, holders, flow, dev)
  FlowTracker     rolling smart-money / KOL buy-sell flow per token from the track feeds
  SampleStore     every scored candidate is snapshotted; outcomes are labeled 60m later
  label_outcome() did it reach +TP before -SL within the horizon (from the snapshot price)?
  Model           L2 logistic regression, standardised features, time-ordered holdout AUC
"""
from __future__ import annotations
import json, math, pathlib, threading, time
from collections import defaultdict

# ── outcome definition (what "worked" means) ───────────────────────────────
# Floor bases can sit for hours before they break, so the window is 2h.
LABEL = dict(horizon_min=120, tp=0.30, sl=0.15)

FEATURES = [
    "base_len", "base_range", "base_pos", "wake", "pullback", "quiet", "bar_usd_log",
    "mcap_log", "liq_ratio", "age_log", "kline_score",
    "sm_conf_log", "holders_log", "top10", "bundler", "dev_hold", "rug", "sniper70", "rat",
    "buy_ratio", "chg_1h", "chg_5m",
    "flow_sm_net", "flow_sm_wallets", "flow_kol_wallets", "flow_in_base",
    "dev_eval",
    "floor", "pump_x_log", "retrace", "vol_decay", "near_low",
]

# ── post-pump floor base: pump → 60-90% crash → bleed → long dead-quiet range at the lows ──
FLOOR = dict(min_pump=2.5, min_retrace=0.60, max_vol_ratio=0.25, near_low=1.15, max_range=0.12, min_len_min=60)

def find_floor_base(cs, bar_min=5, cfg=None):
    """cs = candles over the coin's life (5m). Returns (base dict, None) or (None, reason)."""
    c = dict(FLOOR, **(cfg or {}))
    n = len(cs)
    if n < 20:
        return None, "too little history"
    pk = max(range(n), key=lambda i: cs[i]["h"])
    peak = cs[pk]["h"]
    start = min(x["l"] for x in cs[:pk + 1])
    pump_x = peak / start if start else 0.0
    if pump_x < c["min_pump"]:
        return None, "no launch pump"
    hi = lo = None; k = 0
    for i in range(n - 1, pk, -1):                    # trailing range, only after the peak
        nh = cs[i]["h"] if hi is None else max(hi, cs[i]["h"])
        nl = cs[i]["l"] if lo is None else min(lo, cs[i]["l"])
        if (nh - nl) / ((nh + nl) / 2) > c["max_range"]:
            break
        hi, lo, k = nh, nl, k + 1
    if k * bar_min < c["min_len_min"]:
        return None, "no long flat range yet"
    base = cs[n - k:]
    mid = (hi + lo) / 2
    retrace = 1 - mid / peak
    if retrace < c["min_retrace"]:
        return None, "hasn't retraced enough"
    post_low = min(x["l"] for x in cs[pk + 1:])
    if lo > post_low * c["near_low"]:
        return None, "base is above the lows"
    mean = lambda a: sum(a) / len(a) if a else 0.0
    pump_vol = mean([x["v"] for x in cs[max(0, pk - 6):pk + 3]])
    bvol = mean([x["v"] for x in base])
    vol_decay = bvol / pump_vol if pump_vol else 1.0
    if vol_decay > c["max_vol_ratio"]:
        return None, "volume hasn't dried up"
    last = cs[-1]["c"]
    if last > hi * 1.03:
        return None, "already breaking out"
    tail = base[-12:]
    atr = mean([x["h"] - x["l"] for x in tail])
    return dict(length=k * bar_min, top=hi, low=lo, range=(hi - lo) / mid, last=last,
                pos=(last - lo) / (hi - lo) if hi > lo else 0.5, pullback=retrace,
                bar_usd=bvol / bar_min, quiet=True, wake=(mean([x["v"] for x in base[-2:]]) / bvol) if bvol else 0.0,
                broken=False, atr=atr, start_ts=base[0]["t"],
                pump_x=pump_x, retrace=retrace, vol_decay=vol_decay, near_low=lo / post_low,
                dip_entry=min(x["l"] for x in tail) + 0.2 * atr,
                breakout_entry=max(x["h"] for x in tail) * 1.01), None

def _slog(x):   # signed log so net flow keeps its sign
    return math.copysign(math.log10(1 + abs(x)), x)

def features(f, row: dict, base: dict, kline: dict, flow: dict, dev_eval) -> dict:
    """f = screener.Token, row = raw trending row, base = floor/range dict, kline = charts.chart_read()."""
    g = lambda k: float(row.get(k) or 0) if _num(row.get(k)) else 0.0
    return dict(
        base_len=base["length"], base_range=base["range"], base_pos=base["pos"],
        wake=min(base["wake"], 6.0), pullback=base["pullback"], quiet=1.0 if base["quiet"] else 0.0,
        bar_usd_log=math.log10(1 + base["bar_usd"]),
        mcap_log=math.log10(1 + f.mcap), liq_ratio=(f.liquidity / f.mcap) if f.mcap else 0.0,
        age_log=math.log10(1 + f.age_min), kline_score=kline["score"] / 100.0,
        sm_conf_log=math.log10(1 + f.sm_confluence), holders_log=math.log10(1 + g("holder_count")),
        top10=f.top10, bundler=f.bundler, dev_hold=f.dev_hold, rug=f.rug_ratio,
        sniper70=g("top70_sniper_hold_rate"), rat=g("rat_trader_amount_rate"),
        buy_ratio=f.buy_ratio, chg_1h=max(-1.0, min(1.0, f.chg_1h)), chg_5m=max(-1.0, min(1.0, f.chg_5m)),
        flow_sm_net=_slog(flow.get("sm_net_usd", 0.0)), flow_sm_wallets=min(flow.get("sm_wallets", 0), 30),
        flow_kol_wallets=min(flow.get("kol_wallets", 0), 30), flow_in_base=_slog(flow.get("net_in_base", 0.0)),
        dev_eval=0.5 if dev_eval is None else float(dev_eval),
        floor=1.0 if "pump_x" in base else 0.0,
        pump_x_log=math.log10(max(1.0, base.get("pump_x", 1.0))), retrace=base.get("retrace", base["pullback"]),
        vol_decay=min(1.0, base.get("vol_decay", 1.0)), near_low=base.get("near_low", 1.0),
    )

def _num(v):
    try:
        float(v); return True
    except Exception:
        return False

def rule_score(x: dict) -> int:
    """Hand-set prior used until the model has enough labeled data (and blended after)."""
    if x.get("floor"):
        return floor_score(x)
    s = 20 * min(1.0, max(0.0, (x["base_len"] - 15) / 45))            # longer base
    s += 15 * min(1.0, max(0.0, (0.10 - x["base_range"]) / 0.08))     # tighter base
    s += 15 * min(1.0, max(0.0, (x["wake"] - 1.0) / 2.0))             # volume waking up
    s += 15 * min(1.0, max(0.0, x["flow_in_base"] / 4.0))             # smart money net-buying the base ($10k → full)
    s += 5 * min(1.0, x["flow_sm_wallets"] / 5)
    s += 10 * min(1.0, x["sm_conf_log"] / 1.5)
    s += 8 if 0.25 <= x["pullback"] <= 0.75 else (4 if x["pullback"] > 0 else 0)
    s += 7 * (1 - min(1.0, x["base_pos"]))                            # lower in range = better R/R
    s += 5 * (x["dev_eval"] - 0.5) * 2                                 # dev reputation ±5
    s -= 10 * min(1.0, max(0.0, (x["top10"] - 0.30) / 0.20))          # concentration penalty
    s -= 10 * min(1.0, max(0.0, (x["sniper70"] - 0.15) / 0.25))       # snipers still holding
    return int(round(max(0, min(100, s))))


def floor_score(x: dict) -> int:
    """Post-pump floor: a real launch pump, a deep flush, then a long, dead-quiet floor that
    smart money is quietly buying — and ideally the first volume stirring."""
    s = 15 * min(1.0, max(0.0, (x["base_len"] - 60) / 180))           # 1h → 0, 4h+ → full
    s += 12 * min(1.0, max(0.0, (0.12 - x["base_range"]) / 0.09))     # tight floor
    s += 12 * min(1.0, max(0.0, (0.25 - x["vol_decay"]) / 0.20))      # volume truly dried up
    s += 8 * min(1.0, max(0.0, (x["pump_x_log"] - 0.4) / 0.6))        # 2.5x → 0, 10x → full launch pump
    s += 8 * (1.0 if 0.65 <= x["retrace"] <= 0.92 else 0.4 if x["retrace"] > 0.92 else 0.5)  # deep flush, not dead
    s += 15 * min(1.0, max(0.0, x["flow_in_base"] / 4.0))             # smart money net-buying the floor
    s += 5 * min(1.0, x["flow_sm_wallets"] / 4)
    s += 12 * min(1.0, max(0.0, (x["wake"] - 1.0) / 3.0))             # first volume spike off the floor
    s += 8 * min(1.0, x["sm_conf_log"] / 1.5)
    s += 5 * (x["dev_eval"] - 0.5) * 2
    s -= 10 * min(1.0, max(0.0, (x["top10"] - 0.30) / 0.20))
    s -= 8 * min(1.0, max(0.0, (x["sniper70"] - 0.15) / 0.25))
    return int(round(max(0, min(100, s))))


# ── smart money / KOL flow ─────────────────────────────────────────────────
class FlowTracker:
    """Track feeds return only the last few minutes of trades, so kraken polls them every minute and
    feeds them here. Dedupes by tx hash and keeps WINDOW_S of history per token."""
    WINDOW_S = 3 * 3600

    def __init__(self):
        self.lock = threading.Lock()
        self.seen: dict[str, float] = {}
        self.trades: dict[str, list] = defaultdict(list)   # token → [(ts, kind, side, usd, maker)]

    def add(self, kind: str, rows: list):
        now = time.time()
        with self.lock:
            for r in rows or []:
                h = r.get("transaction_hash")
                tok = r.get("base_address")
                if not h or not tok or h in self.seen:
                    continue
                try:
                    ts, usd = float(r.get("timestamp") or now), float(r.get("amount_usd") or 0)
                except Exception:
                    continue
                self.seen[h] = ts
                self.trades[tok].append((ts, kind, r.get("side"), usd, r.get("maker")))
            cut = now - self.WINDOW_S
            self.seen = {h: t for h, t in self.seen.items() if t >= cut}
            for tok in list(self.trades):
                self.trades[tok] = [t for t in self.trades[tok] if t[0] >= cut]
                if not self.trades[tok]:
                    del self.trades[tok]

    def summary(self, token: str, base_start_ts: float | None = None) -> dict:
        with self.lock:
            tr = list(self.trades.get(token, []))
        net = sum(u if s == "buy" else -u for _, k, s, u, _ in tr if k == "sm")
        inb = sum(u if s == "buy" else -u for ts, k, s, u, _ in tr if base_start_ts and ts >= base_start_ts)
        return dict(sm_net_usd=net, net_in_base=inb,
                    sm_wallets=len({m for _, k, s, _, m in tr if k == "sm" and s == "buy"}),
                    kol_wallets=len({m for _, k, s, _, m in tr if k == "kol" and s == "buy"}),
                    trades=len(tr))

    def coverage_min(self) -> float:
        with self.lock:
            ts = [t for v in self.trades.values() for t in (x[0] for x in v)]
        return (time.time() - min(ts)) / 60 if ts else 0.0


# ── outcome labeling ───────────────────────────────────────────────────────
def label_outcome(entry_price: float, candles_after: list, tp=None, sl=None, sparse_ok=False) -> dict | None:
    """Walk 1m candles after the snapshot: win if +tp is touched before -sl. Same-candle touches of
    both count as a loss (conservative). None if there are too few candles to judge."""
    tp = LABEL["tp"] if tp is None else tp
    sl = LABEL["sl"] if sl is None else sl
    # GMGN leaves out minutes with no trades, so a quiet coin can have far fewer than 120 candles.
    # Once the window is well over, judge it on the candles that exist; none at all means nobody traded = loss.
    if not entry_price:
        return None
    if len(candles_after) < LABEL["horizon_min"] * 0.5 and not sparse_ok:
        return None
    if not candles_after:
        return dict(win=0, max_up=0.0, max_dd=0.0, end_ret=0.0, resolved=False, dead=True)
    up_px, dn_px = entry_price * (1 + tp), entry_price * (1 - sl)
    max_up = max_dd = 0.0
    result = None
    for c in candles_after[:LABEL["horizon_min"]]:
        max_up = max(max_up, c["h"] / entry_price - 1)
        max_dd = max(max_dd, 1 - c["l"] / entry_price)
        if result is None:
            if c["l"] <= dn_px:
                result = 0
            elif c["h"] >= up_px:
                result = 1
    last = candles_after[min(len(candles_after), LABEL["horizon_min"]) - 1]["c"]
    return dict(win=result if result is not None else 0, max_up=max_up, max_dd=max_dd,
                end_ret=last / entry_price - 1, resolved=result is not None)


# ── storage ────────────────────────────────────────────────────────────────
class SampleStore:
    """Append-only JSONL. Snapshots and labels live in separate files and are joined by id."""
    def __init__(self, out_dir: pathlib.Path):
        self.samples_path = out_dir / "base_samples.jsonl"
        self.labels_path = out_dir / "base_labels.jsonl"
        self.lock = threading.Lock()
        self.samples: dict[str, dict] = {}
        self.labels: dict[str, dict] = {}
        self._last_snap: dict[str, float] = {}
        out_dir.mkdir(parents=True, exist_ok=True)
        for p, dst in ((self.samples_path, self.samples), (self.labels_path, self.labels)):
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    try:
                        r = json.loads(line); dst[r["id"]] = r
                    except Exception:
                        pass
        for s in self.samples.values():
            self._last_snap[s["address"]] = max(self._last_snap.get(s["address"], 0), s["ts"])

    def snapshot(self, chain, address, symbol, price, x: dict, rule: int, p, min_gap_s=1800) -> bool:
        """One snapshot per token per 30 min, so a coin sitting in a base for hours isn't overcounted."""
        now = time.time()
        with self.lock:
            if now - self._last_snap.get(address, 0) < min_gap_s or not price:
                return False
            rec = dict(id=f"{address}:{int(now)}", ts=now, chain=chain, address=address, symbol=symbol,
                       price=price, x=x, rule=rule, p=p)
            self.samples[rec["id"]] = rec
            self._last_snap[address] = now
            with self.samples_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True

    def due(self, now=None, limit=20) -> list:
        now = now or time.time()
        h = LABEL["horizon_min"] * 60
        with self.lock:
            d = [s for i, s in self.samples.items()
                 if i not in self.labels and now - s["ts"] >= h + 120 and now - s["ts"] < 24 * 3600]
        return sorted(d, key=lambda s: s["ts"])[:limit]

    def add_label(self, sid: str, out: dict):
        rec = dict(id=sid, **out)
        with self.lock:
            self.labels[sid] = rec
            with self.labels_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

    def labeled(self) -> list:
        with self.lock:
            return sorted(((self.samples[i], l) for i, l in self.labels.items()
                           if i in self.samples and l.get("win") is not None), key=lambda t: t[0]["ts"])

    def stats(self) -> dict:
        lab = self.labeled()
        wins = sum(l["win"] for _, l in lab)
        hi = [l for s, l in lab if s.get("rule", 0) >= 60]
        return dict(samples=len(self.samples), labeled=len(lab), wins=wins, replayed=sum(1 for s, _ in lab if s.get("replay")),
                    win_rate=(wins / len(lab)) if lab else None,
                    hi_score_n=len(hi), hi_score_win_rate=(sum(l["win"] for l in hi) / len(hi)) if hi else None,
                    pending=len(self.samples) - len(self.labels))


# ── model ──────────────────────────────────────────────────────────────────
def _auc(y, p):
    pos = [pi for yi, pi in zip(y, p) if yi == 1]; neg = [pi for yi, pi in zip(y, p) if yi == 0]
    if not pos or not neg:
        return None
    wins = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)
    return wins / (len(pos) * len(neg))

class Model:
    MIN_N, MIN_CLASS = 40, 5

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.state = None
        if path.exists():
            try:
                self.state = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self.state = None

    @staticmethod
    def _fit(X, y, l2=1.0, iters=600, lr=0.3):
        n, d = len(X), len(X[0])
        mu = [sum(r[j] for r in X) / n for j in range(d)]
        sd = [max(1e-6, math.sqrt(sum((r[j] - mu[j]) ** 2 for r in X) / n)) for j in range(d)]
        Z = [[(r[j] - mu[j]) / sd[j] for j in range(d)] for r in X]
        pos = sum(y) / n
        w, b = [0.0] * d, math.log(max(pos, 1e-3) / max(1 - pos, 1e-3))
        for _ in range(iters):
            gw, gb = [0.0] * d, 0.0
            for zi, yi in zip(Z, y):
                e = 1 / (1 + math.exp(-max(-30, min(30, b + sum(a * c for a, c in zip(w, zi)))))) - yi
                gb += e
                for j in range(d):
                    gw[j] += e * zi[j]
            b -= lr * gb / n
            w = [wj - lr * (gj / n + l2 * wj / n) for wj, gj in zip(w, gw)]
        return dict(mu=mu, sd=sd, w=w, b=b)

    @staticmethod
    def _pred(m, row):
        z = m["b"] + sum(wj * (v - mu) / sd for wj, v, mu, sd in zip(m["w"], row, m["mu"], m["sd"]))
        return 1 / (1 + math.exp(-max(-30, min(30, z))))

    def train(self, labeled: list) -> dict:
        X = [[float(s["x"].get(k, 0.0)) for k in FEATURES] for s, _ in labeled]
        y = [int(l["win"]) for _, l in labeled]
        n, pos = len(y), sum(y)
        info = dict(n=n, pos=pos, ready=False, auc=None, trained_at=time.time())
        if n < self.MIN_N or pos < self.MIN_CLASS or n - pos < self.MIN_CLASS:
            info["why"] = f"need ≥{self.MIN_N} labeled with ≥{self.MIN_CLASS} wins and losses (have {n}, {pos} wins)"
            self.state = dict(info=info)
            return info
        cut = int(n * 0.75)                                   # time-ordered holdout: train on past, test on future
        if cut >= 20 and len(set(y[cut:])) == 2:
            m = self._fit(X[:cut], y[:cut])
            info["auc"] = _auc(y[cut:], [self._pred(m, r) for r in X[cut:]])
            info["base_auc"] = _auc(y[cut:], [labeled[i][0].get("rule", 0) for i in range(cut, n)])
        m = self._fit(X, y)
        info["ready"] = True
        info["weights"] = sorted(([k, round(w, 3)] for k, w in zip(FEATURES, m["w"])), key=lambda t: -abs(t[1]))
        self.state = dict(info=info, model=m)
        self.path.write_text(json.dumps(self.state), encoding="utf-8")
        return info

    def predict(self, x: dict):
        if not self.state or not self.state.get("model"):
            return None
        if len(self.state["model"]["w"]) != len(FEATURES):   # feature set changed: wait for a retrain
            return None
        return self._pred(self.state["model"], [float(x.get(k, 0.0)) for k in FEATURES])

    def blend_weight(self) -> float:
        """How much the model's say grows with data; capped so the rule prior never vanishes.
        If the model doesn't beat the rule score on the holdout, it gets a small vote only."""
        info = (self.state or {}).get("info") or {}
        if not info.get("ready"):
            return 0.0
        a = min(0.7, info["n"] / 300)
        auc, base = info.get("auc"), info.get("base_auc")
        if auc is not None and base is not None and auc <= base:
            a = min(a, 0.2)
        return a
