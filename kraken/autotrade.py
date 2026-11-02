"""Auto-trade: Base Hunter finds become trades on their own, paper first.

Every flagged coin that clears the score bar is bought with a fixed size, a take-profit, a stop-loss and a
time limit. Paper trades build a track record; real trading stays locked until that record clears the bar
you set (enough trades, positive P/L, profit factor), and then only if you also switch it on yourself.
"""
from __future__ import annotations

import time

from .positions import RiskError

SOURCE = "auto"


class AutoTrader:
    def __init__(self, settings, positions, event):
        self.settings, self.pos, self.event = settings, positions, event
        self._tried: dict[str, float] = {}

    @property
    def c(self) -> dict:
        return self.settings["autotrade"]

    # ── track record and the live gate ──────────────────────────────────────
    def record(self, mode: str = "SHADOW") -> dict:
        closed = [p for p in self.pos.items if p.get("source") == SOURCE and p["status"] == "closed" and p["mode"] == mode]
        pnls = [float(p.get("pnl") or 0) for p in closed]
        sized = [float(p.get("pnl") or 0) / p["size"] for p in closed if p.get("size")]
        wins = [x for x in pnls if x > 0]
        loss = -sum(x for x in pnls if x < 0)
        eq = peak = dd = 0.0
        for x in pnls:
            eq += x; peak = max(peak, eq); dd = max(dd, peak - eq)
        return dict(trades=len(closed), wins=len(wins), win_rate=len(wins) / len(closed) if closed else None,
                    pnl=sum(pnls), avg_ret=sum(sized) / len(sized) if sized else None,
                    profit_factor=(sum(wins) / loss) if loss else (None if not wins else 999.0),
                    max_drawdown=dd, open=sum(1 for p in self.pos.open_list() if p.get("source") == SOURCE and p["mode"] == mode))

    def gate(self) -> dict:
        r, c = self.record("SHADOW"), self.c
        pf = r["profit_factor"]
        checks = [
            dict(name=f"{c['unlock_trades']}+ paper trades", ok=r["trades"] >= c["unlock_trades"], have=r["trades"]),
            dict(name="paper P/L above zero", ok=r["pnl"] > 0, have=round(r["pnl"], 4)),
            dict(name=f"profit factor ≥ {c['unlock_profit_factor']}", ok=pf is not None and pf >= c["unlock_profit_factor"],
                 have=None if pf is None else round(pf, 2)),
        ]
        return dict(unlocked=all(x["ok"] for x in checks), checks=checks)

    def live_on(self) -> bool:
        """Real trades need all three: the record unlocked, auto-trade live switched on, and kraken in LIVE mode."""
        return bool(self.c["live"]) and self.settings["mode"] == "LIVE" and self.gate()["unlocked"]

    # ── entries: called after every Base Hunter scan ────────────────────────
    def on_scan(self, client, results: list, chain: str) -> list:
        c = self.c
        if not c["enabled"]:
            return []
        live = self.live_on()
        mode = "LIVE" if live else "SHADOW"
        day0 = time.time() - 86400
        lost_today = -sum(min(0.0, float(p.get("pnl") or 0)) for p in self.pos.items
                          if p.get("source") == SOURCE and p["mode"] == mode and p["status"] == "closed" and p.get("exit_ts", 0) >= day0)
        if lost_today >= c["daily_loss_limit"]:
            return []
        opened = []
        for o in sorted(results, key=lambda o: -o["score"]):
            if o["score"] < c["min_score"]:
                break
            if self.record(mode)["open"] >= c["max_open"]:
                break
            a = o["address"]
            if time.time() - self._tried.get(a, 0) < c["cooldown_h"] * 3600:
                continue
            if any(p["address"] == a for p in self.pos.open_list()):
                continue
            self._tried[a] = time.time()
            try:
                p = self.pos.buy(client, a, o["symbol"], c["size"], source=SOURCE, take_profit=c["tp"],
                                 stop_loss=c["sl"], paper=not live, chain=chain)
                p["auto_score"] = o["score"]; p["max_hold_s"] = c["max_hold_min"] * 60
                self.pos._save()
                opened.append(p)
                self.event("auto", f"{'LIVE' if live else 'paper'} auto-buy {o['symbol']} · score {o['score']} · "
                                   f"{c['size']} · TP +{c['tp']:.0%} / SL −{c['sl']:.0%}", id=p["id"])
            except RiskError as e:
                self.event("auto", f"auto-buy skipped {o['symbol']}: {e}")
            except Exception as e:
                self.event("error", f"auto-buy failed {o['symbol']}: {e}")
        return opened

    # ── exits: time limit (TP/SL are handled by the position monitor) ───────
    def on_monitor(self, client_for) -> list:
        out = []
        for p in list(self.pos.open_list()):
            if p.get("source") != SOURCE or not p.get("max_hold_s"):
                continue
            if time.time() - p["entry_ts"] < p["max_hold_s"]:
                continue
            try:
                q = self.pos.sell(client_for(p.get("chain", "sol")), p["id"], reason="time limit")
                out.append(q)
                self.event("auto", f"auto-sell {p['symbol']} at the time limit · P/L {q.get('pnl', 0):+.4f}", id=p["id"])
            except Exception as e:
                self.event("error", f"auto time-exit failed {p['symbol']}: {e}")
        return out

    def state(self) -> dict:
        recent = [dict(id=p["id"], symbol=p["symbol"], address=p["address"], mode=p["mode"], status=p["status"],
                       size=p["size"], entry_ts=p["entry_ts"], exit_ts=p.get("exit_ts"), score=p.get("auto_score"),
                       pnl=p.get("pnl"), pnl_pct=p.get("pnl_pct"), reason=p.get("exit_reason"))
                  for p in self.pos.items if p.get("source") == SOURCE][-40:][::-1]
        return dict(settings=self.c, mode=self.settings["mode"], paper=self.record("SHADOW"), live=self.record("LIVE"),
                    gate=self.gate(), live_active=self.live_on(), recent=recent)
