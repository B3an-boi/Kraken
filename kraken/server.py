"""FastAPI app + background loop. Binds to 127.0.0.1 by default; keys never leave your machine."""
from __future__ import annotations
import ipaddress, json, os, threading, time, traceback
from collections import deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, backtest, screener, setup_flow
from .alerts import Alerts
from .config import DATA, ROOT, Settings
from .gmgn import DemoClient, GMGNError, LiveClient, RateGate, key_status
from .hunter import Hunter
from .positions import Positions, RiskError

S = Settings()
GATE = RateGate(S["rate"]["min_gap_s"], S["rate"]["max_inflight"])
HUNTER = Hunter(S)
POS = Positions(S)
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


def client():
    chain = S["chain"]
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
    return await call_next(request)


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


class SellIn(BaseModel):
    id: str
    reason: str = "manual"


@app.get("/api/positions")
def get_positions():
    return dict(open=POS.open_list(), closed=[p for p in POS.items if p["status"] == "closed"][-50:][::-1],
                summary=POS.summary())


@app.post("/api/buy")
def buy(b: BuyIn):
    try:
        p = POS.buy(client(), b.address.strip(), screener.clean_symbol(b.symbol), b.size, b.source)
    except Exception as e:
        _err(e)
    event("buy", f"{p['mode']} buy {p['symbol']} {p['size']} @ {p['entry_price']:.3g}", id=p["id"])
    return p


@app.post("/api/sell")
def sell(s: SellIn):
    try:
        p = POS.sell(client(), s.id, s.reason)
    except Exception as e:
        _err(e)
    event("sell", f"{p['mode']} sell {p['symbol']} {p['pnl_pct']:+.1%}", id=p["id"])
    return p


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
                HUNTER.poll_flow(c)
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
                for sig in POS.monitor(c):
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
