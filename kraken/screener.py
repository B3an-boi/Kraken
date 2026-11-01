"""Token screener: trending rows → safety gates → consensus gate → momentum score.

Every rejection keeps its reason so the UI can show *why* a token was cut."""
from __future__ import annotations
import math, re, time
from dataclasses import dataclass, asdict

_SAFE = re.compile(r"[^\w\-. $]", re.UNICODE)


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else d
    except (TypeError, ValueError):
        return d


def _b(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


def clean_symbol(s) -> str:
    """Token names are attacker-controlled: strip markup/control chars and cap the length."""
    return _SAFE.sub("", str(s or "?"))[:24] or "?"


@dataclass
class Token:
    address: str
    symbol: str
    price: float
    mcap: float
    liquidity: float
    volume: float
    age_min: float
    chg_1h: float
    chg_5m: float
    buy_ratio: float
    holders: int
    top10: float
    dev_hold: float
    bundler: float
    rug_ratio: float
    honeypot: bool
    renounced: bool
    buy_tax: float
    sell_tax: float
    smart: int
    kol: int
    ath_mcap: float

    @property
    def sm_confluence(self) -> int:
        return self.smart + self.kol

    @classmethod
    def from_row(cls, r: dict) -> "Token":
        created = _f(r.get("creation_timestamp") or r.get("open_timestamp"))
        if created > 1e11:
            created /= 1000
        buys, sells = _f(r.get("buys")), _f(r.get("sells"))
        return cls(
            address=str(r.get("address") or ""), symbol=clean_symbol(r.get("symbol")),
            price=_f(r.get("price")), mcap=_f(r.get("market_cap")), liquidity=_f(r.get("liquidity")),
            volume=_f(r.get("volume")),
            age_min=max(0.0, (time.time() - created) / 60) if created else 0.0,
            chg_1h=_f(r.get("price_change_percent1h")) / 100, chg_5m=_f(r.get("price_change_percent5m")) / 100,
            buy_ratio=buys / (buys + sells) if buys + sells else 0.5, holders=int(_f(r.get("holder_count"))),
            top10=_f(r.get("top_10_holder_rate")), dev_hold=_f(r.get("dev_team_hold_rate")),
            bundler=_f(r.get("bundler_rate")), rug_ratio=_f(r.get("rug_ratio")),
            honeypot=_b(r.get("is_honeypot")), renounced=_b(r.get("renounced_mint")),
            buy_tax=_f(r.get("buy_tax")), sell_tax=_f(r.get("sell_tax")),
            smart=int(_f(r.get("smart_degen_count"))), kol=int(_f(r.get("renowned_count"))),
            ath_mcap=_f(r.get("history_highest_market_cap")))


def safety_check(t: Token, c: dict) -> str | None:
    """Return a rejection reason, or None if the token passes every safety gate."""
    if t.honeypot:
        return "honeypot"
    if c["require_renounced"] and not t.renounced:
        return "mint authority not renounced"
    if t.buy_tax > c["max_buy_tax"] or t.sell_tax > c["max_sell_tax"]:
        return f"tax {t.buy_tax:.0%}/{t.sell_tax:.0%}"
    if t.rug_ratio > c["max_rug"]:
        return f"rug ratio {t.rug_ratio:.0%}"
    if t.bundler > c["max_bundler"]:
        return f"bundled {t.bundler:.0%}"
    if t.dev_hold > c["max_dev_hold"]:
        return f"dev holds {t.dev_hold:.0%}"
    if t.top10 > c["max_top10"]:
        return f"top 10 hold {t.top10:.0%}"
    return None


def market_check(t: Token, c: dict) -> str | None:
    if t.liquidity < c["min_liquidity"]:
        return f"liquidity ${t.liquidity:,.0f}"
    if t.mcap < c["min_mcap"] or (c["max_mcap"] and t.mcap > c["max_mcap"]):
        return f"market cap ${t.mcap:,.0f} out of range"
    if t.sm_confluence < c["min_smart_money"]:
        return f"only {t.sm_confluence} smart money / KOL"
    return None


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def score(t: Token) -> tuple[int, list[str]]:
    """0-100 momentum + quality score with the main reasons. Simple, transparent, tunable."""
    parts = [
        (22, _clip((t.chg_1h + 0.1) / 0.6), "1h momentum"),
        (12, _clip((t.chg_5m + 0.02) / 0.12), "5m momentum"),
        (16, _clip((t.buy_ratio - 0.45) / 0.2), "buy pressure"),
        (16, _clip(math.log10(1 + t.sm_confluence) / math.log10(16)), "smart money / KOL"),
        (10, _clip((t.liquidity / t.mcap if t.mcap else 0) / 0.2), "liquidity depth"),
        (8, _clip(math.log10(1 + t.holders) / 3.5), "holders"),
        (10, 1 - _clip((t.top10 - 0.15) / 0.25), "distribution"),
        (6, 1 - _clip(t.bundler / 0.3), "few bundlers"),
    ]
    s = sum(w * v for w, v, _ in parts)
    if t.chg_1h < -0.25:
        s *= 0.5
    best = sorted(parts, key=lambda p: -p[0] * p[1])[:3]
    return int(round(_clip(s / 100) * 100)), [f"{n} {v:.0%}" for _, v, n in best]


def run(client, c: dict) -> dict:
    rows = client.trending(interval=c["interval"], limit=c["limit"])
    funnel = dict(scanned=len(rows), safety=0, market=0, scored=0, passed=0)
    out = []
    for r in rows:
        if not r.get("address"):
            continue
        t = Token.from_row(r)
        why = safety_check(t, c)
        stage = "safety"
        if not why:
            funnel["safety"] += 1
            why, stage = market_check(t, c), "market"
        if not why:
            funnel["market"] += 1
            s, reasons = score(t)
            funnel["scored"] += 1
            ok = s >= c["min_score"]
            funnel["passed"] += ok
            out.append(dict(token=asdict(t), score=s, reasons=reasons, status="pass" if ok else "low score",
                            stage="score"))
        elif c.get("show_rejected", True):
            out.append(dict(token=asdict(t), score=None, reasons=[why], status="rejected", stage=stage))
    out.sort(key=lambda o: (o["score"] is None, -(o["score"] or 0)))
    return dict(results=out, funnel=funnel, ts=time.time())
