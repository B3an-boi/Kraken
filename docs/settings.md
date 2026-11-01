# Settings reference

Every setting is editable on the **Settings** tab and saved to `data/settings.json`. Values shown as % in the UI are stored as fractions (18% → `0.18`). **Reset** on each card restores that section's defaults.

## Base Hunter

| Setting | Default | What it does |
|---|---|---|
| Setup | Post-pump floor | `floor` = pump → flush → flat at the lows on 5m candles. `any` = any tight range on 1m candles. |
| Auto-scan / every | on / 10 min | Background scans that feed the learning loop. |
| Charts per scan | 30 | Tokens charted per scan. Each costs one API call. |
| Min base length | 45 min | How long the flat range must hold. |
| Max base range | 18% | (top − low) / mid of the base. Lower = flatter, fewer finds. |
| Min launch pump × | 2.5 | Peak ÷ lowest low before the peak. Usually the biggest filter; try 2.0 if you see many `no launch pump` rejections. |
| Min retrace | 60% | How far below the peak the base must sit. |
| Base vol ≤ % of pump | 25% | Base volume must have dried up versus the pump. |
| Base ≤ % above the low | 15% | The base must sit at the lows, not halfway up. |
| MC ≤ % of ATH | 40% | Prefilter: skip coins still near their highs. |
| Min $/min in base | 15 (floor) / 100 (any) | Below this the coin counts as dead. |
| Min / max market cap | $20K / $1M | 0 = no maximum. |
| Max age / min age | any / 20 min | Max age in hours, 0 = any. |
| Min liquidity | $10K | |
| Max 1h / 5m move | 25% / 6% | Skip coins already moving. |
| Win = up / before down / within | 30% / 15% / 120 min | The learning label. Changing it only affects new labels. |

**Choosing a max range:** 8–12% gives few, very clean floors with a tight stop. 15–20% collects more data while the model learns. Above 20% lets choppy bleeds through. Once you have 40+ labeled outcomes, use **Learning → What-if backtest** to pick from your own results.

## Screener

| Setting | Default |
|---|---|
| Trending window / tokens per run | 1h / 100 |
| Auto-screen / every | off / 10 min |
| Min score to pass | 40 |
| Min smart money + KOL | 1 |
| Min liquidity / min MC / max MC | $10K / $20K / $5M |
| Max top-10 / dev / bundled / rug | 35% / 10% / 30% / 30% |
| Max buy / sell tax | 10% / 10% |
| Require renounced mint | on |

The safety gates apply to Base Hunter too.

## Trading & risk

| Setting | Default |
|---|---|
| Buy size (native coin) | 0.05 |
| Slippage | 15% |
| Max open positions / total exposure | 10 / 1.0 |
| Daily loss limit | 0.5 |
| Stop-loss / take-profit signals | 25% / 100% |
| Check positions every | 30 s |
| Safety-drop signal | on |

## GMGN rate limits

| Tier | Seconds between calls | Parallel calls |
|---|---|---|
| Free (default) | 1.2 | 1 |
| Plus | 0.15 | 4 |
