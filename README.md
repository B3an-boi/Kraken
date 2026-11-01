<div align="center">

# 🐙 kraken

**Self-hosted memecoin screener, Base Hunter and learning loop, built on [gmgn-cli](https://www.npmjs.com/package/gmgn-cli).**

Find coins resting in a quiet floor after their first pump, before the breakout. Snapshot every find, grade what happened next, and let a small model learn which setups actually work, from *your* data.

Runs on your own computer · uses your own GMGN API key · keys never leave your machine · paper trading by default

[![Download](https://img.shields.io/github/v/release/B3an-boi/Kraken?label=Download&style=for-the-badge&color=3ef0c6)](https://github.com/B3an-boi/Kraken/releases/latest)
[![VirusTotal](https://img.shields.io/badge/VirusTotal-v0.1.1%20report-394EFF?style=for-the-badge&logo=virustotal&logoColor=white)](https://www.virustotal.com/gui/file/5bda58fce46c68448b4b84fd60f5aa77d392300d541053f6d8fffbeaff3ef858)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

</div>

---

## What you need

- A **Windows, Mac or Linux** computer
- A free **GMGN account** at [gmgn.ai](https://gmgn.ai). kraken uses your own GMGN API key, and the setup page walks you through creating it.
- For **real trading only:** a wallet in your GMGN account that's set up and funded. Without one you can still use everything else, including paper trading.

That's it. The installer sets up everything else (Python, Node.js and gmgn-cli) for you.

> 💡 **Get Plus without paying cash:** as of November 2026, GMGN lets you redeem **5,000 GMGN credits for 1 month of the Plus API plan**. You earn credits by trading on GMGN. Terms can change, so check the [GMGN paid plans page](https://gmgn.ai/ai?chain=bsc&tab=paid_plans) for the current offer. With Plus, set **Settings → GMGN rate limits** to 0.15 s and 4 parallel calls for much faster scans.

## Install on Windows (step by step)

**1. Download.** Click the **Download** button at the top of this page, then click **`kraken-vX.X.X.zip`** under *Assets* to save it.

**2. Check it's safe (optional, recommended).** Go to **[virustotal.com](https://www.virustotal.com)**, choose **File**, and drop in the ZIP. It should say **"No security vendors flagged this file as malicious"**. Or click the **VirusTotal** button at the top of this page to see the report for the official file.

**3. Unzip.** Right-click the ZIP → **Extract All…** → **Extract**. A good place is your *Documents* folder.

**4. Install.** Open the extracted **kraken** folder and double-click **`install.cmd`**.
- If Windows shows **"Windows protected your PC"**, click **More info → Run anyway**. This appears for any script downloaded from the internet that isn't from a paid, signed publisher.
- If Python or Node.js are missing, the installer adds them. Click **Yes** if Windows asks for permission.
- If it says Windows "needs a fresh window", close it and double-click **`install.cmd`** again. That happens once, right after Python or Node.js is installed.

**5. Connect GMGN.** When the install finishes, kraken opens in your browser with a short setup page:
1. Log in to **gmgn.ai** in your browser.
2. Click **Open GMGN**. GMGN's "create API key" page opens with everything pre-filled. Create the key and **copy** it.
3. Back in kraken, **paste** the key and click **Connect**.

**6. Done!** From now on, start kraken by double-clicking the **kraken** icon on your desktop. A small black window opens alongside the browser; keep it open while you use kraken, and close it to stop kraken.

## Install on Mac or Linux

1. Download and unzip the release as in steps 1–3 above.
2. Install Python 3.10+ and Node.js 18+ if you don't have them. Mac: install [Homebrew](https://brew.sh), then run `brew install python node`. Ubuntu: `sudo apt install python3 python3-venv nodejs npm`.
3. Open a terminal in the kraken folder (Mac: right-click the folder → **New Terminal at Folder**) and run:
   ```bash
   bash install.sh
   ```
4. Your browser opens to the same setup page. Next time, start kraken with `./run.sh` in that folder.

<details>
<summary><b>Advanced: install with git</b></summary>

```bash
git clone https://github.com/B3an-boi/Kraken.git
cd Kraken
./install.sh            # Windows: .\install.cmd
```
</details>

## Your keys

- Setup creates a key pair **on your computer**, and GMGN links your API key to it. Both are saved in `~/.config/gmgn/.env` (`C:\Users\<you>\.config\gmgn\.env` on Windows). They never go into the kraken folder, GitHub, or anywhere else.
- **Reconnect or change keys:** Settings → **Reconnect GMGN**.
- **Real trading** also needs a funded wallet in your GMGN account. kraken stays on **SHADOW** (paper trading) until you switch to LIVE and confirm.
- **On GMGN Plus?** Set **Settings → GMGN rate limits** to 0.15 s and 4 parallel calls.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Windows protected your PC" | Click **More info → Run anyway**. |
| Installer says it needs a fresh window | Close it and double-click `install.cmd` again. |
| The page says "backend offline" | The black kraken window was closed. Double-click the kraken desktop icon. |
| GMGN rejected the key | Create the key from the page the **Open GMGN** button opens (it pre-fills your public key), copy the whole key, and paste again. |
| Key works on GMGN but kraken gets 401/403 errors | gmgn-cli only works over IPv4. Turn off IPv6 on your network adapter, then retry. |
| "No GMGN key found" banner | Settings → **Connect GMGN**. |
| Checking your install | In the kraken folder run `.venv\Scripts\python.exe -m kraken doctor` (Windows) or `.venv/bin/python -m kraken doctor`. |

**Updating:** download the new release and unzip it to a new folder, then copy your old **`data`** folder into it to keep your settings, snapshots and positions. Run `install.cmd` in the new folder.

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
│   ├── setup_flow.py  first-run GMGN connection (wraps gmgn-cli config)
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
