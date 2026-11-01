"""Data/trading clients.

LiveClient wraps the public `gmgn-cli` (npm i -g gmgn-cli) and reads credentials from the CLI's own
env file (~/.config/gmgn/.env). DemoClient synthesises a realistic market so kraken runs with no key.
Both expose the same methods, so the rest of kraken never knows which one it's talking to."""
from __future__ import annotations
import hashlib, json, math, os, pathlib, random, re, shutil, string, subprocess, threading, time

GMGN_ENV = pathlib.Path.home() / ".config" / "gmgn" / ".env"
NATIVE = {"sol": ("So11111111111111111111111111111111111111112", 9),
          "bsc": ("0x0000000000000000000000000000000000000000", 18),
          "base": ("0x0000000000000000000000000000000000000000", 18),
          "eth": ("0x0000000000000000000000000000000000000000", 18)}


class GMGNError(RuntimeError):
    pass


def gmgn_bin() -> str | None:
    return shutil.which("gmgn-cli")


_VERSION: dict = {}


def cli_version() -> str | None:
    """Installed gmgn-cli version (cached), e.g. '1.7.1'."""
    if "v" not in _VERSION:
        v = None
        exe = gmgn_bin()
        if exe:
            try:
                out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
                m = re.search(r"(\d+\.\d+\.\d+)", out.stdout or out.stderr or "")
                v = m.group(1) if m else None
            except Exception:
                v = None
        _VERSION["v"] = v
    return _VERSION["v"]


MIN_CLI = (1, 7, 0)   # call-outs, market search, portfolio profits


def cli_outdated() -> bool:
    v = cli_version()
    if not v:
        return False
    return tuple(int(x) for x in v.split(".")) < MIN_CLI


def load_env(path: pathlib.Path = GMGN_ENV) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                v = v[1:-1]
            out[k.strip()] = v.replace("\\n", "\n")
    return out


def write_env(api_key: str, private_key: str = "", path: pathlib.Path = GMGN_ENV):
    path.parent.mkdir(parents=True, exist_ok=True)
    cur = load_env(path)
    cur["GMGN_API_KEY"] = api_key.strip() or cur.get("GMGN_API_KEY", "")
    if private_key.strip():
        cur["GMGN_PRIVATE_KEY"] = private_key.strip()
    body = "".join(f'{k}="{v.replace(chr(10), chr(92) + "n")}"\n' for k, v in cur.items() if v)
    path.write_text(body, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def key_status() -> dict:
    env = load_env()
    return dict(cli=bool(gmgn_bin()), cli_version=cli_version(), cli_outdated=cli_outdated(),
                api_key=bool(env.get("GMGN_API_KEY")),
                private_key=bool(env.get("GMGN_PRIVATE_KEY")), env_path=str(GMGN_ENV))


class RateGate:
    """Every gmgn-cli call passes here: starts are spaced, concurrency is capped, and after a 429 we
    stop sending until the ban expires (requests during a ban extend it)."""
    def __init__(self, min_gap_s=1.2, max_inflight=1):
        self.lock = threading.Lock()
        self.configure(min_gap_s, max_inflight)
        self.last = 0.0
        self.banned_until = 0.0
        self.calls = 0

    def configure(self, min_gap_s, max_inflight):
        self.min_gap_s = float(min_gap_s)
        self.slots = threading.BoundedSemaphore(int(max_inflight))

    def run(self, cmd: list, env: dict, timeout=45) -> subprocess.CompletedProcess:
        slots = self.slots
        with slots:
            with self.lock:
                now = time.time()
                if now < self.banned_until:
                    raise GMGNError(f"rate-limited by GMGN, {int(self.banned_until - now)}s left")
                wait = self.last + self.min_gap_s - now
                if wait > 0:
                    time.sleep(wait)
                self.last = time.time()
                self.calls += 1
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                                 encoding="utf-8", errors="replace")
            wait_s = rate_limit_wait(out)
            if wait_s is not None:
                with self.lock:
                    self.banned_until = time.time() + wait_s + 5
                raise GMGNError(f"rate-limited by GMGN (429), pausing {wait_s + 5}s")
            return out


_RL_MARK = re.compile(r"RATE[_ ]?LIMIT|too many requests|(?:HTTP|status(?: code)?)\s*:?\s*429", re.I)
_RL_429 = re.compile(r"(?<![\d.])429(?![\d.])")


def rate_limit_wait(out) -> int | None:
    """Seconds to back off if this gmgn-cli result is a real rate-limit error, else None.

    A real ban carries both an HTTP 429 and GMGN's RATE_LIMIT code (or "too many requests").
    Successful output is never scanned as text: prices, timestamps and addresses often contain
    the digits 429, which used to trigger false bans."""
    stderr, stdout = out.stderr or "", out.stdout or ""
    body = stderr
    try:
        d = json.loads(stdout) if stdout.strip() else None
    except json.JSONDecodeError:
        d = None
    if isinstance(d, dict):
        code = d.get("code")
        if code not in (0, None, "0"):              # an error payload: inspect its code/message only
            body += f" {code} {d.get('msg') or ''} {d.get('message') or ''} {d.get('error') or ''}"
    elif out.returncode != 0:
        body += stdout[:2000]                       # non-JSON error output
    if not (_RL_429.search(body) and _RL_MARK.search(body)):
        return None
    m = re.search(r"~?(\d+)\s*s(?:ec(?:onds)?)?\s*remaining", body, re.I) or \
        re.search(r"(?:retry|reset)\D{0,20}(\d+)", body, re.I)
    return min(int(m.group(1)), 3600) if m else 300


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def parse_candles(raw) -> list[dict]:
    out = []
    for c in raw or []:
        try:
            t = int(float(c["time"])); o, h, l, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        if min(h, l, cl) <= 0:
            continue
        out.append(dict(t=t if t < 1e11 else t // 1000, o=o, h=h, l=l, c=cl,
                        v=_f(c.get("amount") if c.get("amount") is not None else c.get("volume"))))
    out.sort(key=lambda x: x["t"])
    return out


class LiveClient:
    live = True

    def __init__(self, chain: str, gate: RateGate):
        self.chain, self.gate = chain, gate
        self.env = {**os.environ, **load_env()}
        if "--use-system-ca" not in self.env.get("NODE_OPTIONS", ""):
            self.env["NODE_OPTIONS"] = (self.env.get("NODE_OPTIONS", "") + " --use-system-ca").strip()
        self.bin = gmgn_bin() or "gmgn-cli"
        self._wallet = None

    def _run(self, args: list, chain=True):
        cmd = [self.bin, *args] + (["--chain", self.chain] if chain else []) + ["--raw"]
        out = self.gate.run(cmd, self.env)
        if out.returncode != 0:
            raise GMGNError((out.stderr or out.stdout or "gmgn-cli failed").strip()[:300])
        try:
            d = json.loads(out.stdout)
        except json.JSONDecodeError:
            raise GMGNError("gmgn-cli returned non-JSON output")
        if isinstance(d, dict) and d.get("code") not in (0, None):
            raise GMGNError(f"gmgn-cli code={d.get('code')} {d.get('msg') or d.get('message') or ''}".strip())
        return d

    @staticmethod
    def _data(d):
        return d.get("data", d) if isinstance(d, dict) and d.get("data") is not None else d

    def trending(self, interval="1h", limit=100, order_by="volume") -> list[dict]:
        d = self._data(self._run(["market", "trending", "--interval", interval, "--order-by", order_by,
                                  "--direction", "desc", "--limit", str(limit), "--filter", "not_wash_trading"]))
        return (d.get("rank") or d.get("tokens") or []) if isinstance(d, dict) else []

    def kline(self, addr, resolution="1m", minutes=120) -> list[dict]:
        now = int(time.time())
        d = self._data(self._run(["market", "kline", "--address", addr, "--resolution", resolution,
                                  "--from", str(now - int(minutes) * 60), "--to", str(now)]))
        return parse_candles(d.get("list") if isinstance(d, dict) else d)

    def kline_range(self, addr, t0, t1, resolution="1m") -> list[dict]:
        d = self._data(self._run(["market", "kline", "--address", addr, "--resolution", resolution,
                                  "--from", str(int(t0)), "--to", str(int(t1))]))
        return parse_candles(d.get("list") if isinstance(d, dict) else d)

    def token_info(self, addr) -> dict:
        return self._data(self._run(["token", "info", "--address", addr]))

    def price(self, addr) -> float:
        p = self.token_info(addr).get("price")
        return _f(p.get("price")) if isinstance(p, dict) else _f(p)

    def security(self, addr) -> dict:
        return self._data(self._run(["token", "security", "--address", addr]))

    def track(self, kind: str) -> list[dict]:
        d = self._data(self._run(["track", {"sm": "smartmoney", "kol": "kol"}[kind], "--limit", "200"]))
        return (d.get("list") or []) if isinstance(d, dict) else []

    def wallet_address(self) -> str:
        if self._wallet:
            return self._wallet
        d = self._run(["portfolio", "info"], chain=False)
        for w in (d.get("wallets") or []):
            if w.get("chain") == self.chain and w.get("address"):
                self._wallet = w["address"]
                return self._wallet
        raise GMGNError(f"no {self.chain} wallet bound to this GMGN API key")

    def _fees(self) -> list:
        """Default priority/tip fees; GMGN requires them on SOL for TP/SL and strategy orders."""
        if self.chain == "sol":
            return ["--priority-fee", "0.0001", "--tip-fee", "0.0001"]
        return []

    def swap(self, input_token, output_token, amount=None, percent=None, slippage=0.15,
             take_profit=None, stop_loss=None) -> dict:
        """slippage, take_profit, stop_loss are fractions (0.15 = 15%). gmgn-cli wants percents."""
        args = ["swap", "--from", self.wallet_address(), "--input-token", input_token,
                "--output-token", output_token, "--slippage", f"{slippage * 100:g}"]
        args += ["--percent", f"{percent:g}"] if percent is not None else ["--amount", str(int(amount))]
        cond = []
        if take_profit:
            cond.append({"order_type": "profit_stop", "side": "sell", "price_scale": f"{take_profit * 100:g}", "sell_ratio": "100"})
        if stop_loss:
            cond.append({"order_type": "loss_stop", "side": "sell", "price_scale": f"{stop_loss * 100:g}", "sell_ratio": "100"})
        if cond:
            args += ["--condition-orders", json.dumps(cond)] + self._fees()
        return self._data(self._run(args))

    def quote(self, input_token, output_token, amount, slippage=0.15) -> dict:
        return self._data(self._run(["order", "quote", "--from", self.wallet_address(), "--input-token", input_token,
                                     "--output-token", output_token, "--amount", str(int(amount)),
                                     "--slippage", f"{slippage * 100:g}"]))

    def limit_order(self, token, side_type, trigger_price, amount_in=None, amount_pct=None,
                    slippage=0.15, expire_s=86400) -> dict:
        """side_type: buy_low / buy_high (spend native) or take_profit / stop_loss (sell token)."""
        native, _ = NATIVE[self.chain]
        args = ["order", "strategy", "create", "--from", self.wallet_address(), "--base-token", token,
                "--quote-token", native, "--order-type", "limit_order", "--sub-order-type", side_type,
                "--check-price", f"{trigger_price:.12g}", "--slippage", f"{slippage * 100:g}",
                "--expire-in", str(int(expire_s))]
        args += ["--amount-in-percent", f"{amount_pct:g}"] if amount_pct is not None else ["--amount-in", str(int(amount_in))]
        return self._data(self._run(args + self._fees()))

    def limit_orders(self, kind="open") -> list:
        d = self._data(self._run(["order", "strategy", "list", "--type", kind, "--group-tag", "LimitOrder",
                                  "--from", self.wallet_address(), "--limit", "50"]))
        return (d.get("list") or d.get("orders") or []) if isinstance(d, dict) else (d or [])

    def cancel_order(self, order_id, order_type="limit_order") -> dict:
        return self._data(self._run(["order", "strategy", "cancel", "--from", self.wallet_address(),
                                     "--order-id", str(order_id), "--order-type", order_type]))

    def order_get(self, order_id) -> dict:
        return self._data(self._run(["order", "get", "--order-id", str(order_id)]))

    # Generic read access for the command-center features. Every call still goes through the rate gate.
    READ_ONLY = {("market", "kline"), ("market", "trending"), ("market", "trenches"), ("market", "signal"),
                 ("market", "hot-searches"), ("market", "search"), ("token", "info"), ("token", "security"),
                 ("token", "pool"), ("token", "holders"), ("token", "traders"), ("portfolio", "activity"),
                 ("portfolio", "stats"), ("portfolio", "profits"), ("portfolio", "token-balance"),
                 ("portfolio", "created-tokens"), ("portfolio", "holdings"), ("track", "kol"),
                 ("track", "smartmoney"), ("track", "follow-wallet"), ("callout", "record"),
                 ("callout", "global"), ("order", "quote"), ("order", "gas-price"), ("cooking", "stats")}
    NO_CHAIN = {("market", "hot-searches"), ("market", "search"), ("cooking", "stats"), ("callout", "global")}

    def read(self, args: list, chain: bool | None = None):
        """Run a whitelisted read-only gmgn-cli sub-command and return its JSON (unwrapped)."""
        key = tuple(args[:2])
        if key not in self.READ_ONLY:
            raise GMGNError(f"not an allowed read command: {' '.join(args[:2])}")
        if chain is None:
            chain = key not in self.NO_CHAIN
        return self._data(self._run(list(args), chain=chain))


# ── demo market ──────────────────────────────────────────────────────────────
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_NAMES = ("KRAKEN TIDE REEF ABYSS SQUID INK CORAL PEARL DRIFT SHOAL BRINE NAUTI GULP WHIRL SIREN "
          "MOLT FATHOM KELP LURE ORCA TRENCH SONAR BUBBL HYDRA DEEP SALT CRAB WAVE ANCHR GILL "
          "PLNKTN JELLY ECHO CURRNT LAGOON MARLIN EEL URCHIN RIPTD HARBR SPRAT COD DUNE BOUY "
          "NARWHL TUNA KRILL MANTA OTTER").split()


def _rng(*parts) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big"))


class DemoClient:
    """Deterministic synthetic market. Each token follows launch pump → flush → floor → breakout/bleed
    with per-minute noise seeded by (token, minute), so charts are stable across calls and keep
    evolving in real time — which lets the learning loop label demo snapshots too."""
    live = False
    SUPPLY = 1_000_000_000

    def __init__(self, chain="sol", seed=None, n=110):
        self.chain = chain
        epoch = int(time.time() // 86400) if seed is None else seed       # new universe each day
        self.tokens = [self._make(epoch, i) for i in range(n)]
        self.by_addr = {t["address"]: t for t in self.tokens}
        self.positions_hint = {}

    def _make(self, epoch, i):
        r = _rng("tok", epoch, i)
        now_min = time.time() / 60
        addr = "".join(r.choice(_B58) for _ in range(40)) + "pump"
        age = r.choice([r.uniform(60, 360), r.uniform(240, 1440), r.uniform(1440, 2880)])
        kind = r.choices(["floor", "runner", "bleed", "chop"], [0.45, 0.2, 0.2, 0.15])[0]
        bad = r.random() < 0.12
        return dict(address=addr, symbol=_NAMES[i % len(_NAMES)] + ("" if i < len(_NAMES) else str(i)),
                    launch=now_min - age, kind=kind, p0=r.uniform(6000, 15000) / self.SUPPLY, usd_min=r.uniform(20, 90),
                    pump_len=r.uniform(15, 90), pump_x=r.uniform(2.2, 30) if kind != "chop" else r.uniform(1.2, 2.2),
                    flush_len=r.uniform(10, 60), retrace=r.uniform(0.55, 0.95),
                    floor_len=r.uniform(40, 900), floor_amp=r.uniform(0.015, 0.06),
                    breakout=r.random() < 0.4, brk_x=r.uniform(1.4, 4.0), seed=r.random(),
                    top10=r.uniform(0.10, 0.55 if bad else 0.32), dev_hold=r.uniform(0, 0.15 if bad else 0.04),
                    bundler=r.uniform(0, 0.5 if bad else 0.2), rug=r.uniform(0, 0.6 if bad else 0.15),
                    honeypot=bad and r.random() < 0.4, renounced=not (bad and r.random() < 0.5),
                    sm=r.choices([0, 1, 2, 4, 8], [0.25, 0.3, 0.2, 0.15, 0.1])[0], kol=r.choice([0, 0, 1, 2]),
                    holders=int(r.uniform(80, 3000)))

    def _price(self, t, m: float) -> float:
        """Price at minute m since launch (before noise)."""
        p0, peak = t["p0"], t["p0"] * t["pump_x"]
        if m < t["pump_len"]:
            return p0 * t["pump_x"] ** (m / t["pump_len"])
        m -= t["pump_len"]
        low = peak * (1 - t["retrace"])
        if t["kind"] == "runner":
            return peak * (1 + 0.004 * m) * (1 + 0.15 * math.sin(m / 25))
        if t["kind"] == "chop":
            return peak * (0.7 + 0.25 * math.sin(m / 9) + 0.1 * math.sin(m / 31))
        if m < t["flush_len"]:
            return peak * (low / peak) ** (m / t["flush_len"])
        m -= t["flush_len"]
        if t["kind"] == "bleed":
            return low * max(0.05, 1 - 0.0015 * m)
        if m < t["floor_len"]:
            return low * (1 + t["floor_amp"] * math.sin(m / 7 + t["seed"] * 6))
        m -= t["floor_len"]
        if t["breakout"]:
            return low * min(t["brk_x"], 1 + (t["brk_x"] - 1) * m / 60) * (1 + 0.05 * math.sin(m / 5))
        return low * max(0.3, 1 - 0.004 * m)

    def _vol(self, t, m: float) -> float:
        base = t["usd_min"]
        if m < t["pump_len"]:
            return base * 40
        m -= t["pump_len"]
        if t["kind"] in ("runner", "chop"):
            return base * 8
        if m < t["flush_len"]:
            return base * 25
        m -= t["flush_len"]
        if t["kind"] == "bleed" or m < t["floor_len"]:
            return base * 1.2
        return base * (15 if t["breakout"] else 2)

    def _candle(self, t, minute_abs: int) -> dict:
        m = minute_abs - t["launch"]
        r = _rng("c", t["address"], minute_abs)
        o = self._price(t, m) * (1 + r.uniform(-0.012, 0.012))
        c = self._price(t, m + 1) * (1 + r.uniform(-0.012, 0.012))
        h = max(o, c) * (1 + abs(r.gauss(0, 0.01)))
        l = min(o, c) * (1 - abs(r.gauss(0, 0.01)))
        return dict(t=minute_abs * 60, o=o, h=h, l=l, c=c, v=self._vol(t, m) * r.uniform(0.4, 1.6))

    def _series(self, t, t0_min: int, t1_min: int, step=1):
        start = max(t0_min, int(math.ceil(t["launch"])))
        out = []
        for mm in range(start - start % step, t1_min, step):
            cs = [self._candle(t, x) for x in range(max(mm, start), min(mm + step, t1_min))]
            if cs:
                out.append(dict(t=mm * 60, o=cs[0]["o"], h=max(x["h"] for x in cs), l=min(x["l"] for x in cs),
                                c=cs[-1]["c"], v=sum(x["v"] for x in cs)))
        return out

    def kline(self, addr, resolution="1m", minutes=120):
        t = self.by_addr.get(addr)
        if not t:
            return []
        now = int(time.time() // 60)
        return self._series(t, now - int(minutes), now, 5 if resolution == "5m" else 1)

    def kline_range(self, addr, t0, t1, resolution="1m"):
        t = self.by_addr.get(addr)
        return self._series(t, int(t0 // 60), min(int(t1 // 60), int(time.time() // 60))) if t else []

    def price(self, addr) -> float:
        t = self.by_addr.get(addr)
        return self._candle(t, int(time.time() // 60))["c"] if t else 0.0

    def _row(self, t) -> dict:
        now = int(time.time() // 60)
        m = now - t["launch"]
        p = self.price(t["address"])
        p1h, p5 = self._price(t, max(0, m - 60)), self._price(t, max(0, m - 5))
        ath = max(self._price(t, x) for x in range(0, int(m) + 1, 3)) * self.SUPPLY
        r = _rng("row", t["address"], now // 5)
        vol = self._vol(t, m) * 60
        buys = int(r.uniform(50, 400)); sells = int(buys * r.uniform(0.6, 1.4))
        return dict(address=t["address"], symbol=t["symbol"], name=t["symbol"].title(), price=p,
                    market_cap=p * self.SUPPLY, liquidity=p * self.SUPPLY * r.uniform(0.12, 0.3),
                    volume=vol, swaps=buys + sells, buys=buys, sells=sells, holder_count=t["holders"],
                    price_change_percent1h=(p / p1h - 1) * 100 if p1h else 0,
                    price_change_percent5m=(p / p5 - 1) * 100 if p5 else 0,
                    creation_timestamp=int(t["launch"] * 60), open_timestamp=int(t["launch"] * 60),
                    history_highest_market_cap=ath, top_10_holder_rate=t["top10"], dev_team_hold_rate=t["dev_hold"],
                    bundler_rate=t["bundler"], rug_ratio=t["rug"], is_honeypot=int(t["honeypot"]),
                    renounced_mint=int(t["renounced"]), renounced_freeze_account=int(t["renounced"]),
                    buy_tax=0, sell_tax=0, smart_degen_count=t["sm"], renowned_count=t["kol"],
                    sniper_count=int(r.uniform(0, 30)), top70_sniper_hold_rate=r.uniform(0, 0.3))

    def trending(self, interval="1h", limit=100, order_by="volume"):
        rows = [self._row(t) for t in self.tokens if t["launch"] < time.time() / 60 - 5]
        rows.sort(key=lambda x: -x["volume"])
        return rows[:limit]

    def token_info(self, addr):
        t = self.by_addr.get(addr)
        return self._row(t) if t else {}

    def security(self, addr):
        t = self.by_addr.get(addr) or {}
        return dict(is_honeypot=t.get("honeypot", False), renounced_mint=t.get("renounced", True),
                    top_10_holder_rate=t.get("top10", 0))

    def track(self, kind):
        now = time.time()
        r = _rng("track", kind, int(now // 60))
        pool = [t for t in self.tokens if t["kind"] == "floor"] or self.tokens
        out = []
        for i in range(r.randint(3, 12)):
            t = r.choice(pool if r.random() < 0.7 else self.tokens)
            out.append(dict(transaction_hash=f"demo{kind}{int(now // 60)}{i}", base_address=t["address"],
                            timestamp=now - r.uniform(0, 60), amount_usd=r.uniform(50, 3000),
                            side="buy" if r.random() < (0.7 if t["breakout"] else 0.45) else "sell",
                            maker="".join(r.choice(_B58) for _ in range(8))))
        return out

    def read(self, args: list, chain=None):
        """Simulated market: no GMGN data for these views. Callers show a 'connect GMGN' state."""
        raise GMGNError("this view needs live GMGN data. Connect your GMGN key in Settings")

    def wallet_address(self):
        return "DEMOWALLET1111111111111111111111111111111111"

    def quote(self, *a, **k):
        raise GMGNError("quotes need live GMGN data")

    def limit_orders(self, kind="open"):
        return []

    def swap(self, **kw):
        return dict(order_id="DEMO-" + "".join(random.choice(string.digits) for _ in range(6)),
                    status="confirmed", hash="demo-tx")

    def order_get(self, order_id):
        return dict(order_id=order_id, status="confirmed", hash="demo-tx")
