"""FastAPI app + background loop. Binds to 127.0.0.1 by default; keys never leave your machine."""
from __future__ import annotations
import ipaddress, json, os, threading, time, traceback
from collections import deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, backtest, graph, research, screener, setup_flow
from . import basehunter as bh
from .alerts import Alerts
from .config import DATA, ROOT, Settings
from .gmgn import NATIVE, DemoClient, GMGNError, LiveClient, RateGate, key_status
from .hunter import Hunter
from .positions import PaperOrders, Positions, RiskError

S = Settings()
GATE = RateGate(S["rate"]["min_gap_s"], S["rate"]["max_inflight"])
HUNTER = Hunter(S)
POS = Positions(S)
ORDERS = PaperOrders(POS)
WATCH = research.Watchlist()
TAPE = research.Tape()
JOBS = research.Jobs()
ALERTS = Alerts(S)
SCREEN = dict(results=[], funnel={}, ts=0.0, running=False, error="")
EVENTS: deque = deque(maxlen=300)
EVENTS_PATH = DATA / "events.jsonl"
_clients: dict = {}
_lock = threading.Lock()
FORCE_DEMO = os.getenv("KRAKEN_DEMO", "").lower() in ("1", "true", "yes")
ALLOW_REMOTE = os.getenv("KRAKEN_ALLOW_REMOTE", "").lower() in ("1", "true", "yes")


def event(kind: str, msg: str, **extra):
    e = dict(ts=time.time(), kind=kind, msg=msg, **extra)
    EVENTS.appendleft(e)
    try:
        with EVENTS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError:
        pass


def is_live() -> bool:
    k = key_status()
    return not FORCE_DEMO and k["cli"] and k["api_key"]


def client(chain: str | None = None):
    """GMGN client for `chain` (default: the chain selected in the UI). One cached client per chain."""
    chain = chain or S["chain"]
    key = (chain, is_live())
    with _lock:
        if key not in _clients:
            _clients[key] = LiveClient(chain, GATE) if key[1] else DemoClient(chain)
        return _clients[key]


app = FastAPI(title="kraken", version=__version__)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host in ("localhost", "testclient")
    if not local and not ALLOW_REMOTE and request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "kraken only accepts requests from this computer"}, status_code=403)
    resp = await call_next(request)
    if request.url.path.startswith("/assets/") or request.url.path == "/":
        resp.headers["Cache-Control"] = "no-cache"      # updates show up on the next page load
    return resp


def _err(e: Exception):
    if isinstance(e, (RiskError, ValueError)):
        raise HTTPException(400, str(e))
    if isinstance(e, GMGNError):
        raise HTTPException(502, str(e))
    raise HTTPException(500, str(e))


# ── status & settings ────────────────────────────────────────────────────────
@app.get("/api/status")
def status():
    return dict(version=__version__, live_data=is_live(), forced_demo=FORCE_DEMO, mode=S["mode"], chain=S["chain"],
                keys=key_status(), positions=POS.summary(), gmgn_calls=GATE.calls,
                rate_limited_s=max(0, int(GATE.banned_until - time.time())))


@app.get("/api/settings")
def get_settings():
    return S.public()


@app.post("/api/settings")
def set_settings(patch: dict):
    try:
        if patch.get("mode") == "LIVE":
            if not is_live():
                raise ValueError("LIVE needs gmgn-cli and a GMGN API key (no key found, so this is a simulated market)")
            if not key_status()["private_key"]:
                raise ValueError("LIVE needs GMGN_PRIVATE_KEY — run: python -m kraken setup")
        out = S.update(patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if "rate" in patch:
        GATE.configure(S["rate"]["min_gap_s"], S["rate"]["max_inflight"])
    if "hunter" in patch:
        HUNTER.sync_label_rule()
    if "mode" in patch:
        event("mode", f"mode set to {S['mode']}")
    return out


@app.post("/api/settings/reset")
def reset_settings(section: str | None = None):
    if section and section not in S.data:
        raise HTTPException(400, "unknown section")
    return S.reset(section)


# ── screener ─────────────────────────────────────────────────────────────────
def _run_screen():
    if SCREEN["running"]:
        return
    SCREEN["running"] = True
    try:
        r = screener.run(client(), S.get("screen"))
        SCREEN.update(r, error="")
        event("screen", f"screened {r['funnel']['scanned']} → {r['funnel']['passed']} passed")
        a = S.get("alerts")
        if a["on_screen"]:
            for o in r["results"]:
                if o["status"] == "pass" and o["score"] >= a["min_score"]:
                    t = o["token"]
                    ALERTS.send(f"Screener: {t['symbol']} scored {o['score']}",
                                f"MC ${t['mcap']:,.0f} · 1h {t['chg_1h']:+.0%} · " + ", ".join(o["reasons"]),
                                key=f"scr:{t['address']}", url=f"https://gmgn.ai/{S['chain']}/token/{t['address']}")
    except Exception as e:
        SCREEN["error"] = str(e)[:300]
        event("error", f"screen failed: {e}")
    finally:
        SCREEN["running"] = False


@app.get("/api/screen")
def get_screen():
    return SCREEN


@app.post("/api/screen/run")
def run_screen():
    threading.Thread(target=_run_screen, daemon=True).start()
    return dict(ok=True)


# ── base hunter ──────────────────────────────────────────────────────────────
def _run_hunter():
    try:
        r = HUNTER.scan(client())
        st = r["stats"]
        event("hunter", f"{st['setup']}: {st['pool']} → {st['found']} bases", stats=st)
        a = S.get("alerts")
        if a["on_floor"]:
            for o in r["results"]:
                if o["score"] >= a["min_score"]:
                    b = o["base"]
                    ALERTS.send(f"Base Hunter: {o['symbol']} score {o['score']}",
                                f"MC ${o['mcap']:,.0f} · base {b['length']:.0f}m ±{b['range'] / 2:.1%} · {o['pattern']}",
                                key=f"hunt:{o['address']}", url=f"https://gmgn.ai/{S['chain']}/token/{o['address']}")
    except Exception as e:
        event("error", f"hunter scan failed: {e}")


@app.get("/api/hunter")
def get_hunter():
    return HUNTER.public_state()


_SNAP_CACHE: dict = {}


@app.get("/api/hunter/snap/{sid:path}")
def hunter_snap(sid: str):
    """1m candles around one Base Hunter snapshot: 45 min before the flag to 15 min after its 2h check."""
    s = HUNTER.store.samples.get(sid)
    if not s:
        raise HTTPException(404, "snapshot not found")
    lab = HUNTER.store.labels.get(sid)
    if lab and sid in _SNAP_CACHE:
        return _SNAP_CACHE[sid]
    h = bh.LABEL["horizon_min"] * 60
    try:
        cs = client(s.get("chain", "sol")).kline_range(s["address"], s["ts"] - 45 * 60, s["ts"] + h + 15 * 60)
    except Exception as e:
        _err(e)
    out = dict(id=sid, symbol=s["symbol"], address=s["address"], chain=s.get("chain", "sol"), ts=s["ts"], price=s.get("price"),
               rule=s.get("rule"), p=s.get("p"), label=lab, tp=bh.LABEL["tp"], sl=bh.LABEL["sl"], horizon_min=bh.LABEL["horizon_min"],
               candles=[[x["t"], x["o"], x["h"], x["l"], x["c"], x["v"]] for x in cs])
    if lab:
        _SNAP_CACHE[sid] = out
        if len(_SNAP_CACHE) > 200:
            _SNAP_CACHE.pop(next(iter(_SNAP_CACHE)))
    return out


@app.get("/api/hunter/flags/{address}")
def hunter_flags(address: str):
    """Every time Base Hunter flagged this token, for markers on the token chart."""
    with HUNTER.store.lock:
        rows = [dict(ts=s["ts"], price=s.get("price"), rule=s.get("rule"),
                     win=(HUNTER.store.labels.get(i) or {}).get("win")) for i, s in HUNTER.store.samples.items() if s["address"] == address]
    return dict(flags=sorted(rows, key=lambda r: r["ts"]), tp=bh.LABEL["tp"], sl=bh.LABEL["sl"], horizon_min=bh.LABEL["horizon_min"])


@app.post("/api/hunter/scan")
def scan_hunter():
    threading.Thread(target=_run_hunter, daemon=True).start()
    return dict(ok=True)


@app.post("/api/hunter/label")
def label_now():
    return dict(labeled=HUNTER.label_due(client()))


@app.get("/api/backtest")
def get_backtest(min_score: float | None = None, max_range: float | None = None, min_base_len: float | None = None,
                 min_pump: float | None = None, min_retrace: float | None = None, max_vol_ratio: float | None = None,
                 tp: float | None = None, sl: float | None = None):
    f = {k: v for k, v in dict(min_score=min_score, max_range=max_range, min_base_len=min_base_len, min_pump=min_pump,
                               min_retrace=min_retrace, max_vol_ratio=max_vol_ratio, tp=tp, sl=sl).items() if v is not None}
    return backtest.run(HUNTER.store.labeled(), HUNTER.public_state()["label"], f)


# ── trading ──────────────────────────────────────────────────────────────────
class BuyIn(BaseModel):
    address: str
    symbol: str = "?"
    size: float | None = None
    source: str = "manual"
    take_profit: float | None = None
    stop_loss: float | None = None


class SellIn(BaseModel):
    id: str
    reason: str = "manual"
    pct: float = 100


@app.get("/api/positions")
def get_positions():
    return dict(open=POS.open_list(), closed=[p for p in POS.items if p["status"] == "closed"][-50:][::-1],
                summary=POS.summary())


@app.post("/api/buy")
def buy(b: BuyIn):
    try:
        p = POS.buy(client(), b.address.strip(), screener.clean_symbol(b.symbol), b.size, b.source,
                    take_profit=b.take_profit, stop_loss=b.stop_loss)
    except Exception as e:
        _err(e)
    event("buy", f"{p['mode']} buy {p['symbol']} {p['size']} @ {p['entry_price']:.3g}", id=p["id"])
    return p


@app.post("/api/sell")
def sell(s: SellIn):
    try:
        pos = next((x for x in POS.items if x["id"] == s.id), None)
        p = POS.sell(client(pos["chain"] if pos else None), s.id, s.reason, s.pct)
    except Exception as e:
        _err(e)
    event("sell", f"{p['mode']} sell {s.pct:g}% of {p['symbol']} at {p['pnl_pct']:+.1%}", id=p["id"])
    return p


# ── command center: discover, research, tape, watchlist, orders ────────────────
def _chain():
    return S["chain"]


def _addr_chain(addr: str, follow=True) -> str:
    """The chain an address can live on: base58 = Solana, 0x = an EVM chain (the selected one if it's EVM,
    otherwise BSC). With follow=True the UI's chain switches to match, so every screen stays consistent."""
    cur = S["chain"]
    ch = "sol" if research.SOL_ADDR.match(addr) else (cur if cur != "sol" else "bsc")
    if follow and ch != cur:
        S.update({"chain": ch})
        event("chain", f"switched to {ch.upper()} to match {addr[:6]}…")
    return ch


@app.get("/api/discover")
def get_discover(force: bool = False):
    c = client()
    if not c.live:
        raise HTTPException(400, "Discover needs live GMGN data. Connect your GMGN key in Settings.")
    return research.discover(c, _chain(), force)


@app.get("/api/search")
def get_search(q: str):
    c = client()
    if not c.live:
        raise HTTPException(400, "Research needs live GMGN data. Connect your GMGN key in Settings.")
    try:
        r = research.search(c, _chain(), q, client_for=client)
    except Exception as e:
        _err(e)
    if r.get("chain") and r["chain"] != _chain():
        S.update({"chain": r["chain"]})                     # the address lives on another chain: follow it
        event("chain", f"switched to {r['chain'].upper()} for {q[:12]}…")
    return r


@app.get("/api/token/{address}")
def get_token(address: str, force: bool = False):
    c = client()
    if not c.live:
        raise HTTPException(400, "Research needs live GMGN data. Connect your GMGN key in Settings.")
    if not research.is_address(address):
        raise HTTPException(400, "that's not a contract address")
    try:
        ch = _addr_chain(address)
        return research.token_dossier(client(ch), ch, address, force)
    except Exception as e:
        _err(e)


@app.get("/api/candles/{address}")
def get_candles(address: str, res: str = "15m"):
    if not research.is_address(address):
        raise HTTPException(400, "that's not a contract address")
    ch = _addr_chain(address, follow=False)
    c = client(ch)
    if not c.live:
        raise HTTPException(400, "Charts need live GMGN data.")
    try:
        return research.candles(c, ch, address, res)
    except Exception as e:
        _err(e)


@app.get("/api/wallet/{address}")
def get_wallet(address: str, force: bool = False):
    c = client()
    if not c.live:
        raise HTTPException(400, "Research needs live GMGN data. Connect your GMGN key in Settings.")
    if not research.is_address(address):
        raise HTTPException(400, "that's not a wallet address")
    try:
        ch = _addr_chain(address)
        d = research.wallet_dossier(client(ch), ch, address, force)
    except Exception as e:
        _err(e)
    d["following"] = any(w["address"] == address for w in WATCH.wallets())
    return d


@app.get("/api/graph/{address}")
def get_graph(address: str):
    c = client()
    if not c.live:
        raise HTTPException(400, "The wallet graph needs live GMGN data. Connect your GMGN key in Settings.")
    if not research.is_address(address):
        raise HTTPException(400, "that's not a wallet address")
    try:
        ch = _addr_chain(address, follow=False)
        return graph.build(client(ch), ch, address)
    except Exception as e:
        _err(e)


class JobIn(BaseModel):
    kind: str
    target: str


@app.post("/api/jobs")
def start_job(j: JobIn):
    if not client().live:
        raise HTTPException(400, "needs live GMGN data")
    try:
        t = j.target.strip()
        return JOBS.start(j.kind, _addr_chain(t, follow=False), t)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/jobs")
def get_job(kind: str, target: str):
    return JOBS.get(kind, _addr_chain(target, follow=False), target) or dict(status="none")


@app.get("/api/tape")
def get_tape(kinds: str = ""):
    k = [x for x in kinds.split(",") if x] or None
    return dict(trades=TAPE.list(k, chain=_chain()), following=WATCH.wallets())


class WatchIn(BaseModel):
    address: str
    label: str = ""


@app.post("/api/watchlist")
def add_watch(w: WatchIn):
    try:
        return dict(wallets=WATCH.add(w.address.strip(), w.label))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/watchlist/remove")
def remove_watch(w: WatchIn):
    return dict(wallets=WATCH.remove(w.address.strip()))


class OrderIn(BaseModel):
    address: str
    symbol: str = "?"
    type: str                 # buy_low / buy_high / take_profit / stop_loss
    trigger_price: float
    size: float | None = None
    pct: float = 100          # sell orders: share of the position to sell
    expire_hours: float = 24


@app.get("/api/orders")
def get_orders():
    out = dict(paper=ORDERS.open_list(), live=[], live_error=None, mode=S["mode"])
    c = client()
    if c.live and key_status()["private_key"]:
        try:
            out["live"] = c.limit_orders("open")
        except Exception as e:
            out["live_error"] = str(e)[:200]
    return out


@app.post("/api/orders")
def create_order(o: OrderIn):
    if o.type not in ("buy_low", "buy_high", "take_profit", "stop_loss"):
        raise HTTPException(400, "unknown order type")
    if not (0 < o.pct <= 100):
        raise HTTPException(400, "sell share must be between 1 and 100%")
    if not (0 < o.expire_hours <= 24 * 30):
        raise HTTPException(400, "expiry must be between 0 and 30 days")
    c = client()
    try:
        if S["mode"] == "LIVE":
            if not c.live or not key_status()["private_key"]:
                raise RiskError("LIVE orders need a connected GMGN key with a wallet")
            if o.type.startswith("buy"):
                native, dec = NATIVE[_chain()]
                r = c.limit_order(o.address, o.type, o.trigger_price, amount_in=float(o.size or S["risk"]["buy_size"]) * 10 ** dec,
                                  slippage=S["risk"]["slippage"], expire_s=o.expire_hours * 3600)
            else:
                r = c.limit_order(o.address, o.type, o.trigger_price, amount_pct=o.pct,
                                  slippage=S["risk"]["slippage"], expire_s=o.expire_hours * 3600)
            event("order", f"LIVE {o.type.replace('_', ' ')} order on {screener.clean_symbol(o.symbol)} at {o.trigger_price:.6g}")
            return dict(mode="LIVE", result=r)
        p = ORDERS.create(o.address, screener.clean_symbol(o.symbol), o.type, o.trigger_price, o.size, o.expire_hours * 3600,
                          chain=_chain(), pct=o.pct)
        event("order", f"paper {o.type.replace('_', ' ')} order on {p['symbol']} at {o.trigger_price:.6g}")
        return dict(mode="SHADOW", result=p)
    except Exception as e:
        _err(e)


class CancelIn(BaseModel):
    id: str
    live: bool = False


@app.post("/api/orders/cancel")
def cancel_order(cn: CancelIn):
    try:
        if cn.live:
            return dict(result=client().cancel_order(cn.id))
        return dict(result=ORDERS.cancel(cn.id))
    except Exception as e:
        _err(e)


# ── first-run GMGN setup ─────────────────────────────────────────────────────
class SetupApplyIn(BaseModel):
    api_key: str


@app.get("/api/setup")
def setup_status():
    return setup_flow.status()


@app.post("/api/setup/start")
def setup_start():
    try:
        return setup_flow.start()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/setup/apply")
def setup_apply(b: SetupApplyIn):
    try:
        r = setup_flow.apply(b.api_key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    if r["result"] in ("ok", "saved_unverified"):
        with _lock:
            _clients.clear()                       # next call builds a LiveClient with the new key
        event("setup", "GMGN key connected" + (" (not verified yet)" if r["result"] != "ok" else ""))
    return r


# ── alerts & log ─────────────────────────────────────────────────────────────
@app.post("/api/alerts/test")
def test_alert():
    r = ALERTS.send("kraken test alert", "If you can read this, alerts work. 🐙", force=True)
    if not r:
        raise HTTPException(400, "no alert channel configured — add an ntfy topic, Telegram or Discord first")
    return r


@app.get("/api/events")
def get_events(limit: int = 100):
    return dict(events=list(EVENTS)[:limit], alerts=ALERTS.log[:20])


# ── background loop ──────────────────────────────────────────────────────────
def loop():
    last = dict(flow=0.0, label=0.0, hunter=0.0, screen=0.0, monitor=0.0)
    time.sleep(3)
    while True:
        now = time.time()
        try:
            c = client()
            if now - last["flow"] >= 60:
                last["flow"] = now
                HUNTER.poll_flow(c, TAPE, chain=S["chain"])
            if c.live and WATCH.wallets() and now - last.get("watch", 0) >= 120:
                last["watch"] = now
                for w in WATCH.wallets():
                    try:
                        d = c.read(["portfolio", "activity", "--wallet", w["address"], "--limit", "10"])
                        for a in (d or {}).get("activities") or []:
                            if a.get("event_type") in ("buy", "sell"):
                                TAPE.add("follow", a, w.get("label") or w["address"][:6], chain=S["chain"])
                    except Exception:
                        pass
            if ORDERS.open_list() and now - last.get("orders", 0) >= 20:
                last["orders"] = now
                for o in ORDERS.check(client):
                    event("order", f"paper {o['type'].replace('_', ' ')} filled on {o['symbol']} at {o['fill_price']:.6g}")
            if now - last["label"] >= 120:
                last["label"] = now
                n = HUNTER.label_due(c)
                if n:
                    event("learn", f"labeled {n} snapshot(s)")
            h = S.get("hunter")
            if h["auto"] and now - max(last["hunter"], HUNTER.state["last_scan"]) >= h["auto_every_min"] * 60:
                last["hunter"] = now
                _run_hunter()
            sc = S.get("screen")
            if sc["auto"] and now - max(last["screen"], SCREEN["ts"]) >= sc["auto_every_min"] * 60:
                last["screen"] = now
                _run_screen()
            if POS.open_list() and now - last["monitor"] >= S["risk"]["monitor_every_s"]:
                last["monitor"] = now
                sigs = []
                for ch in {p["chain"] for p in POS.open_list()}:      # each position is priced on its own chain
                    sigs += POS.monitor(client(ch), chain=ch)
                for sig in sigs:
                    p = sig["position"]
                    event("exit_signal", f"{p['symbol']}: {sig['msg']}", id=p["id"])
                    if S["alerts"]["on_exit"]:
                        ALERTS.send(f"Exit signal: {p['symbol']}", f"{sig['msg']} · P/L {p['pnl_pct']:+.0%}",
                                    key=f"exit:{p['id']}:{sig['kind']}")
        except Exception as e:
            event("error", f"loop: {e}")
            traceback.print_exc()
        time.sleep(5)


@app.on_event("startup")
def _start():
    try:
        for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-200:]:
            EVENTS.appendleft(json.loads(line))
    except Exception:
        pass
    event("start", f"kraken {__version__} started · {'live GMGN data' if is_live() else 'NO GMGN KEY: simulated market'} · {S['mode']}")
    threading.Thread(target=loop, daemon=True).start()


WEB = ROOT / "web"
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
