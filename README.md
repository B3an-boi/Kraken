<div align="center">

# 🐙 kraken

**Self-hosted memecoin screener, Base Hunter and learning loop, built on [gmgn-cli](https://www.npmjs.com/package/gmgn-cli).**

Find coins resting in a quiet floor after their first pump, before the breakout. Snapshot every find, grade what happened next, and let a small model learn which setups actually work, from *your* data.

Runs on your own computer · uses your own GMGN API key · keys never leave your machine · paper trading by default

[![Download](https://img.shields.io/github/v/release/B3an-boi/Kraken?label=Download&style=for-the-badge&color=3ef0c6)](https://github.com/B3an-boi/Kraken/releases/latest)
[![VirusTotal](https://img.shields.io/badge/VirusTotal-report-394EFF?style=for-the-badge&logo=virustotal&logoColor=white)](https://www.virustotal.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

</div>

---

## Requirements

- **Python 3.10+**
- **Node.js 18+** (for `gmgn-cli`, GMGN's official command-line tool)
- **A GMGN API key** from **[gmgn.ai/ai](https://gmgn.ai/ai)**. The free tier works; Plus is much faster. Each key is bound to your IP and your Ed25519 public key, so everyone uses their own.

## Quick install

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

The installer sets up Python, installs `gmgn-cli`, and asks for your GMGN API key. kraken then opens at **http://127.0.0.1:8420** with live GMGN data.

No git? Download the ZIP from the [latest release](https://github.com/B3an-boi/Kraken/releases/latest), unzip it, and run the same commands inside the folder.

### Verify your download

Before you run anything, check the ZIP is safe:

1. Go to **[virustotal.com](https://www.virustotal.com)**, choose **File**, and drop in the `kraken-vX.X.X.zip` you downloaded.
2. Wait for the scan. It should show **0 security vendors flagged this file**.
3. Or just click the **VirusTotal** button at the top of this page. It opens the report for the official release ZIP. If your file is identical, uploading it opens that same report.

kraken contains no .exe files. It's plain Python and JavaScript you can open and read.

### Your keys

- **API key (required):** read-only market data, scans and learning.
- **Signing key (only for LIVE trading):** leave it blank to paper trade.

> **Want real trading?** You need a **GMGN account with a wallet already set up and funded** before you create your API key. The key is tied to that wallet, and every LIVE buy and sell goes through it. Without a GMGN wallet you can still use everything else: scans, Base Hunter, learning, alerts and paper trading.

To add or change keys later, run `python -m kraken setup` from the kraken folder (`.\.venv\Scripts\python.exe -m kraken setup` on Windows), then restart kraken. Use `python -m kraken doctor` to check your install. If you're on GMGN Plus, set **Settings → GMGN rate limits** to 0.15 s and 4 parallel calls.

> Without a key, kraken falls back to a simulated market so the dashboard can still load. A yellow banner tells you when this happens. It's for troubleshooting, not trading.

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

> **Is the download safe?** Every release ZIP is scanned on VirusTotal automatically. The **VirusTotal** button at the top opens the report for the latest download, and each [release](https://github.com/B3an-boi/Kraken/releases/latest) lists the file's **SHA-256** fingerprint. kraken is plain, readable Python and JavaScript with no .exe files, so you can also read every line yourself.


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
│   ├── gmgn.py        gmgn-cli client, rate gate, simulated fallback
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
| `KRAKEN_DEMO` | off | `1` forces the simulated market even when a key is set (for testing the UI) |
| `KRAKEN_DATA` | `./data` | Where settings, snapshots and positions are stored |
| `KRAKEN_NO_BROWSER` | off | Any value stops kraken from opening a browser tab |

## Disclaimer

kraken is a research and screening tool, **not financial advice**. Memecoins are extremely risky, and most go to zero. Past win rates don't predict future results. If you enable LIVE trading you are responsible for every trade. Use at your own risk.

kraken is an independent project and is not affiliated with or endorsed by GMGN. It talks to GMGN only through the public `gmgn-cli` tool, under your own API key.

## License

[MIT](LICENSE)
