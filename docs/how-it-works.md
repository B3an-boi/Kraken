# How kraken works

## Chains

kraken works on **Solana, BSC, Base and Ethereum**. Pick one with the chain picker in the top bar; every screen then reads that chain. Positions and limit orders remember the chain they were opened on, so they keep being priced and sold on the right chain after you switch. Paste an address from another chain into the search box and kraken detects it and switches for you (0x addresses are checked on BSC, Base and Ethereum).

## CA research and the safety score

The safety score is a Python implementation of GMGN's `gmgn-contract-dd` model. It reads `token info`, `token security` and 15-minute candles, and scores three sections from 100:

- **Contract:** mint/freeze authority (Solana), honeypot, verified source, ownership, blacklist (EVM), taxes, LP lock or burn, liquidity, pool shrinkage, how many tokens the creator launched, duplicated logo, and how much price history exists.
- **Holders:** top-10 concentration, holder count, and GMGN's chain analysis (creator holdings, bundlers, snipers, rat traders, entrapment traders, bots, fresh wallets, private vaults).
- **Price:** drawdown from the window high, the worst single candle, halving in 24h, and a volume collapse.

Each field only counts its worst matching tier. Sections are combined 45/35/20 over whatever returned data, GMGN's own rug label caps the score (59 at 50%+, 79 at 30%+), and a honeypot forces 0. The bands are **buyable** (80+), **buyable with conditions** (60+), **not advised** (40+) and **do not buy**. The score is about whether you can buy and sell safely, not whether the price will go up.

Discover's "quick safety" uses the same thresholds on the fields already in each listing row, so the feed costs no extra API calls; open a token for the full score.

## Wallet connection graph

For a wallet, kraken reads who first funded it (exchanges are named, e.g. "Kraken"), its incoming and outgoing transfers (grouped per counterparty, with amounts and dates), the tokens it created and the tokens it buys most. The ten busiest counterparties are looked up to label them (smart money, KOL, dev, sniper, transfer-only wallet) and to spot wallets that share the same funder. Click **Expand connections** on any node to map that wallet too.


## Data source

kraken talks to GMGN only through the public **gmgn-cli** command-line tool, using your own API key. Every call goes through a single rate gate that spaces calls (default 1.2 s apart for the free tier), limits how many run at once, and stops sending after a 429 until the ban expires. Sending during a ban only extends it.

If no key is configured, kraken falls back to a **simulated market** (about 110 synthetic tokens that pump, flush, base and break out or bleed) so the dashboard still loads for troubleshooting. Don't use it for trading decisions. Snapshots from it go into the same learning files, so connect your key before leaving auto-scan running.

## Screener

1. **Trending pull:** up to 100 tokens from `market trending` for the chosen window.
2. **Safety gates:** honeypot, mint authority not renounced, buy/sell tax, rug ratio, bundled supply, dev holdings, top-10 concentration.
3. **Market and consensus gate:** liquidity, market-cap range, minimum smart-money + KOL count.
4. **Score (0-100):** 1h and 5m momentum, buy pressure, smart money/KOL, liquidity depth, holder count, distribution and bundling. A token down more than 25% in the last hour gets its score halved. The top three contributors are shown as reasons.

## Base Hunter

### Post-pump floor (default)

Looks at the token's whole life on 5-minute candles and requires, in order:

| Check | Default | Rejection shown |
|---|---|---|
| Launch pump: peak ÷ lowest low before the peak | ≥ 2.5× | `no launch pump` |
| A trailing flat range after the peak, (top − low) / mid | ≤ 18%, ≥ 45 min | `no long flat range yet` |
| Base mid below the peak | ≥ 60% | `hasn't retraced enough` |
| Base low near the lowest low after the peak | within 15% | `base is above the lows` |
| Base volume vs pump volume | ≤ 25% | `volume hasn't dried up` |
| Not already breaking out | last close ≤ top + 3% | `already breaking out` |
| Still trading | ≥ $15/min in the base | `dead (no trading)` |

### Any tight range

Uses the last 2 hours of 1-minute candles and finds the longest trailing window within the max range. Useful for intraday coils that don't follow the pump-and-flush pattern.

### Prefilters (before any chart is pulled)

Same safety gates as the screener, plus: 1h and 5m moves small enough to look flat, minimum age and liquidity, market-cap range, max age, and (floor setup) market cap at most 40% of its all-time high. Survivors are ranked by live smart-money and KOL flow, and only the top N (`Charts per scan`, default 30) are charted, since each chart costs one API call.

### Score

Until the model is ready, the score is a hand-set rule: longer and tighter bases, deeper volume dry-up, a real launch pump, a deep but not dead flush, smart money net-buying inside the base, first volume waking up, minus penalties for concentration and snipers still holding.

## Smart-money flow

Every minute kraken polls GMGN's smart-money and KOL trade feeds and keeps 3 hours of trades per token. Each card shows the net dollars smart money put in **since the base started**, which is one of the strongest features.

## Learning loop

1. **Snapshot:** each base found is saved with 32 numeric features (at most once per token per 30 minutes).
2. **Label:** after the horizon, kraken pulls the 1-minute candles that followed and marks a **win** if price touched +TP before −SL (defaults +30% / −15% within 120 min). If both are touched in the same candle it counts as a loss, to stay conservative.
3. **Train:** with ≥ 40 labeled outcomes (and ≥ 5 wins and ≥ 5 losses) an L2 logistic regression trains on standardized features. The newest 25% is held out to measure AUC against the rule score.
4. **Blend:** the model's weight grows with data (up to 70% at 300 outcomes). If it doesn't beat the rule score on the holdout, it's capped at 20%.

Your data lives in `data/base_samples.jsonl`, `data/base_labels.jsonl` and `data/base_model.json`. Back these up if you move machines.

## Positions and risk

- **SHADOW:** paper positions at the live price. Nothing is sent on-chain.
- **LIVE:** buys swap native → token via `gmgn-cli swap`, wait for confirmation, and only record the position if it filled. Sells swap 100% back.
- **Limits:** buy size, max open positions, max total exposure, and a daily loss limit that pauses buying for 24 hours.
- **Exit monitor:** checks prices every 30 s and raises one-time signals for stop-loss, take-profit, a new honeypot flag, or top-10 holders jumping 15+ points since entry.
