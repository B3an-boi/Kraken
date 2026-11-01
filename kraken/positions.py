"""Positions: one-click buys/sells (paper in SHADOW, real swaps in LIVE) and an exit monitor that
flags stop-loss, take-profit and safety degradation. Kraken never trades on its own — signals only."""
from __future__ import annotations
import json, threading, time, uuid
from .config import DATA
from .gmgn import NATIVE, GMGNError, key_status

PATH = DATA / "positions.json"


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
        r = self.settings["risk"]
        return dict(open=len(op), max_positions=r["max_positions"], exposure=sum(p["size"] for p in op),
                    max_exposure=r["max_exposure"], realized_24h=realized, daily_loss_limit=r["daily_loss_limit"],
                    unrealized=sum(p.get("pnl", 0) for p in op))

    def _check_risk(self, size: float, address: str):
        r, s = self.settings["risk"], self.summary()
        if any(p["address"] == address for p in self.open_list()):
            raise RiskError("you already hold this token")
        if s["open"] >= r["max_positions"]:
            raise RiskError(f"max positions reached ({r['max_positions']})")
        if s["exposure"] + size > r["max_exposure"] + 1e-12:
            raise RiskError(f"exposure would exceed {r['max_exposure']}")
        if s["realized_24h"] <= -r["daily_loss_limit"]:
            raise RiskError("daily loss limit hit — buying paused for 24h")

    def _live(self, client) -> bool:
        if self.settings["mode"] != "LIVE":
            return False
        if not client.live:
            raise RiskError("LIVE mode needs a GMGN API key — you're on demo data")
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

    def buy(self, client, address: str, symbol: str, size: float | None = None, source: str = "manual") -> dict:
        size = float(size or self.settings["risk"]["buy_size"])
        if size <= 0:
            raise RiskError("size must be positive")
        with self.lock:
            self._check_risk(size, address)
            live = self._live(client)
            price = client.price(address)
            if not price:
                raise RiskError("couldn't get a price for this token")
            fill = dict(filled=True, status="paper", order_id=None, hash=None)
            if live:
                chain = self.settings["chain"]
                native, dec = NATIVE[chain]
                fill = self._await_fill(client, client.swap(native, address, amount=size * 10 ** dec,
                                                            slippage=self.settings["risk"]["slippage"]))
                if not fill["filled"]:
                    raise RiskError(f"swap not confirmed (status {fill['status']}) — no position recorded")
                price = client.price(address) or price
            p = dict(id=uuid.uuid4().hex[:10], address=address, symbol=symbol, chain=self.settings["chain"],
                     mode="LIVE" if live else "SHADOW", size=size, entry_price=price, entry_ts=time.time(),
                     last_price=price, peak=price, pnl=0.0, pnl_pct=0.0, status="open", source=source,
                     order_id=fill["order_id"], tx=fill["hash"], signals=[], entry_top10=None)
            self.items.append(p)
            self._save()
            return p

    def sell(self, client, pid: str, reason: str = "manual") -> dict:
        with self.lock:
            p = next((x for x in self.items if x["id"] == pid and x["status"] == "open"), None)
            if not p:
                raise RiskError("position not found or already closed")
            price = client.price(p["address"]) or p["last_price"]
            if p["mode"] == "LIVE":
                if not client.live:
                    raise RiskError("this is a LIVE position but kraken is on demo data — check your key")
                native, _ = NATIVE[p["chain"]]
                fill = self._await_fill(client, client.swap(p["address"], native, percent=100,
                                                            slippage=self.settings["risk"]["slippage"]))
                if not fill["filled"]:
                    raise RiskError(f"sell not confirmed (status {fill['status']}) — position still open")
                p["exit_tx"] = fill["hash"]
            p.update(status="closed", exit_price=price, exit_ts=time.time(), exit_reason=reason,
                     pnl=p["size"] * (price / p["entry_price"] - 1), pnl_pct=price / p["entry_price"] - 1)
            self._save()
            return p

    def monitor(self, client) -> list[dict]:
        """Update prices and return newly raised exit signals."""
        r = self.settings["risk"]
        new = []
        with self.lock:
            for p in self.open_list():
                try:
                    price = client.price(p["address"])
                except Exception:
                    continue
                if not price:
                    continue
                p.update(last_price=price, peak=max(p["peak"], price), pnl_pct=price / p["entry_price"] - 1,
                         pnl=p["size"] * (price / p["entry_price"] - 1), updated=time.time())
                sig = []
                if p["pnl_pct"] <= -r["stop_loss"]:
                    sig.append(("stop_loss", f"down {p['pnl_pct']:.0%} (stop {r['stop_loss']:.0%})"))
                if p["pnl_pct"] >= r["take_profit"]:
                    sig.append(("take_profit", f"up {p['pnl_pct']:.0%} (target {r['take_profit']:.0%})"))
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
