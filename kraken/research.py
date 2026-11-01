"""Discover feed, CA / wallet research, watchlist and GMGN-script jobs.

Everything here reads GMGN through the client's whitelisted read() (rate-gated) and caches results,
so browsing the dashboard doesn't burn API calls."""
from __future__ import annotations
import json, re, subprocess, sys, threading, time
from collections import deque

from . import contract_dd
from .charts import chart_read, spark
from .config import DATA, ROOT
from .gmgn import GMGNError, gmgn_bin, parse_candles
from .screener import clean_symbol

SOL_ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def is_address(q: str) -> bool:
    return bool(SOL_ADDR.match(q) or EVM_ADDR.match(q))


class _Cache:
    def __init__(self):
        self.d, self.lock = {}, threading.Lock()

    def get(self, key, ttl):
        with self.lock:
            v = self.d.get(key)
            return v[1] if v and time.time() - v[0] < ttl else None

    def put(self, key, val):
        with self.lock:
            self.d[key] = (time.time(), val)
            if len(self.d) > 400:
                for k in sorted(self.d, key=lambda k: self.d[k][0])[:100]:
                    del self.d[k]
        return val


CACHE = _Cache()


# ── quick safety from a listing row (no extra API calls) ────────────────────────────────
def quick_safety(r: dict, chain: str) -> tuple[int, list[str]]:
    """A fast 0-100 read using only fields already in trending/trenches rows, with the same
    thresholds as the full contract-DD score. The dossier computes the full score."""
    s, flags = 100.0, []

    def hit(cond, d, msg):
        nonlocal s
        if cond:
            s -= d
            flags.append(msg)
    if str(r.get("is_honeypot")) in ("1", "True", "true"):
        return 0, ["honeypot"]
    if chain == "sol":
        hit(str(r.get("renounced_mint")) not in ("1", "True", "true"), 25, "mint not renounced")
        hit(str(r.get("renounced_freeze_account")) not in ("1", "True", "true"), 20, "freeze not renounced")
    else:
        hit(str(r.get("is_open_source")) in ("0", "False", "false"), 15, "contract not verified")
        hit(str(r.get("is_renounced")) in ("0", "False", "false"), 8, "ownership not renounced")
        tax = max(_f(r.get("buy_tax")), _f(r.get("sell_tax")))
        tax = tax / 100 if tax > 1 else tax
        hit(tax > 0.10, 25, f"tax {tax:.0%}") or hit(0.05 < tax <= 0.10, 10, f"tax {tax:.0%}")
    t10 = _f(r.get("top_10_holder_rate"))
    hit(t10 > 0.5, 25, f"top10 {t10:.0%}") or hit(0.3 < t10 <= 0.5, 14, f"top10 {t10:.0%}")
    b = _f(r.get("bundler_rate", r.get("bundler_trader_amount_rate")))
    hit(b > 0.3, 20, f"bundled {b:.0%}") or hit(0.15 < b <= 0.3, 10, f"bundled {b:.0%}")
    dev = max(_f(r.get("dev_team_hold_rate")), _f(r.get("creator_balance_rate")))
    hit(dev > 0.05, 20, f"dev holds {dev:.0%}") or hit(0.02 < dev <= 0.05, 10, f"dev holds {dev:.0%}")
    sn = _f(r.get("top70_sniper_hold_rate"))
    hit(sn > 0.15, 15, f"snipers {sn:.0%}")
    rat = _f(r.get("rat_trader_amount_rate"))
    hit(rat > 0.05, 12, f"rat traders {rat:.0%}")
    ent = _f(r.get("entrapment_ratio"))
    hit(ent > 0.5, 22, f"entrapment {ent:.0%}") or hit(0.2 < ent <= 0.5, 16, f"entrapment {ent:.0%}")
    cc = _f(r.get("creator_created_count"))
    hit(cc >= 500, 18, f"dev launched {cc:,.0f} tokens") or hit(50 <= cc < 500, 10, f"dev launched {cc:,.0f} tokens")
    liq = _f(r.get("liquidity"))
    if r.get("launchpad_status") in (1, "1") or liq:
        hit(0 < liq < 10_000, 15, "liquidity < $10K") or hit(10_000 <= liq < 50_000, 6, "liquidity < $50K")
    rug = r.get("rug_ratio")
    s = max(0.0, s)
    if rug is not None and _f(rug) >= 0.5:
        s = min(s, 59); flags.append(f"GMGN rug label {_f(rug):.0%}")
    elif rug is not None and _f(rug) >= 0.3:
        s = min(s, 79); flags.append(f"GMGN rug label {_f(rug):.0%}")
    return int(round(s)), flags


def _norm_row(r: dict, chain: str, source: str) -> dict:
    created = _f(r.get("created_timestamp") or r.get("creation_timestamp") or r.get("open_timestamp"))
    q, flags = quick_safety(r, chain)
    return dict(address=r.get("address"), symbol=clean_symbol(r.get("symbol")), name=clean_symbol(r.get("name")),
                logo=r.get("logo") if str(r.get("logo") or "").startswith("https://") else None,
                mcap=_f(r.get("market_cap")), liquidity=_f(r.get("liquidity")),
                volume=_f(r.get("volume") or r.get("volume_24h")), chg_1h=_f(r.get("price_change_percent1h")) / 100,
                chg_5m=_f(r.get("price_change_percent5m")) / 100, holders=int(_f(r.get("holder_count"))),
                age_min=(time.time() - created) / 60 if created else None,
                smart=int(_f(r.get("smart_degen_count"))), kol=int(_f(r.get("renowned_count"))),
                top10=_f(r.get("top_10_holder_rate")), rug=r.get("rug_ratio"),
                launchpad=r.get("launchpad_platform") or r.get("launchpad") or "",
                progress=_f(r.get("progress")) if r.get("progress") is not None else None,
                callouts=int(_f(r.get("callout_count"))), safety=q, flags=flags, sources=[source],
                creator=r.get("creator"))


# ── Discover ────────────────────────────────────────────────────────────────────────────
def discover(client, chain: str, force=False) -> dict:
    key = ("discover", chain)
    if not force and (c := CACHE.get(key, 45)):
        return c
    rows, errors = {}, {}

    def add(r, source):
        if not r.get("address"):
            return
        n = _norm_row(r, chain, source)
        if n["address"] in rows:
            rows[n["address"]]["sources"].append(source)
            for k in ("rug", "progress", "creator"):
                if rows[n["address"]].get(k) is None and n.get(k) is not None:
                    rows[n["address"]][k] = n[k]
        else:
            rows[n["address"]] = n
    try:
        for r in client.trending(interval="1h", limit=100):
            add(r, "trending")
    except Exception as e:
        errors["trending"] = str(e)[:200]
    try:
        d = client.read(["market", "trenches", "--type", "new_creation", "--type", "near_completion",
                         "--type", "completed", "--limit", "40"])
        for bucket, tag in (("new_creation", "new"), ("near_completion", "almost bonded"), ("completed", "just bonded")):
            for r in (d or {}).get(bucket) or []:
                add(r, tag)
    except Exception as e:
        errors["new launches"] = str(e)[:200]
    try:
        d = client.read(["market", "hot-searches", "--chain", chain, "--interval", "1h", "--limit", "40"], chain=False)
        for block in d if isinstance(d, list) else [d]:
            for r in (block or {}).get("tokens") or []:
                add(r, "hot search")
    except Exception as e:
        errors["hot searches"] = str(e)[:200]
    callouts = []
    try:
        d = client.read(["callout", "global", "--chain", chain, "--limit", "30"], chain=False)
        items = d.get("list") if isinstance(d, dict) else d
        for c in items or []:
            callouts.append(c)
    except Exception as e:
        msg = str(e)
        errors["call-outs"] = "update gmgn-cli to see call-outs: npm install -g gmgn-cli@latest" if "unknown command" in msg else msg[:200]
    out = dict(chain=chain, ts=time.time(), tokens=sorted(rows.values(), key=lambda r: -(r["volume"] or 0)),
               callouts=callouts[:30], errors=errors)
    return CACHE.put(key, out)


def rug_for(chain, address):
    d = CACHE.get(("discover", chain), 3600)
    if d:
        for r in d["tokens"]:
            if r["address"] == address:
                return r.get("rug")
    return None


# ── Token dossier (CA research) ─────────────────────────────────────────────────────────
def token_dossier(client, chain: str, address: str, force=False) -> dict:
    key = ("token", chain, address)
    if not force and (c := CACHE.get(key, 60)):
        return c
    info = client.read(["token", "info", "--address", address])
    if not (info or {}).get("symbol"):
        return dict(kind="unknown", address=address, chain=chain)
    out = dict(kind="token", chain=chain, address=address, errors={})

    def safe(name, fn, default=None):
        try:
            return fn()
        except Exception as e:
            out["errors"][name] = str(e)[:200]
            return default
    security = safe("security", lambda: client.read(["token", "security", "--address", address]), {})
    kl = safe("chart", lambda: client.read(["market", "kline", "--address", address, "--resolution", "15m"]), {})
    raw_c = (kl.get("list") if isinstance(kl, dict) else kl) or []
    candles, bar_min = parse_candles(raw_c), 15
    if len(candles) < 30:                      # young token: 15m bars are too coarse to read, use 1m for the chart
        k1 = safe("chart", lambda: client.read(["market", "kline", "--address", address, "--resolution", "1m",
                                                 "--from", str(int(time.time()) - 6 * 3600), "--to", str(int(time.time()))]), {})
        c1 = parse_candles((k1.get("list") if isinstance(k1, dict) else k1) or [])
        if len(c1) > len(candles):
            candles, bar_min = c1, 1
    holders = safe("holders", lambda: client.read(["token", "holders", "--address", address, "--limit", "30"]), {})
    smart = safe("smart money", lambda: client.read(["token", "holders", "--address", address, "--limit", "20", "--tag", "smart_degen"]), {})
    kol = safe("KOLs", lambda: client.read(["token", "holders", "--address", address, "--limit", "20", "--tag", "renowned"]), {})
    dev = info.get("dev") or {}
    creator = dev.get("creator_address")
    created = safe("dev history", lambda: client.read(["portfolio", "created-tokens", "--wallet", creator]), {}) if creator else {}
    dd = contract_dd.score(info, security or {}, raw_c, chain, rug_ratio=rug_for(chain, address))
    price = info.get("price") or {}
    stat = info.get("stat") or {}
    tags = info.get("wallet_tags_stat") or {}

    def hrow(h):
        return dict(address=h.get("address"), name=clean_symbol(h.get("name") or h.get("twitter_username") or "") if (h.get("name") or h.get("twitter_username")) else "",
                    pct=_f(h.get("amount_percentage")), usd=_f(h.get("usd_value")), profit=_f(h.get("profit")),
                    unrealized=_f(h.get("unrealized_profit")), realized=_f(h.get("realized_profit")),
                    buys=int(_f(h.get("buy_tx_count_cur"))), sells=int(_f(h.get("sell_tx_count_cur"))),
                    tags=[t for t in (h.get("maker_token_tags") or []) + (h.get("tags") or []) if isinstance(t, str)][:4],
                    exchange=h.get("exchange"), since=h.get("start_holding_at"))
    link = info.get("link") or {}
    ath = (created or {}).get("creator_ath_info") or dev.get("ath_token_info") or {}
    out.update(
        token=dict(symbol=clean_symbol(info.get("symbol")), name=clean_symbol(info.get("name")),
                   logo=info.get("logo") if str(info.get("logo") or "").startswith("https://") else None,
                   price=_f(price.get("price")), mcap=_f(price.get("price")) * _f(info.get("circulating_supply") or info.get("total_supply")),
                   liquidity=_f(info.get("liquidity")), holders=int(_f(info.get("holder_count"))),
                   ath_price=_f(info.get("ath_price")), created=info.get("creation_timestamp"),
                   launchpad=info.get("launchpad_platform"), bonded=str(info.get("launchpad_status")) == "1",
                   progress=_f(info.get("launchpad_progress")),
                   chg={k: (_f(price.get("price")) / _f(price.get(f"price_{k}")) - 1) if _f(price.get(f"price_{k}")) else None for k in ("5m", "1h", "24h")},
                   vol={k: _f(price.get(f"volume_{k}")) for k in ("1h", "24h")},
                   buys_1h=int(_f(price.get("buys_1h"))), sells_1h=int(_f(price.get("sells_1h"))),
                   links={k: link.get(k) for k in ("website", "twitter_username", "telegram") if link.get(k)}),
        dd=dd,
        chart=dict(spark=spark(candles, 160), pattern=chart_read(candles) if len(candles) >= 10 else None, bar_min=bar_min, candles=len(candles)),
        holders=dict(top=[hrow(h) for h in (holders or {}).get("list") or []],
                     smart=[hrow(h) for h in (smart or {}).get("list") or []],
                     kol=[hrow(h) for h in (kol or {}).get("list") or []],
                     counts=dict(smart=tags.get("smart_wallets"), kol=tags.get("renowned_wallets"), fresh=tags.get("fresh_wallets"),
                                 sniper=tags.get("sniper_wallets"), bundler=tags.get("bundler_wallets"), rat=tags.get("rat_trader_wallets"),
                                 whale=tags.get("whale_wallets")),
                     stat={k: _f(stat.get(k)) for k in ("top_10_holder_rate", "creator_hold_rate", "top_bundler_trader_percentage",
                                                        "top70_sniper_hold_rate", "top_rat_trader_percentage", "bot_degen_rate",
                                                        "fresh_wallet_rate", "top_entrapment_trader_percentage")}),
        dev=dict(address=creator, launched=int(_f((created or {}).get("inner_count", dev.get("creator_open_count")))) + int(_f((created or {}).get("open_count"))) if created else int(_f(stat.get("creator_created_count"))),
                 bonded=int(_f((created or {}).get("open_count"))), bond_rate=_f((created or {}).get("open_ratio")),
                 holds=_f(stat.get("creator_hold_rate")), status=dev.get("creator_token_status") or "",
                 best=dict(symbol=clean_symbol(ath.get("token_symbol") or ath.get("symbol")), ath_mc=_f(ath.get("ath_mc"))) if ath and _f(ath.get("ath_mc")) < 1e12 else None,
                 recent=[dict(address=t.get("token_address"), symbol=clean_symbol(t.get("symbol")), mcap=_f(t.get("market_cap")),
                              ath_mc=_f(t.get("token_ath_mc")) if _f(t.get("token_ath_mc")) < 1e12 else None, bonded=bool(t.get("is_open")), created=t.get("create_timestamp"))
                         for t in ((created or {}).get("tokens") or [])[:12]],
                 x_renames=len(dev.get("twitter_name_change_history") or []),
                 x_deleted=int(_f(dev.get("twitter_del_post_token_count")))),
    )
    return CACHE.put(key, out)


# ── OHLCV for the trading chart ──────────────────────────────────────────────────────────
CANDLE_WINDOW = {"1m": 6 * 3600, "5m": 2 * 86400, "15m": 5 * 86400, "1h": 20 * 86400, "4h": 90 * 86400}


def candles(client, chain: str, address: str, res: str) -> dict:
    if res not in CANDLE_WINDOW:
        raise ValueError("timeframe must be one of " + ", ".join(CANDLE_WINDOW))
    key = ("candles", chain, address, res)
    if (c := CACHE.get(key, 20)):
        return c
    now = int(time.time())
    d = client.read(["market", "kline", "--address", address, "--resolution", res,
                     "--from", str(now - CANDLE_WINDOW[res]), "--to", str(now)])
    cs = parse_candles((d.get("list") if isinstance(d, dict) else d) or [])
    return CACHE.put(key, dict(res=res, candles=[[x["t"], x["o"], x["h"], x["l"], x["c"], x["v"]] for x in cs]))


# ── Wallet research ─────────────────────────────────────────────────────────────────────
def style_tag(trades_7d: int, winrate: float, pnl: float, avg_hold_s: float, trades_30d: int = -1) -> tuple[str, str]:
    if trades_30d == 0:
        return "no trades in 30 days", "—"
    speed = ("seconds" if avg_hold_s < 120 else "intraday" if avg_hold_s < 86400 else "swing" if avg_hold_s < 7 * 86400 else "long hold") if avg_hold_s else "unknown"
    if trades_7d > 2000:
        main = "bot-like volume"
    elif pnl > 0 and winrate >= 0.55:
        main = "consistent winner"
    elif pnl > 0:
        main = "a few big wins"
    elif winrate >= 0.5:
        main = "wins often, loses big"
    else:
        main = "losing money"
    return main, speed


def wallet_dossier(client, chain: str, wallet: str, force=False) -> dict:
    key = ("wallet", chain, wallet)
    if not force and (c := CACHE.get(key, 90)):
        return c
    out = dict(kind="wallet", chain=chain, address=wallet, errors={})

    def safe(name, fn, default=None):
        try:
            return fn()
        except Exception as e:
            out["errors"][name] = str(e)[:200]
            return default
    s7 = safe("7d stats", lambda: client.read(["portfolio", "stats", "--wallet", wallet, "--period", "7d"]), {}) or {}
    s30 = safe("30d stats", lambda: client.read(["portfolio", "stats", "--wallet", wallet, "--period", "30d"]), {}) or {}
    act = safe("activity", lambda: client.read(["portfolio", "activity", "--wallet", wallet, "--limit", "50"]), {}) or {}
    created = safe("launches", lambda: client.read(["portfolio", "created-tokens", "--wallet", wallet]), {}) or {}

    def period(s):
        p = s.get("pnl_stat") or {}
        return dict(realized=_f(s.get("realized_profit")), roi=_f(s.get("realized_profit_pnl")), buys=int(_f(s.get("buy"))),
                    sells=int(_f(s.get("sell"))), tokens=int(_f(p.get("token_num"))), winrate=_f(p.get("winrate")),
                    avg_hold_s=_f(p.get("avg_holding_period")), cost=_f(s.get("bought_cost")),
                    dist={"< -50%": int(_f(p.get("pnl_lt_nd5_num"))), "-50% to 0": int(_f(p.get("pnl_nd5_0x_num"))),
                          "0 to 2×": int(_f(p.get("pnl_0x_2x_num"))), "2× to 5×": int(_f(p.get("pnl_2x_5x_num"))),
                          "> 5×": int(_f(p.get("pnl_gt_5x_num")))})
    p7, p30 = period(s7), period(s30)
    common = s7.get("common") or s30.get("common") or {}
    main, speed = style_tag(p7["buys"] + p7["sells"], p30["winrate"], p30["realized"], p30["avg_hold_s"], p30["buys"] + p30["sells"])
    acts = []
    for a in (act.get("activities") or []):
        t = a.get("token") or {}
        acts.append(dict(ts=a.get("timestamp"), side=a.get("event_type"), token=t.get("address"), symbol=clean_symbol(t.get("symbol")),
                         usd=_f(a.get("cost_usd")), price=_f(a.get("price_usd"))))
    launched = int(_f(created.get("inner_count"))) + int(_f(created.get("open_count")))
    out.update(
        profile=dict(name=clean_symbol(common.get("name") or common.get("twitter_username") or "") if (common.get("name") or common.get("twitter_username")) else "",
                     twitter=common.get("twitter_username") or "", tags=[t for t in (common.get("tags") or []) if isinstance(t, str)][:6],
                     funded_by=clean_symbol(common.get("fund_from") or ""), age_days=(time.time() - _f(common.get("created_at"))) / 86400 if common.get("created_at") else None,
                     followers=int(_f(common.get("followers_count"))), balance=_f(s7.get("native_balance"))),
        p7=p7, p30=p30, style=dict(main=main, speed=speed, dev=launched > 0, launched=launched),
        activity=acts, last_active=s7.get("last_timestamp"))
    return CACHE.put(key, out)


def search(client, chain: str, q: str, client_for=None) -> dict:
    q = (q or "").strip()
    if not q:
        raise ValueError("type a contract address, wallet or token name")
    if is_address(q):
        # an address only makes sense on chains with its format: SOL is base58, BSC/Base/ETH are 0x
        evm = bool(EVM_ADDR.match(q))
        order = [chain] if (chain != "sol") == evm else []
        order += [c for c in (("bsc", "base", "eth") if evm else ("sol",)) if c not in order]
        for ch in order:
            c = client if ch == chain or not client_for else client_for(ch)
            try:
                info = c.read(["token", "info", "--address", q])
            except Exception:
                continue
            if (info or {}).get("symbol"):
                return dict(kind="token", address=q, chain=ch)
        # not a token on any matching chain: it's a wallet. EVM wallets are the same address on every
        # EVM chain, so stay on the current one if it's EVM, else default to BSC.
        return dict(kind="wallet", address=q, chain=chain if (chain != "sol") == evm else ("bsc" if evm else "sol"))
    results, note = [], None
    try:
        d = client.read(["market", "search", "-q", q, "--chain", chain], chain=False)
        toks = (d.get("tokens") or d.get("coins") or d.get("list") or []) if isinstance(d, dict) else (d or [])
        for t in toks[:15]:
            results.append(dict(address=t.get("address"), symbol=clean_symbol(t.get("symbol")), name=clean_symbol(t.get("name")),
                                mcap=_f(t.get("market_cap")), liquidity=_f(t.get("liquidity")), holders=int(_f(t.get("holder_count")))))
    except GMGNError as e:
        note = "update gmgn-cli for full name search (npm install -g gmgn-cli@latest). Showing matches from the live feeds." if "unknown command" in str(e) else str(e)[:200]
        feed = discover(client, chain)
        ql = q.lower()
        for t in feed["tokens"]:
            if ql in (t["symbol"] or "").lower() or ql in (t["name"] or "").lower():
                results.append({k: t[k] for k in ("address", "symbol", "name", "mcap", "liquidity", "holders")})
    results.sort(key=lambda r: -(r["mcap"] or 0))
    if len({r["symbol"].lower() for r in results if r["symbol"]}) < len(results):
        for r in results:
            r["copycat_risk"] = sum(1 for x in results if x["symbol"].lower() == r["symbol"].lower()) > 1
    return dict(kind="results", query=q, results=results, note=note)


# ── watchlist (followed wallets) + live tape ────────────────────────────────────────────
WATCH_PATH = DATA / "watchlist.json"


class Watchlist:
    MAX = 15

    def __init__(self):
        self.lock = threading.Lock()
        try:
            self.d = json.loads(WATCH_PATH.read_text(encoding="utf-8"))
        except Exception:
            self.d = {"wallets": []}
        self.seen = set()

    def save(self):
        WATCH_PATH.write_text(json.dumps(self.d, indent=1), encoding="utf-8")

    def wallets(self):
        return list(self.d["wallets"])

    def add(self, address, label=""):
        if not is_address(address):
            raise ValueError("not a wallet address")
        with self.lock:
            if any(w["address"] == address for w in self.d["wallets"]):
                return self.wallets()
            if len(self.d["wallets"]) >= self.MAX:
                raise ValueError(f"you can follow up to {self.MAX} wallets")
            self.d["wallets"].append(dict(address=address, label=clean_symbol(label)[:24], added=time.time()))
            self.save()
        return self.wallets()

    def remove(self, address):
        with self.lock:
            self.d["wallets"] = [w for w in self.d["wallets"] if w["address"] != address]
            self.save()
        return self.wallets()


class Tape:
    """Recent smart-money, KOL and followed-wallet trades with token symbols, newest first."""
    def __init__(self):
        self.rows, self.seen, self.lock = deque(maxlen=400), set(), threading.Lock()

    def add(self, kind, r, label="", chain="sol"):
        h = r.get("transaction_hash") or r.get("tx_hash")
        if not h or h in self.seen:
            return
        bt = r.get("base_token") or r.get("token") or {}
        mi = r.get("maker_info") or {}
        row = dict(h=h, chain=chain, ts=_f(r.get("timestamp")), kind=kind, side=r.get("side") or r.get("event_type"),
                   usd=_f(r.get("amount_usd") or r.get("cost_usd")), maker=r.get("maker") or r.get("wallet"),
                   who=clean_symbol(label or mi.get("name") or mi.get("twitter_username") or "") if (label or mi.get("name") or mi.get("twitter_username")) else "",
                   token=r.get("base_address") or bt.get("address"), symbol=clean_symbol(bt.get("symbol")))
        with self.lock:
            self.seen.add(h)
            self.rows.appendleft(row)
            if len(self.seen) > 4000:
                self.seen = {r.get("h") for r in self.rows}

    def list(self, kinds=None, limit=150, chain=None):
        with self.lock:
            rows = sorted(self.rows, key=lambda r: -r["ts"])
        return [r for r in rows if (not kinds or r["kind"] in kinds) and (not chain or r.get("chain") == chain)][:limit]


# ── GMGN script jobs (dev score, holder analysis, wallet analysis) ──────────────────────
class Jobs:
    SCRIPTS = {"dev": "dev_score.py", "holders": "holder_analysis.py", "wallet": "wallet_analysis.py"}
    TTL = 15 * 60

    def __init__(self):
        self.jobs, self.lock, self.run_lock = {}, threading.Lock(), threading.Lock()

    def get(self, kind, chain, target):
        with self.lock:
            j = self.jobs.get((kind, chain, target))
            return dict(j) if j else None

    def start(self, kind, chain, target):
        if kind not in self.SCRIPTS:
            raise ValueError("unknown analysis")
        if not is_address(target):
            raise ValueError("not an address")
        if not gmgn_bin():
            raise ValueError("gmgn-cli isn't installed")
        key = (kind, chain, target)
        with self.lock:
            j = self.jobs.get(key)
            if j and (j["status"] in ("queued", "running") or (j["status"] == "done" and time.time() - j["ended"] < self.TTL)):
                return dict(j)
            self.jobs[key] = dict(kind=kind, status="queued", started=time.time(), ended=0, output=None, error=None)
        threading.Thread(target=self._run, args=(key,), daemon=True).start()
        return self.get(*key)

    def _run(self, key):
        kind, chain, target = key
        args = {"dev": [chain, target, "10", "brief"], "holders": [target, chain, "en"], "wallet": [target, chain, "en"]}[kind]
        with self.run_lock:                         # one GMGN script at a time, so they don't stack up on the rate limit
            with self.lock:
                self.jobs[key]["status"] = "running"
            env = dict(__import__("os").environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                       GMGN_RATE_LIMIT_AUTO_RETRY_MAX_WAIT_MS="60000")
            try:
                r = subprocess.run([sys.executable, "-m", "kraken.vendor.run", self.SCRIPTS[kind], *args],
                                   capture_output=True, text=True, timeout=420, env=env, encoding="utf-8", errors="replace",
                                   cwd=str(ROOT))
                text = (r.stdout or "").replace("[OUTPUT COMPLETE — COPY ABOVE VERBATIM, DO NOT SUMMARIZE]", "")
                if kind == "dev":
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = None
                    out = dict(status="done" if data else "error", output=data, error=None if data else (r.stderr or text)[-600:])
                else:
                    ok = r.returncode == 0 and text.strip()
                    out = dict(status="done" if ok else "error", output=text.strip() if ok else None,
                               error=None if ok else (r.stderr or text)[-600:])
            except subprocess.TimeoutExpired:
                out = dict(status="error", output=None, error="took longer than 7 minutes; try again later")
            except Exception as e:
                out = dict(status="error", output=None, error=str(e)[:300])
            with self.lock:
                self.jobs[key].update(out, ended=time.time())
