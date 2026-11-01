<div align="center">

# 🐙 kraken

**Self-hosted memecoin screener, Base Hunter and learning loop, built on [gmgn-cli](https://www.npmjs.com/package/gmgn-cli).**

Find coins resting in a quiet floor after their first pump, before the breakout. Snapshot every find, grade what happened next, and let a small model learn which setups actually work, from *your* data.

Runs on your own computer · keys never leave it · paper trading by default · works with no key (demo mode)

</div>

---

## Quick install

You need **Python 3.10+**. Node.js is optional (only for live GMGN data).

**Windows**
```powershell
git clone https://github.com/B3an-boi/Kraken.git
cd Kraken
.\install.cmd
.\run.cmd
```

**macOS / Linux**
```bash
git clone https://github.com/B3an-boi/Kraken.git
cd Kraken
./install.sh
./run.sh
```

kraken opens at **http://127.0.0.1:8420**. It starts on **demo data** (a simulated market), so you can try every feature before connecting anything.

No git? Click **Code → Download ZIP** on GitHub, unzip, and run the same install/run commands inside the folder.

### Connect real GMGN data (optional)

1. Install Node.js 18+, then `npm install -g gmgn-cli` (the installer offers this).
2. Get an API key at **[gmgn.ai/ai](https://gmgn.ai/ai)**. It's bound to your IP and your Ed25519 public key, so each person uses their own.
3. Run the setup wizard and paste the key:
   ```bash
   .venv/bin/python -m kraken setup          # macOS / Linux
   .\.venv\Scripts\python.exe -m kraken setup  # Windows
   ```
4. Restart kraken. The top bar switches from **demo data** to **GMGN live data**.

The signing (private) key is **only** needed for LIVE trading. Leave it blank to stay paper-only.

Check your install any time with `python -m kraken doctor`.

---

## What's inside

| Tab | What it does |
|---|---|
| **Base Hunter** | Scans trending tokens for a *post-pump floor* (launch pump → deep flush → long, flat, quiet base near the lows) or *any tight range*. Each card shows the chart with the base boxed, pump/flush stats, smart-money flow inside the base, a 0-100 score, and dip/breakout entry levels. |
| **Screener** | Pulls trending tokens, runs safety gates (honeypot, mint authority, taxes, rug ratio, bundlers, dev and top-10 holdings), a market/consensus gate, then a transparent momentum score. Every rejected token shows *why*. |
| **Positions** | One-click Buy and Sell. **SHADOW** (default) records paper trades at live prices; **LIVE** sends real swaps through gmgn-cli. Risk limits on size, open positions, total exposure and daily loss. An exit monitor flags stop-loss, take-profit and safety drops. |
| **Learning** | Every Base Hunter find is snapshotted. After the horizon (default 120 min) it's labeled a **win** if price rose +30% before falling −15%. After 40 labeled outcomes a logistic-regression model trains, is tested on a time-ordered holdout, and only gets a say in the score if it beats the rule score. |
| **Backtest** | What-if filters over your labeled snapshots ("what if max range were 10%?", "what if min pump were 4×?"), plus win rate by bucket for score, base range, base length, pump size, retrace, volume decay and smart-money flow. |
| **Alerts** | Push notifications via **ntfy**, **Telegram** or **Discord** when Base Hunter finds a high-scoring floor, the screener passes a token, or a position raises an exit signal. |
| **Settings** | Every threshold is editable in the UI, validated, and saved to `data/settings.json` so it survives restarts. |

More detail: **[How it works](docs/how-it-works.md)** · **[Settings reference](docs/settings.md)** · **[Alerts setup](docs/alerts.md)**

---

## Safety

- **Local only.** The server binds to `127.0.0.1` and rejects API requests from other machines.
- **Keys stay on your computer** in gmgn-cli's own env file (`~/.config/gmgn/.env`). kraken never sends them anywhere except to gmgn-cli.
- **Paper by default.** LIVE mode needs both an API key and a signing key, and asks you to confirm. Every real buy and sell asks again.
- **Human in the loop.** kraken never opens or closes a trade on its own. Exit signals only alert you.
- **Rate-limit aware.** Every GMGN call goes through one gate that spaces calls and backs off after a 429, so your key doesn't get banned.

## Project layout

```
kraken/
├── kraken/
│   ├── server.py      FastAPI app, endpoints and background loop
│   ├── gmgn.py        gmgn-cli client, rate gate, demo market
│   ├── screener.py    safety gates + momentum score
│   ├── hunter.py      Base Hunter scan, flow polling, labeling
│   ├── basehunter.py  floor detection, features, scoring, sample store, model
│   ├── charts.py      chart read, tight-range detection, sparklines
│   ├── positions.py   paper/live trades, risk limits, exit monitor
│   ├── alerts.py      ntfy / Telegram / Discord
│   ├── backtest.py    win-rate buckets and what-if filters
│   └── config.py      settings with validation + persistence
├── web/               the dashboard (plain HTML/CSS/JS, no build step)
├── data/              your local data (git-ignored)
├── install.ps1 / install.cmd / install.sh
└── run.cmd / run.sh
```

## Options

| Environment variable | Default | Meaning |
|---|---|---|
| `KRAKEN_PORT` | `8420` | Port to serve on |
| `KRAKEN_HOST` | `127.0.0.1` | Bind address. Changing it exposes kraken on your network; API calls from other machines are still refused unless `KRAKEN_ALLOW_REMOTE=1` |
| `KRAKEN_DEMO` | off | `1` forces demo data even when a key is set |
| `KRAKEN_DATA` | `./data` | Where settings, snapshots and positions are stored |
| `KRAKEN_NO_BROWSER` | off | Any value stops kraken from opening a browser tab |

## Disclaimer

kraken is a research and screening tool, **not financial advice**. Memecoins are extremely risky, and most go to zero. Past win rates don't predict future results. If you enable LIVE trading you are responsible for every trade. Use at your own risk.

kraken is an independent project and is not affiliated with or endorsed by GMGN. It talks to GMGN only through the public `gmgn-cli` tool, under your own API key.

## License

[MIT](LICENSE)
