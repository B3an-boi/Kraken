"""Historical replay: walk recent coins' past candles as if Base Hunter had been scanning, and label
what happened next. Fills the Learning data in an hour instead of days.

Honest limits: replay only knows price and volume. Holder, smart-money and flow features were not
recorded in the past, so they are left neutral (0) instead of using today's values, which would leak
the future (a coin that later rugged has a high rug label *now*). Replayed snapshots train the model
and the backtests; they never count toward the auto-trade record that unlocks real trading.
"""
from __future__ import annotations

import json, math, threading, time
from types import SimpleNamespace

from . import basehunter as bh
from .charts import chart_read
from .screener import Token, safety_check

STEP_BARS = 2           # look every 10 minutes, like the live scan
GAP_S = 1800            # one snapshot per coin per 30 min, like live


class Replay:
    def __init__(self, hunter, settings, event):
        self.h, self.settings, self.event = hunter, settings, event
        self.state = dict(running=False, done=0, total=0, added=0, wins=0, started=0.0, finished=0.0, error="", note="")
        self.lock = threading.Lock()

    def start(self, client, chain: str) -> dict:
        with self.lock:
            if self.state["running"]:
                return self.state
            self.state.update(running=True, done=0, total=0, added=0, wins=0, started=time.time(), finished=0.0, error="", note="")
        threading.Thread(target=self._run, args=(client, chain), daemon=True).start()
        return self.state

    def _run(self, client, chain):
        try:
            c, safe = self.settings["hunter"], self.settings["screen"]
            rows, seen = [], set()
            for iv in ("24h", "6h", "1h"):
                try:
                    for r in client.trending(interval=iv, limit=100):
                        if r.get("address") and r["address"] not in seen:
                            seen.add(r["address"]); rows.append(r)
                except Exception:
                    pass
            from .hunter import trench_rows
            for r in trench_rows(client):
                if r["address"] not in seen:
                    seen.add(r["address"]); rows.append(r)
            pool = []
            for r in rows:
                t = Token.from_row(r)
                if safety_check(t, safe) or self.h._slop(r, c) or t.age_min < 120:
                    continue
                pool.append((t, r))
            self.state["total"] = len(pool)
            self.state["note"] = f"{len(rows)} coins → {len(pool)} worth replaying"
            for t, r in pool:
                try:
                    cs = client.kline(t.address, "5m", int(min(t.age_min + 15, 2880)))
                except Exception:
                    cs = None
                if cs:
                    a, w = self._walk(t, r, cs, c, chain)
                    self.state["added"] += a; self.state["wins"] += w
                self.state["done"] += 1
            if self.state["added"]:
                self.h.model.train(self.h.store.labeled())
            self.event("learn", f"replay added {self.state['added']} snapshots ({self.state['wins']} wins) from {self.state['done']} coins")
        except Exception as e:
            self.state["error"] = str(e)[:300]
            self.event("error", f"replay failed: {e}")
        finally:
            self.state.update(running=False, finished=time.time())

    def _walk(self, t, r, cs, c, chain) -> tuple[int, int]:
        H = bh.LABEL["horizon_min"] * 60
        now_px = cs[-1]["c"] or t.price
        supply = (t.mcap / t.price) if t.price else 0
        added = wins = 0
        last_snap = 0.0
        cfg = dict(min_len_min=c["min_base_min"], max_range=c["max_range"], min_pump=c["min_pump"],
                   min_retrace=c["min_retrace"], max_vol_ratio=c["max_vol_ratio"], near_low=c["near_low"])
        for i in range(20, len(cs), STEP_BARS):
            ts = cs[i]["t"] + 300                       # the moment that candle closed
            if ts + H > cs[-1]["t"] + 300:               # need the full 2h after it
                break
            if ts - last_snap < GAP_S:
                continue
            hist = cs[:i + 1]
            b, _ = bh.find_floor_base(hist, 5, cfg)
            if not b or b["bar_usd"] < c["min_usd_per_min_floor"]:
                continue
            price = hist[-1]["c"]
            sid = f"replay:{t.address}:{int(ts)}"
            if sid in self.h.store.samples:
                last_snap = ts
                continue
            # the coin as it looked then: price-derived fields only, everything else neutral
            then = lambda k: next((x["c"] for x in reversed(hist) if x["t"] <= ts - k * 60), hist[0]["o"])
            f = SimpleNamespace(mcap=price * supply, liquidity=0.0, age_min=max(0.0, t.age_min - (cs[-1]["t"] - cs[i]["t"]) / 60),
                                sm_confluence=0, top10=0.0, bundler=0.0, dev_hold=0.0, rug_ratio=0.0, buy_ratio=0.5,
                                chg_1h=price / then(60) - 1, chg_5m=price / then(5) - 1)
            x = bh.features(f, {}, b, chart_read(hist), {}, None)
            after = [dict(h=k["h"], l=k["l"], c=k["c"]) for k in cs[i + 1:] if k["t"] < ts + H]
            out = _label_5m(price, after)
            rec = dict(id=sid, ts=ts, chain=chain, address=t.address, symbol=t.symbol, price=price, x=x,
                       rule=bh.rule_score(x), p=None, replay=True)
            with self.h.store.lock:
                self.h.store.samples[sid] = rec
                self.h.store.labels[sid] = dict(id=sid, **out)
                with self.h.store.samples_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                with self.h.store.labels_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(dict(id=sid, **out)) + "\n")
            added += 1; wins += out["win"]; last_snap = ts
        return added, wins


def _label_5m(entry, after) -> dict:
    """Same rule as live labels, on 5m candles: +TP before −SL; both in one candle counts as a loss."""
    tp, sl = entry * (1 + bh.LABEL["tp"]), entry * (1 - bh.LABEL["sl"])
    if not after:
        return dict(win=0, max_up=0.0, max_dd=0.0, end_ret=0.0, resolved=False, dead=True)
    up = dd = 0.0; res = None
    for k in after:
        up = max(up, k["h"] / entry - 1); dd = max(dd, 1 - k["l"] / entry)
        if res is None:
            if k["l"] <= sl:
                res = 0
            elif k["h"] >= tp:
                res = 1
    return dict(win=res or 0, max_up=up, max_dd=dd, end_ret=after[-1]["c"] / entry - 1, resolved=res is not None)
