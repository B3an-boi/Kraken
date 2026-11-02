"""Base Hunter: find coins sitting in a tight floor/range, snapshot them, label what happened next,
and train a small model on those outcomes."""
from __future__ import annotations
import threading, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import basehunter as bh
from .charts import chart_read, find_tight_range, spark
from .config import DATA
from .screener import Token, safety_check


def trench_rows(client, limit=80) -> list[dict]:
    """GMGN's just-bonded and almost-bonded feeds, with field names matched to trending rows."""
    if not hasattr(client, "read"):
        return []
    try:
        d = client.read(["market", "trenches", "--type", "completed", "--type", "near_completion", "--limit", str(limit)])
    except Exception:
        return []
    out = []
    for bucket in ("completed", "near_completion"):
        for r in (d or {}).get(bucket) or []:
            if not r.get("address"):
                continue
            r = dict(r)
            r.setdefault("creation_timestamp", r.get("created_timestamp") or r.get("open_timestamp"))
            r.setdefault("bundler_rate", r.get("bundler_trader_amount_rate"))
            if r.get("market_cap") in (None, "") and r.get("usd_market_cap") not in (None, ""):
                r["market_cap"] = r["usd_market_cap"]
            out.append(r)
    return out


class Hunter:
    def __init__(self, settings):
        self.settings = settings
        self.flow = bh.FlowTracker()
        self.store = bh.SampleStore(DATA)
        self.model = bh.Model(DATA / "base_model.json")
        self.state = dict(results=[], stats={}, last_scan=0.0, scanning=False, error="")
        self.lock = threading.Lock()
        self.sync_label_rule()

    def sync_label_rule(self):
        h = self.settings["hunter"]
        bh.LABEL.update(tp=h["label_tp"], sl=h["label_sl"], horizon_min=h["label_horizon_min"])

    # ── scanning ──────────────────────────────────────────────────────────
    def scan(self, client) -> dict:
        with self.lock:
            if self.state["scanning"]:
                return self.state
            self.state["scanning"] = True
        try:
            res = self._scan(client)
            self.state.update(results=res["results"], stats=res["stats"], last_scan=time.time(), error="")
            return res
        except Exception as e:
            self.state["error"] = str(e)[:300]
            raise
        finally:
            self.state["scanning"] = False

    def _scan(self, client) -> dict:
        c = self.settings.get("hunter")
        safe = self.settings.get("screen")
        floor = c["setup"] == "floor"
        rows, seen = [], set()
        for iv in ("6h", "24h", "1h"):
            try:
                got = client.trending(interval=iv, limit=100)
            except Exception as e:
                if not rows and iv == "1h":
                    raise
                got = []
            for r in got:
                if r.get("address") and r["address"] not in seen:
                    seen.add(r["address"])
                    rows.append(r)
        # coins that once pumped big and now trade far below that: exactly what a post-pump floor is
        if floor:
            for iv in ("24h", "6h"):
                try:
                    got = client.trending(interval=iv, limit=100, order_by="history_highest_market_cap",
                                          ranges={"min-history-highest-marketcap": max(50000, c["min_mcap"] * 3),
                                                  "min-marketcap": c["min_mcap"], "max-marketcap": c["max_mcap"] or None,
                                                  "min-liquidity": c["min_liq"]})
                except Exception:
                    got = []
                for r in got:
                    if r.get("address") and r["address"] not in seen:
                        seen.add(r["address"])
                        rows.append(r)
        # young launchpad coins (just bonded / almost bonded) are where post-pump floors form
        for r in trench_rows(client):
            if r["address"] not in seen:
                seen.add(r["address"])
                rows.append(r)
        stats = dict(pool=len(rows), safe=0, prefilter=0, charted=0, found=0, setup=c["setup"], why={})
        why = Counter()
        pre = []
        for r in rows:
            t = Token.from_row(r)
            if safety_check(t, safe):
                continue
            stats["safe"] += 1
            # prefilter, with the reason counted so the funnel shows what's cutting coins
            pf = ("market cap too low" if t.mcap < c["min_mcap"] else
                  "market cap too high" if c["max_mcap"] and t.mcap > c["max_mcap"] else
                  "liquidity too low" if t.liquidity < c["min_liq"] else
                  "too young" if t.age_min < c["min_age_min"] else
                  "too old" if c["max_age_h"] and t.age_min > c["max_age_h"] * 60 else
                  "already moving" if abs(t.chg_1h) > c["max_chg_1h"] or abs(t.chg_5m) > c["max_chg_5m"] else
                  "still near its high" if floor and t.ath_mcap > 0 and t.mcap / t.ath_mcap > c["max_mc_vs_ath"] else None)
            if pf:
                why[pf] += 1
                continue
            slop = self._slop(r, c)
            if slop:
                why[slop] += 1
                continue
            stats["prefilter"] += 1
            pre.append((t, r, self.flow.summary(t.address)))
        pre.sort(key=lambda x: -(x[2]["sm_wallets"] * 20 + x[2]["kol_wallets"] * 20 + x[0].sm_confluence))
        pre = pre[:c["scan_n"]]

        def fetch(item):
            t = item[0]
            try:
                if floor:
                    return item, client.kline(t.address, "5m", int(min(max(t.age_min, 60) + 15, 2880)))
                return item, client.kline(t.address, "1m", 120)
            except Exception:
                return item, None

        with ThreadPoolExecutor(max_workers=4) as ex:
            charts = list(ex.map(fetch, pre))
        a = self.model.blend_weight()
        out = []
        for (t, r, _), cs in charts:
            if not cs:
                continue
            stats["charted"] += 1
            if floor:
                b, reason = bh.find_floor_base(cs, 5, dict(
                    min_len_min=c["min_base_min"], max_range=c["max_range"], min_pump=c["min_pump"],
                    min_retrace=c["min_retrace"], max_vol_ratio=c["max_vol_ratio"], near_low=c["near_low"]))
                if b and b["bar_usd"] < c["min_usd_per_min_floor"]:
                    b, reason = None, "dead (no trading)"
            else:
                b = find_tight_range(cs, c["min_base_min"], c["max_range"])
                reason = None if b else "no tight range"
                if b and b["broken"]:
                    b, reason = None, "already breaking out"
                elif b and b["bar_usd"] < c["min_usd_per_min_any"]:
                    b, reason = None, "dead (no trading)"
            if not b:
                why[reason] += 1
                continue
            # a base passed: one token-info call to catch slop the trending row doesn't show
            slop = self._slop_info(client, t.address, c)
            if slop:
                why[slop] += 1
                continue
            stats["found"] += 1
            k = chart_read(cs)
            flow = self.flow.summary(t.address, b["start_ts"])
            x = bh.features(t, r, b, k, flow, None)
            rule = bh.rule_score(x)
            p = self.model.predict(x)
            final = round(rule * (1 - a) + 100 * p * a) if p is not None else rule
            self.store.snapshot(self.settings["chain"], t.address, t.symbol, b["last"], x, rule, p)
            supply = t.mcap / t.price if t.price else 0
            out.append(dict(address=t.address, symbol=t.symbol, mcap=t.mcap, liquidity=t.liquidity,
                            age_min=round(t.age_min), smart=t.smart, kol=t.kol, supply=supply,
                            score=final, rule=rule, p=p, pattern=k["pattern"], flow=flow,
                            base={kk: v for kk, v in b.items()}, spark=spark(cs), bar_min=5 if floor else 1,
                            spark_step_min=(5 if floor else 1) * max(1, -(-len(cs) // 150))))
        out.sort(key=lambda o: -o["score"])
        stats["why"] = dict(why.most_common())
        return dict(results=out, stats=stats)

    # ── slop filter: serial launchers, copycat logos, wash trading, dead coins ──
    @staticmethod
    def _slop(r: dict, c: dict) -> str | None:
        f = lambda k: float(r.get(k) or 0) if str(r.get(k) or "0").replace(".", "", 1).isdigit() else 0.0
        if c.get("skip_wash", True) and str(r.get("is_wash_trading")).lower() in ("true", "1"):
            return "wash trading"
        dev = f("creator_created_count")
        if c.get("max_dev_launches") and dev >= c["max_dev_launches"]:
            return "serial-launcher dev"
        dup = f("image_dup") or f("image_dup_count")
        if c.get("max_logo_dups") and dup >= c["max_logo_dups"]:
            return "copycat logo"
        return None

    def _slop_info(self, client, address: str, c: dict) -> str | None:
        try:
            info = client.token_info(address) or {}
        except Exception:
            return None
        stat, price = info.get("stat") or {}, info.get("price") if isinstance(info.get("price"), dict) else {}
        num = lambda v: float(v) if v not in (None, "") else 0.0
        try:
            dev = num(stat.get("creator_created_count"))
            dup = num(info.get("image_dup_count"))
            buys = num(price.get("buys_1h"))
        except (TypeError, ValueError):
            return None
        if c.get("max_dev_launches") and dev >= c["max_dev_launches"]:
            return "serial-launcher dev"
        if c.get("max_logo_dups") and dup >= c["max_logo_dups"]:
            return "copycat logo"
        if c.get("min_buys_1h") and price and buys < c["min_buys_1h"]:
            return "no buyers in 1h"
        return None

    # ── learning loop ─────────────────────────────────────────────────────
    def poll_flow(self, client, tape=None, chain="sol"):
        for kind in ("sm", "kol"):
            try:
                rows = client.track(kind)
            except Exception:
                continue
            self.flow.add(kind, rows)
            if tape is not None:
                for r in rows:
                    tape.add(kind, r, chain=chain)

    def label_due(self, client, limit=20) -> int:
        self.sync_label_rule()
        n = 0
        for s in self.store.due(limit=limit):
            try:
                cs = client.kline_range(s["address"], s["ts"], s["ts"] + bh.LABEL["horizon_min"] * 60 + 60)
            except Exception:
                continue
            # after the window plus 15 min of slack for GMGN's data, label even if trading was sparse
            out = bh.label_outcome(s["price"], cs, sparse_ok=time.time() - s["ts"] > (bh.LABEL["horizon_min"] + 15) * 60)
            if out:
                self.store.add_label(s["id"], out)
                n += 1
        if n:
            self.model.train(self.store.labeled())
        return n

    def public_state(self) -> dict:
        labeled = self.store.labeled()
        recent = [dict(id=s["id"], chain=s.get("chain", "sol"), price=s.get("price"), symbol=s["symbol"], address=s["address"], replay=bool(s.get("replay")),
                       ts=s["ts"], rule=s.get("rule"), p=s.get("p"),
                       win=l["win"], max_up=l.get("max_up"), max_dd=l.get("max_dd"), end_ret=l.get("end_ret"))
                  for s, l in labeled[-25:]][::-1]
        # snapshots still inside their 2h window, shown as "waiting" so you can watch them play out
        with self.store.lock:
            waiting = sorted((s for i, s in self.store.samples.items() if i not in self.store.labels
                              and time.time() - s["ts"] < 24 * 3600), key=lambda s: -s["ts"])[:60]
        pending = [dict(id=s["id"], chain=s.get("chain", "sol"), price=s.get("price"), symbol=s["symbol"],
                        address=s["address"], ts=s["ts"], rule=s.get("rule"), p=s.get("p"), win=None) for s in waiting]
        info = (self.model.state or {}).get("info") or dict(ready=False, why="no labeled data yet")
        return dict(results=self.state["results"], stats=self.state["stats"], last_scan=self.state["last_scan"],
                    scanning=self.state["scanning"], error=self.state["error"], learn=self.store.stats(),
                    model=info, blend=self.model.blend_weight(), label=dict(bh.LABEL),
                    min_labeled=bh.Model.MIN_N,
                    flow=dict(coverage_min=round(self.flow.coverage_min()), tokens=len(self.flow.trades)),
                    recent=recent, pending=pending)
