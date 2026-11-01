"""Contract due-diligence score (0-100) for one token.

A Python implementation of GMGN's `gmgn-contract-dd` skill (MIT, (c) 2025 GMGN,
https://github.com/GMGNAI/gmgn-skills), steps 0-6: contract, holder and price sections scored
from 100 with worst-tier-per-field deductions, GMGN's own rug label as a cap, sections
renormalised over what returned data, and a coverage-based confidence.

Inputs are the raw gmgn-cli responses: `token info`, `token security`, `market kline --resolution 15m`
and optionally the `rug_ratio` taken from a trending/trenches row. Pure function, no I/O.
"""
from __future__ import annotations

EVM_SIX = {"bsc", "base", "eth", "robinhood", "arc", "stable"}
BANDS = [(80, "buyable"), (60, "buyable with conditions"), (40, "not advised"), (0, "do not buy")]


def _f(v):
    """float or None. '' / None / non-numeric are unavailable; '0' and 0 are real zeros."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _worst(value, tiers, cmp):
    """tiers: [(threshold, deduction, label)] ordered worst first; returns first match or None."""
    for th, d, label in tiers:
        if cmp(value, th):
            return d, label
    return None


class _Section:
    def __init__(self, name):
        self.name, self.score, self.executed, self.skipped, self.items = name, 100.0, 0, 0, []

    def check(self, available: bool, hit=None, field="", value=None):
        if not available:
            self.skipped += 1
            return
        self.executed += 1
        if hit:
            d, why = hit
            self.score -= d
            self.items.append(dict(section=self.name, field=field, value=value, deduction=-d, why=why))

    def clamp(self):
        return max(0.0, min(100.0, self.score))


def score(info: dict, security: dict, kline: list, chain: str, rug_ratio=None, pool: dict | None = None) -> dict:
    info, security = info or {}, security or {}
    pool = pool or info.get("pool") or {}
    stat = info.get("stat") or {}
    price = info.get("price") if isinstance(info.get("price"), dict) else {}
    evm = chain != "sol"
    out = dict(chain=chain, scored=False, deductions=[], caps=[], notes=[])

    # Step 0: does GMGN know this token?
    if not (info.get("symbol") or ""):
        out["reason"] = "no_record"
        return out

    # Step 1A: EVM security block populated?
    sec_keys = ("is_honeypot", "is_open_source", "is_blacklist", "is_renounced")
    num_empty = all((security.get(k) in (None, "", "0")) for k in ("top_10_holder_rate", "buy_tax", "sell_tax"))
    sec_populated = not (all(security.get(k) is None for k in sec_keys) and num_empty)
    # Step 1B: stat block populated?
    stat_fields = ("creator_hold_rate", "top_bundler_trader_percentage", "top70_sniper_hold_rate",
                   "top_rat_trader_percentage", "top_entrapment_trader_percentage", "bot_degen_rate",
                   "fresh_wallet_rate", "private_vault_hold_rate", "creator_created_count", "top_10_holder_rate")
    holder_count = _f(info.get("holder_count")) or 0
    stat_hc = _f(stat.get("holder_count")) or 0
    stat_populated = not ((stat_hc == 0 and holder_count > 0) or all(not (_f(stat.get(k)) or 0) for k in stat_fields))
    if not stat_populated:
        out["notes"].append("GMGN chain-analysis metrics (9 checks) unavailable for this token")
    candles = []
    for c in kline or []:
        try:
            candles.append(dict(o=float(c["open"]), h=float(c["high"]), c=float(c["close"]),
                                v=float(c.get("volume") or c.get("amount") or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    n = len(candles)
    caps, hard_stop = [], False

    # Step 2 + 3: contract
    con = _Section("contract")
    if not evm:
        rm, rf = security.get("renounced_mint"), security.get("renounced_freeze_account")
        con.check(True, (25, "mint authority not renounced: supply can be inflated") if rm is not True and str(rm) != "1" else None, "renounced_mint", rm)
        con.check(True, (20, "freeze authority not renounced: your tokens can be frozen") if rf is not True and str(rf) != "1" else None, "renounced_freeze_account", rf)
    else:
        hp = security.get("is_honeypot")
        if sec_populated:
            if hp is None:
                con.check(False); caps.append((79, "honeypot check missing"))
            else:
                con.check(True, None, "is_honeypot", hp)
                if hp is True or str(hp) == "1":
                    hard_stop = True
            os_ = security.get("is_open_source")
            if os_ is None:
                con.check(False); caps.append((79, "open-source check missing"))
            else:
                con.check(True, (15, "contract not open source: real logic can't be audited") if os_ is False or str(os_) == "0" else None, "is_open_source", os_)
            rn = security.get("is_renounced")
            con.check(rn is not None, (8, "ownership not renounced") if rn is False or str(rn) == "0" else None, "is_renounced", rn)
            bl = security.get("is_blacklist")
            con.check(bl is not None, (20, "contract can blacklist addresses") if bl is True or str(bl) == "1" else None, "is_blacklist", bl)
        else:
            for _ in range(4):
                con.check(False)
    bt, st = _f(security.get("buy_tax")), _f(security.get("sell_tax"))
    tax = max([t for t in (bt, st) if t is not None], default=None)
    if tax is not None and tax > 1:
        tax /= 100.0
    con.check(tax is not None and (not evm or sec_populated),
              _worst(tax, [(0.10, 25, "tax over 10%"), (0.05, 10, "tax over 5%")], lambda v, t: v > t) if tax is not None else None,
              "tax", tax)
    lock = security.get("lock_summary") or info.get("lock_summary") or {}
    is_locked = lock.get("is_locked") if isinstance(lock, dict) else None
    burn = security.get("burn_status") if security.get("burn_status") is not None else info.get("burn_status")
    if chain in ("arbitrum", "hyperevm"):
        con.check(False)
    elif not evm:
        if is_locked is None or burn in (None, ""):
            con.check(False)
        else:
            con.check(True, (12, "LP neither locked nor burned") if is_locked is False and burn != "burn" else None, "lp_lock", f"locked={is_locked} burn={burn}")
    elif chain in EVM_SIX:
        if is_locked is None:
            con.check(False)
        else:
            unlocked = is_locked is False
            con.check(True, (12, "LP not locked") if unlocked else None, "lp_lock", is_locked)
            if unlocked:
                caps.append((79, "LP not locked"))
    else:
        con.check(False)
    liq_i, liq_p = _f(info.get("liquidity")), _f(pool.get("liquidity"))
    liq = liq_p if (liq_i in (None, 0) and liq_p) else liq_i
    vol24 = _f(price.get("volume_24h"))
    if liq == 0 and not liq_p and (vol24 or 0) > 0:
        liq = None
    con.check(liq is not None, _worst(liq, [(10_000, 15, "liquidity under $10K"), (50_000, 6, "liquidity under $50K")], lambda v, t: v < t) if liq is not None else None, "liquidity", liq)
    init_liq = _f(pool.get("initial_liquidity"))
    shrink_ok = bool(init_liq) and liq_p is not None
    con.check(shrink_ok, (10, "pool shrank below half its opening depth") if shrink_ok and liq_p / init_liq < 0.5 else None, "pool_shrink", (liq_p / init_liq) if shrink_ok else None)
    if stat_populated:
        cc = _f(stat.get("creator_created_count"))
        con.check(cc is not None, _worst(cc, [(500, 18, "creator launched 500+ tokens"), (200, 14, "creator launched 200+ tokens"),
                                              (50, 10, "creator launched 50+ tokens"), (10, 6, "creator launched 10+ tokens"),
                                              (3, 3, "creator launched 3+ tokens")], lambda v, t: v >= t) if cc is not None else None,
                  "creator_created_count", cc)
    dup = _f(info.get("image_dup_count"))
    con.check(dup is not None, (6, "logo shared with other tokens") if dup and dup > 0 else None, "image_dup_count", dup)
    con.check(True, _worst(n, [(8, 12, "fewer than 8 candles: price can't be verified yet"), (24, 6, "under 24 candles of history")], lambda v, t: v < t), "candles", n)

    # Step 4: holders
    hol = _Section("holders")
    t10 = _f(security.get("top_10_holder_rate")) or _f(stat.get("top_10_holder_rate")) or None
    hol.check(t10 is not None, _worst(t10, [(0.5, 25, "top 10 hold over 50%"), (0.3, 14, "top 10 hold over 30%"), (0.2, 6, "top 10 hold over 20%")], lambda v, t: v > t) if t10 else None, "top_10_holder_rate", t10)
    hc = holder_count or None
    hol.check(hc is not None, _worst(hc, [(200, 12, "under 200 holders"), (500, 5, "under 500 holders")], lambda v, t: v < t) if hc else None, "holder_count", hc)
    if stat_populated:
        rules = [
            ("creator_hold_rate", [(0.05, 20, "creator holds over 5%"), (0.02, 10, "creator holds over 2%")]),
            ("top_bundler_trader_percentage", [(0.30, 20, "bundlers over 30%"), (0.15, 10, "bundlers over 15%"), (0.05, 4, "bundlers over 5%")]),
            ("top70_sniper_hold_rate", [(0.15, 15, "snipers hold over 15%"), (0.05, 6, "snipers hold over 5%")]),
            ("top_rat_trader_percentage", [(0.05, 12, "rat traders over 5%"), (0.01, 5, "rat traders over 1%")]),
            ("top_entrapment_trader_percentage", [(0.50, 22, "entrapment traders over 50%"), (0.20, 16, "entrapment traders over 20%"), (0.05, 10, "entrapment traders over 5%")]),
            ("bot_degen_rate", [(0.70, 12, "bots over 70%"), (0.50, 6, "bots over 50%")]),
            ("fresh_wallet_rate", [(0.50, 8, "fresh wallets over 50%")]),
            ("private_vault_hold_rate", [(0.05, 8, "private vaults hold over 5%")]),
        ]
        for k, tiers in rules:
            v = _f(stat.get(k))
            hol.check(v is not None, _worst(v, tiers, lambda a, b: a > b) if v is not None else None, k, v)

    # Step 5: price (needs 8+ candles)
    pri = None
    if n >= 8:
        pri = _Section("price")
        W = candles[-96:]
        H, C, O, V = [x["h"] for x in W], [x["c"] for x in W], [x["o"] for x in W], [x["v"] for x in W]
        mh = max(H)
        dd = (1 - C[-1] / mh) if mh else None
        pri.check(dd is not None, _worst(dd, [(0.7, 30, "down over 70% from the window high"), (0.5, 18, "down over 50% from the window high"), (0.3, 8, "down over 30% from the window high")], lambda v, t: v > t) if dd is not None else None, "drawdown", dd)
        moves = [(c - o) / o for c, o in zip(C, O) if o]
        wc = min(moves) if moves else None
        pri.check(wc is not None, _worst(wc, [(-0.5, 14, "a single candle fell over 50%"), (-0.3, 7, "a single candle fell over 30%")], lambda v, t: v < t) if wc is not None else None, "worst_candle", wc)
        p_now, p24 = _f(price.get("price")), _f(price.get("price_24h"))
        ok = bool(p_now is not None and p24)
        pri.check(ok, (10, "price halved in 24h") if ok and p_now / p24 < 0.5 else None, "price_vs_24h", (p_now / p24) if ok else None)
        early = sum(V[-40:-20]) / 20 if len(V) >= 40 else 0
        vr_ok = len(V) >= 40 and early > 0
        vr = (sum(V[-20:]) / 20) / early if vr_ok else None
        pri.check(vr_ok, (18, "volume collapsed below 20% of the earlier window") if vr_ok and vr < 0.2 else None, "vol_ratio", vr)

    # Step 5B: GMGN rug label caps
    rr = _f(rug_ratio)
    if rr is not None:
        if rr >= 0.5:
            caps.append((59, f"GMGN rug label {rr:.0%}"))
        elif rr >= 0.3:
            caps.append((79, f"GMGN rug label {rr:.0%}"))

    # Step 6: combine
    sections = [(con, 0.45), (hol, 0.35)] + ([(pri, 0.20)] if pri else [])
    sections = [(s, w) for s, w in sections if s.executed > 0]
    if not sections:
        out["reason"] = "no_data"
        return out
    tw = sum(w for _, w in sections)
    comp = sum(s.clamp() * w / tw for s, w in sections)
    if caps:
        cap = min(c for c, _ in caps)
        comp = min(comp, cap)
    if hard_stop:
        # Step 7: a honeypot flag contradicted by heavy two-sided trading (tokenized stocks, RWAs and some
        # stablecoins trip the sell simulator). Only when privileges were reported AND are empty, and no tax:
        # downgrade the flag to unconfirmed and cap at 59 instead of forcing 0.
        sells, sv, bv = _f(price.get("sells_24h")), _f(price.get("sell_volume_24h")), _f(price.get("buy_volume_24h"))
        priv = security.get("privileges")
        no_tax = tax is not None and tax == 0
        if (sells or 0) > 500 and (sv or 0) > 100_000 and bv and 0.3 <= sv / bv <= 3.0 and no_tax and isinstance(priv, list) and not priv:
            hard_stop = False
            caps.append((59, "honeypot flag contradicted by live trading (unconfirmed)"))
            comp = min(comp, 59)
            out["notes"].append(f"GMGN's simulator flags a honeypot, but {int(sells):,} sells (${sv:,.0f}) went through in 24h, "
                                "so the flag is treated as unconfirmed. Check before buying.")
        else:
            comp = 0.0
            out["notes"].append("flagged as a honeypot: you may not be able to sell")
    comp = max(0.0, min(100.0, comp))
    executed = sum(s.executed for s in (con, hol) + ((pri,) if pri else ()))
    skipped = sum(s.skipped for s in (con, hol) + ((pri,) if pri else ())) + (4 if not pri else 0)
    coverage = executed / (executed + skipped) if executed + skipped else 0
    conf = "evidence sufficient" if coverage >= 0.8 else "coverage low" if coverage >= 0.5 else "insufficient evidence"
    secs = {s.name: round(s.clamp(), 1) for s, _ in sections}
    low = [k for k, v in secs.items() if v < 60]
    if len(low) >= 2:
        profile = "problems on more than one side"
    elif low == ["holders"]:
        profile = "contract is fine, the supply is concentrated"
    elif low == ["price"]:
        profile = "contract is fine, the price structure has broken"
    elif low == ["contract"]:
        profile = "the problem is in the contract itself"
    elif secs.get("contract", 100) < 80:
        profile = "no clear problem, but the contract side is thin"
    else:
        profile = "nothing standing in the way on any side"
    band = next(b for th, b in BANDS if comp >= th)
    out.update(scored=True, score=round(comp, 1), band=band, profile=profile, sections=secs,
               confidence=conf, coverage=round(coverage, 3), honeypot=hard_stop,
               caps=[dict(cap=c, why=w) for c, w in caps], rug_ratio=rr,
               deductions=sorted(con.items + hol.items + (pri.items if pri else []), key=lambda d: d["deduction"]))
    return out
