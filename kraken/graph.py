"""Wallet connection graph: who funded a wallet, who it moves money with, what it created and trades.

Nodes are wallets, exchanges and tokens; every edge says exactly what happened and when.
Built from GMGN data only (portfolio stats/activity/created-tokens). Any node can be expanded,
which runs the same build for that wallet so the graph grows outward like a mind map."""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor

from .research import CACHE, _f, is_address
from .screener import clean_symbol

ROLE_TAGS = {"smart_degen": "smart money", "renowned": "KOL", "kol": "KOL", "sniper": "sniper", "bundler": "bundler",
             "rat_trader": "rat trader", "dev": "dev", "creator": "dev", "fresh_wallet": "fresh wallet", "whale": "whale",
             "arbitrager": "arbitrage bot", "dex_bot": "bot"}


def _amt(x: float) -> str:
    """989842.1 -> 989.8K, 0.0718 -> 0.0718"""
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= div:
            return f"{x / div:.1f}{suf}"
    return f"{x:.4g}"


def wallet_info(client, chain, addr) -> dict:
    """One stats call (cached 10 min) -> who this wallet is."""
    key = ("winfo", chain, addr)
    if (c := CACHE.get(key, 600)):
        return c
    try:
        s = client.read(["portfolio", "stats", "--wallet", addr, "--period", "30d"]) or {}
    except Exception as e:
        return dict(address=addr, error=str(e)[:120])
    c = s.get("common") or {}
    p = s.get("pnl_stat") or {}
    tags = [t for t in (c.get("tags") or []) if isinstance(t, str)]
    roles = sorted({ROLE_TAGS[t] for t in tags if t in ROLE_TAGS})
    created = int(_f(c.get("created_token_count")))
    if created and "dev" not in roles:
        roles.append("dev")
    trades = int(_f(s.get("buy"))) + int(_f(s.get("sell")))
    if not trades and not created:
        roles.append("no trades (transfer wallet)")
    fund_name = clean_symbol(c.get("fund_from") or "") if c.get("fund_from") and not is_address(str(c.get("fund_from"))) else ""
    info = dict(address=addr, name=clean_symbol(c.get("name") or c.get("twitter_username") or "") if (c.get("name") or c.get("twitter_username")) else "",
                twitter=c.get("twitter_username") or "", tags=tags, roles=roles, created_tokens=created,
                trades_30d=trades, realized_30d=_f(s.get("realized_profit")), winrate=_f(p.get("winrate")),
                balance=_f(s.get("native_balance")), age_days=(time.time() - _f(c.get("created_at"))) / 86400 if c.get("created_at") else None,
                funder=c.get("fund_from_address") or None, funder_name=fund_name, fund_amount=_f(c.get("fund_amount")),
                fund_ts=_f(c.get("fund_from_ts")) or None, followers=int(_f(c.get("followers_count"))))
    return CACHE.put(key, info)


def _transfers(client, addr, pages=2):
    rows, cursor = [], None
    for _ in range(pages):
        args = ["portfolio", "activity", "--wallet", addr, "--type", "transferIn", "--type", "transferOut", "--limit", "50"]
        if cursor:
            args += ["--cursor", cursor]
        try:
            d = client.read(args) or {}
        except Exception:
            break
        rows += d.get("activities") or []
        cursor = d.get("next")
        if not cursor or len(d.get("activities") or []) < 50:
            break
    return rows


def build(client, chain: str, addr: str, enrich=10) -> dict:
    """Graph around one wallet. Returns {nodes, edges, center}."""
    key = ("graph", chain, addr)
    if (c := CACHE.get(key, 300)):
        return c
    nodes, edges = {}, []

    def node(id_, **kw):
        n = nodes.setdefault(id_, dict(id=id_, type="wallet", label=id_[:4] + "…" + id_[-4:]))
        n.update({k: v for k, v in kw.items() if v not in (None, "")})
        return n

    me = wallet_info(client, chain, addr)
    node(addr, type="center", label=me.get("name") or addr[:4] + "…" + addr[-4:], info=me)

    # 1. who funded it
    if me.get("funder"):
        f = me["funder"]
        is_exchange = bool(me.get("funder_name"))
        node(f, type="exchange" if is_exchange else "wallet", label=me["funder_name"] or f[:4] + "…" + f[-4:],
             exchange=me.get("funder_name") or None)
        edges.append(dict(source=f, target=addr, kind="funded", amount=me.get("fund_amount"), ts=me.get("fund_ts"),
                          label=f"first funded {me.get('fund_amount') or '?'} native" + (f" via {me['funder_name']}" if is_exchange else "")))

    # 2. who it moves money with (transfers in and out, aggregated per counterparty)
    flows = {}
    for a in _transfers(client, addr):
        incoming = a.get("event_type") in ("transfer_in", "transferIn")
        other = a.get("from_address") if incoming else a.get("to_address")
        if not other or other == addr:
            continue
        k = (other, "in" if incoming else "out")
        sym = clean_symbol((a.get("token") or {}).get("symbol"))
        g = flows.setdefault(k, dict(count=0, usd=0.0, tokens={}, first=None, last=None))
        g["count"] += 1
        g["usd"] += _f(a.get("cost_usd"))
        g["tokens"][sym] = g["tokens"].get(sym, 0) + _f(a.get("token_amount"))
        ts = _f(a.get("timestamp")) or None
        if ts:
            g["first"] = min(g["first"] or ts, ts)
            g["last"] = max(g["last"] or ts, ts)
    for (other, direction), g in flows.items():
        node(other)
        toks = ", ".join(f"{_amt(amt)} {s}" for s, amt in sorted(g["tokens"].items(), key=lambda kv: -kv[1])[:3])
        edges.append(dict(source=other if direction == "in" else addr, target=addr if direction == "in" else other,
                          kind="sent", count=g["count"], usd=round(g["usd"], 2), first=g["first"], last=g["last"],
                          label=f"{'received' if direction == 'in' else 'sent'} {g['count']}× · {toks}" + (f" (${g['usd']:,.0f})" if g["usd"] else "")))

    # 3. tokens it created, and what it trades most
    try:
        ct = client.read(["portfolio", "created-tokens", "--wallet", addr]) or {}
    except Exception:
        ct = {}
    for t in (ct.get("tokens") or [])[:8]:
        ta = t.get("token_address")
        if not ta:
            continue
        ath = _f(t.get("token_ath_mc"))
        node(ta, type="token", label=clean_symbol(t.get("symbol")), token=dict(mcap=_f(t.get("market_cap")), ath_mc=ath if ath < 1e12 else None,
                                                                               bonded=bool(t.get("is_open"))))
        edges.append(dict(source=addr, target=ta, kind="created", ts=_f(t.get("create_timestamp")) or None,
                          label="created" + (" · bonded" if t.get("is_open") else " · never bonded")))
    try:
        act = client.read(["portfolio", "activity", "--wallet", addr, "--type", "buy", "--limit", "50"]) or {}
    except Exception:
        act = {}
    spent = {}
    for a in act.get("activities") or []:
        t = a.get("token") or {}
        if t.get("address"):
            g = spent.setdefault(t["address"], dict(symbol=clean_symbol(t.get("symbol")), usd=0.0, n=0, last=0))
            g["usd"] += _f(a.get("cost_usd"))
            g["n"] += 1
            g["last"] = max(g["last"], _f(a.get("timestamp")))
    for ta, g in sorted(spent.items(), key=lambda kv: -kv[1]["usd"])[:6]:
        if ta not in nodes:
            node(ta, type="token", label=g["symbol"])
        edges.append(dict(source=addr, target=ta, kind="bought", usd=round(g["usd"], 2), count=g["n"], ts=g["last"] or None,
                          label=f"bought {g['n']}× · ${g['usd']:,.0f}"))

    # 4. say who the busiest neighbours are (one lookup each), and flag shared funders
    wallets = [e["source"] if e["target"] == addr else e["target"] for e in edges if e["kind"] == "sent"]
    ranked = sorted(set(wallets), key=lambda w: -sum(e.get("count", 0) for e in edges if w in (e["source"], e["target"])))[:enrich]
    with ThreadPoolExecutor(max_workers=4) as ex:
        infos = list(ex.map(lambda w: wallet_info(client, chain, w), ranked))
    for inf in infos:
        if inf.get("error"):
            continue
        n = node(inf["address"], info=inf, label=inf.get("name") or None)
        if inf["roles"]:
            n["roles"] = inf["roles"]
        if inf.get("funder") and inf["funder"] == me.get("funder"):
            n["shares_funder"] = True
            edges.append(dict(source=me["funder"], target=inf["address"], kind="funded",
                              amount=inf.get("fund_amount"), ts=inf.get("fund_ts"),
                              label=f"also funded this wallet ({inf.get('fund_amount') or '?'} native): same source"))
        elif inf.get("funder") and inf["funder"] in nodes:
            edges.append(dict(source=inf["funder"], target=inf["address"], kind="funded", amount=inf.get("fund_amount"),
                              ts=inf.get("fund_ts"), label=f"first funded {inf.get('fund_amount') or '?'} native"))
    out = dict(center=addr, chain=chain, nodes=list(nodes.values()), edges=edges,
               summary=dict(counterparties=len({w for w in wallets}), shared_funder=sum(1 for n in nodes.values() if n.get("shares_funder")),
                            created=sum(1 for e in edges if e["kind"] == "created")))
    return CACHE.put(key, out)
