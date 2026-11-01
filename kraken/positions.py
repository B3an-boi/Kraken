"""Positions: one-click buys/sells (paper in SHADOW, real swaps in LIVE) and an exit monitor that
flags stop-loss, take-profit and safety degradation. Kraken never trades on its own — signals only."""
from __future__ import annotations
import json, threading, time, uuid
from .config import DATA
from .gmgn import NATIVE, GMGNError, key_status

PATH = DATA / "positions.json"
ORDERS_PATH = DATA / "paper_orders.json"


class RiskError(ValueError):
    pass


class Positions:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.items: list[dict] = []
        if PATH.exists():
            try:
                self.items = json.loads(PATH.read_text(encoding="utf-8"))
            except Exception:
                self.items = []

    def _save(self):
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=1), encoding="utf-8")
        tmp.replace(PATH)

    def open_list(self):
        return [p for p in self.items if p["status"] == "open"]

    def summary(self) -> dict:
        op = self.open_list()
        day0 = time.time() - 86400
        realized = sum(p.get("pnl", 0) for p in self.items if p["status"] == "closed" and p.get("exit_ts", 0) >= day0)
        realized += sum(p.get("realized", 0) for p in self.items if p["status"] == "open")
        r = self.settings["risk"]
        return dict(open=len(op), max_positions=r["max_positions"], exposure=sum(p["size"] for p in op),
                    max_exposure=r["max_exposure"], realized_24h=realized, daily_loss_limit=r["daily_loss_limit"],
                    unrealized=sum(p.get("pnl", 0) for p in op))

    def _check_risk(self, size: float, address: str, adding: bool = False):
        r, s = self.settings["risk"], self.summary()
        if not adding and s["open"] >= r["max_positions"]:
            raise RiskError(f"max positions reached ({r['max_positions']})")
        if s["exposure"] + size > r["max_exposure"] + 1e-12:
            raise RiskError(f"exposure would exceed {r['max_exposure']}")
        if s["realized_24h"] <= -r["daily_loss_limit"]:
            raise RiskError("daily loss limit hit — buying paused for 24h")

    def _live(self, client) -> bool:
        if self.settings["mode"] != "LIVE":
            return False
        if not client.live:
            raise RiskError("LIVE mode needs a GMGN API key (no key found, so this is a simulated market)")
        if not key_status()["private_key"]:
            raise RiskError("LIVE mode needs GMGN_PRIVATE_KEY in your gmgn env file (run: python -m kraken setup)")
        return True

    @staticmethod
    def _await_fill(client, order: dict, timeout=25) -> dict:
        oid, status = order.get("order_id"), order.get("status", "pending")
        t0 = time.time()
        while oid and status not in ("confirmed", "processed", "successful", "failed", "expired") and time.time() - t0 < timeout:
            time.sleep(2.5)
            try:
                o = client.order_get(oid)
                status, order = o.get("status", status), {**order, **o}
            except GMGNError:
                pass
        return dict(order_id=oid, status=status, hash=order.get("hash"),
                    filled=status in ("confirmed", "processed", "successful"))

    def buy(self, client, address: str, symbol: str, size: float | None = None, source: str = "manual",
            take_profit: float | None = None, stop_loss: float | None = None, paper: bool = False,
            chain: str | None = None) -> dict:
        """take_profit / stop_loss are fractions (1.0 = +100%, 0.5 = -50%). LIVE: attached to the swap as
        GMGN server-side orders. SHADOW: kraken closes the paper position itself when they trigger."""
        size = float(size or self.settings["risk"]["buy_size"])
        for v in (take_profit, stop_loss):
            if v is not None and not (0 < v <= 100):
                raise RiskError("take-profit / stop-loss must be a positive percent")
        if stop_loss is not None and stop_loss >= 1:
            raise RiskError("stop-loss must be under 100%")
        if size <= 0:
            raise RiskError("size must be positive")
        with self.lock:
            ch = chain or self.settings["chain"]
            existing = next((x for x in self.open_list() if x["address"] == address and x.get("chain", "sol") == ch), None)
            self._check_risk(size, address, adding=existing is not None)
            live = False if paper else self._live(client)   # paper orders never become real trades
            if existing and existing["mode"] != ("LIVE" if live else "SHADOW"):
                raise RiskError(f"you hold this token as a {'paper' if existing['mode'] == 'SHADOW' else 'LIVE'} position; "
                                "close it before trading it in the other mode")
            price = client.price(address)
            if not price:
                raise RiskError("couldn't get a price for this token")
            fill = dict(filled=True, status="paper", order_id=None, hash=None)
            if live:
                chain = self.settings["chain"]
                native, dec = NATIVE[chain]
                fill = self._await_fill(client, client.swap(native, address, amount=size * 10 ** dec,
                                                            slippage=self.settings["risk"]["slippage"],
                                                            take_profit=take_profit, stop_loss=stop_loss))
                if not fill["filled"]:
                    raise RiskError(f"swap not confirmed (status {fill['status']}) — no position recorded")
                price = client.price(address) or price
            fill_rec = dict(ts=time.time(), side="buy", size=size, price=price, tx=fill["hash"])
            if existing:
                # add to the position: average entry is weighted by what was spent at each price
                p = existing
                tokens = p["size"] / p["entry_price"] + size / price
                p["size"] = round(p["size"] + size, 12)
                p["entry_price"] = p["size"] / tokens
                p.setdefault("fills", []).append(fill_rec)
                p.update(last_price=price, pnl_pct=price / p["entry_price"] - 1,
                         pnl=p["size"] * (price / p["entry_price"] - 1))
                if take_profit is not None:
                    p["tp"] = take_profit
                if stop_loss is not None:
                    p["sl"] = stop_loss
                self._save()
                return p
            p = dict(id=uuid.uuid4().hex[:10], address=address, symbol=symbol, chain=ch,
                     mode="LIVE" if live else "SHADOW", size=size, entry_price=price, entry_ts=time.time(),
                     last_price=price, peak=price, pnl=0.0, pnl_pct=0.0, status="open", source=source,
                     order_id=fill["order_id"], tx=fill["hash"], signals=[], entry_top10=None,
                     tp=take_profit, sl=stop_loss, fills=[fill_rec], realized=0.0)
            self.items.append(p)
            self._save()
            return p

    def sell(self, client, pid: str, reason: str = "manual", pct: float = 100) -> dict:
        """Sell pct% of the position (100 = close it). Partial sells realize that slice's P/L."""
        pct = float(pct)
        if not (0 < pct <= 100):
            raise RiskError("sell percent must be between 0 and 100")
        with self.lock:
            p = next((x for x in self.items if x["id"] == pid and x["status"] == "open"), None)
            if not p:
                raise RiskError("position not found or already closed")
            price = client.price(p["address"]) or p["last_price"]
            if p["mode"] == "LIVE":
                if not client.live:
                    raise RiskError("this is a LIVE position but no GMGN key is loaded; check your key")
                native, _ = NATIVE[p["chain"]]
                fill = self._await_fill(client, client.swap(p["address"], native, percent=pct,
                                                            slippage=self.settings["risk"]["slippage"]))
                if not fill["filled"]:
                    raise RiskError(f"sell not confirmed (status {fill['status']}) — position still open")
                p["exit_tx"] = fill["hash"]
            part = p["size"] * pct / 100
            gain = part * (price / p["entry_price"] - 1)
            p.setdefault("fills", []).append(dict(ts=time.time(), side="sell", size=part, price=price,
                                                  pct=pct, tx=p.get("exit_tx") if p["mode"] == "LIVE" else None))
            p["realized"] = p.get("realized", 0.0) + gain
            if pct < 100:
                p["size"] = round(p["size"] - part, 12)
                p.update(last_price=price, pnl_pct=price / p["entry_price"] - 1, pnl=p["size"] * (price / p["entry_price"] - 1))
            else:
                p.update(status="closed", exit_price=price, exit_ts=time.time(), exit_reason=reason,
                         pnl=p["realized"], pnl_pct=price / p["entry_price"] - 1)
            self._save()
            return p

    def monitor(self, client, chain: str | None = None) -> list[dict]:
        """Update prices (for positions on `chain`) and return newly raised exit signals."""
        r = self.settings["risk"]
        new = []
        with self.lock:
            for p in self.open_list():
                if chain and p.get("chain", "sol") != chain:
                    continue
                try:
                    price = client.price(p["address"])
                except Exception:
                    continue
                if not price:
                    continue
                p.update(last_price=price, peak=max(p["peak"], price), pnl_pct=price / p["entry_price"] - 1,
                         pnl=p["size"] * (price / p["entry_price"] - 1), updated=time.time())
                sig = []
                # paper positions with their own TP/SL close themselves, like GMGN's server-side orders do
                if p["mode"] == "SHADOW" and (p.get("tp") or p.get("sl")):
                    hit = ("take_profit" if p.get("tp") and p["pnl_pct"] >= p["tp"] else
                           "stop_loss" if p.get("sl") and p["pnl_pct"] <= -p["sl"] else None)
                    if hit:
                        p.update(status="closed", exit_price=price, exit_ts=time.time(), exit_reason=hit.replace("_", "-"))
                        new.append(dict(position=p, kind=hit, msg=f"paper {hit.replace('_', '-')} filled at {p['pnl_pct']:+.0%}", ts=time.time()))
                        continue
                sl, tp = p.get("sl") or r["stop_loss"], p.get("tp") or r["take_profit"]
                if p["pnl_pct"] <= -sl:
                    sig.append(("stop_loss", f"down {p['pnl_pct']:.0%} (stop {sl:.0%})"))
                if p["pnl_pct"] >= tp:
                    sig.append(("take_profit", f"up {p['pnl_pct']:.0%} (target {tp:.0%})"))
                if r["exit_on_safety_drop"]:
                    try:
                        sec = client.security(p["address"])
                        t10 = float(sec.get("top_10_holder_rate") or 0)
                        if p.get("entry_top10") is None:
                            p["entry_top10"] = t10
                        if str(sec.get("is_honeypot")).lower() in ("1", "true"):
                            sig.append(("safety", "now flagged as a honeypot"))
                        elif t10 - p["entry_top10"] > 0.15:
                            sig.append(("safety", f"top-10 holders jumped to {t10:.0%}"))
                    except Exception:
                        pass
                have = {s["kind"] for s in p["signals"]}
                for kind, msg in sig:
                    if kind not in have:
                        s = dict(kind=kind, msg=msg, ts=time.time())
                        p["signals"].append(s)
                        new.append(dict(position=p, **s))
            self._save()
        return new


class PaperOrders:
    """Limit orders in SHADOW mode: stored locally, filled by the monitor loop when the price crosses.
    buy_low fills at or below the trigger, buy_high at or above; take_profit / stop_loss close a position."""
    def __init__(self, positions: "Positions"):
        self.pos = positions
        self.lock = threading.RLock()
        try:
            self.items = json.loads(ORDERS_PATH.read_text(encoding="utf-8")) if ORDERS_PATH.exists() else []
        except Exception:
            self.items = []

    def _save(self):
        tmp = ORDERS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=1), encoding="utf-8")
        tmp.replace(ORDERS_PATH)

    def create(self, address, symbol, side_type, trigger_price, size=None, expire_s=86400, chain="sol", pct=100) -> dict:
        if side_type not in ("buy_low", "buy_high", "take_profit", "stop_loss"):
            raise RiskError("unknown order type")
        if not trigger_price or trigger_price <= 0:
            raise RiskError("trigger price must be positive")
        if side_type in ("take_profit", "stop_loss") and not any(p["address"] == address for p in self.pos.open_list()):
            raise RiskError("you don't hold this token, so there's nothing to sell")
        o = dict(id=uuid.uuid4().hex[:10], address=address, symbol=symbol, type=side_type, trigger=float(trigger_price),
                 size=float(size or self.pos.settings["risk"]["buy_size"]), created=time.time(),
                 expires=time.time() + expire_s, status="open", mode="SHADOW", chain=chain, pct=float(pct))
        with self.lock:
            self.items.append(o)
            self._save()
        return o

    def cancel(self, oid) -> dict:
        with self.lock:
            o = next((x for x in self.items if x["id"] == oid and x["status"] == "open"), None)
            if not o:
                raise RiskError("order not found or already done")
            o["status"] = "cancelled"
            self._save()
            return o

    def open_list(self):
        return [o for o in self.items if o["status"] == "open"]

    def check(self, client_for) -> list[dict]:
        """client_for(chain) -> GMGN client; every order is priced and filled on its own chain."""
        done = []
        with self.lock:
            for o in self.open_list():
                if time.time() > o["expires"]:
                    o["status"] = "expired"
                    continue
                client = client_for(o.get("chain", "sol"))
                try:
                    px = client.price(o["address"])
                except Exception:
                    continue
                if not px:
                    continue
                hit = ((o["type"] == "buy_low" and px <= o["trigger"]) or (o["type"] == "buy_high" and px >= o["trigger"]) or
                       (o["type"] == "take_profit" and px >= o["trigger"]) or (o["type"] == "stop_loss" and px <= o["trigger"]))
                if not hit:
                    continue
                try:
                    if o["type"].startswith("buy"):
                        self.pos.buy(client, o["address"], o["symbol"], o["size"], source="limit order", paper=True,
                                     chain=o.get("chain", "sol"))
                    else:
                        p = next((x for x in self.pos.open_list() if x["address"] == o["address"]), None)
                        if not p:
                            o["status"] = "cancelled"
                            continue
                        self.pos.sell(client, p["id"], reason=o["type"].replace("_", "-") + " order", pct=o.get("pct", 100))
                    o.update(status="filled", filled_ts=time.time(), fill_price=px)
                    done.append(o)
                except RiskError as e:
                    o.update(status="failed", error=str(e))
            self.items = self.items[-300:]
            self._save()
        return done
