---
name: portfolio
description: Keeps the user's portfolio with a reason attached to every position. Records buys and sells, the thesis and the condition that would prove it wrong, and dated notes. Shows weights, gains and performance against the index. Replays five real crashes (2000, 2008, 2018, 2020, 2022) on today's weights. Reviews the user's own trading for habits such as selling winners too early and holding losers, averaging down, concentration, and theses never revisited. Use for "add 10 AAPL at 180", "I sold my Tesla", "show my portfolio", "how would my portfolio do in a crash", "stress test my holdings", "review my trades", "am I too concentrated" or "why do I own X". Built for US stocks; Borsa Istanbul works with --market BIST.
---

# Portfolio

The portfolio is stored in `portfolio.json` in the data folder on the user's computer. Only ticker symbols go out, to fetch prices. Prices are per share, in the stock's trading currency. Totals are in US dollars.

## Commands

Run from this skill's folder:

```
python scripts/portfolio.py add AAPL 10 182.50 --date 2024-03-01 --thesis "services keep growing" --sell-if "services growth under 5%"
python scripts/portfolio.py add THYAO 200 280 --market BIST
python scripts/portfolio.py sell AAPL 5 240 --date 2025-06-02 --reason "position too large"
python scripts/portfolio.py note AAPL "Q3 services +14%, thesis intact"
python scripts/portfolio.py note AAPL --sell-if "services growth under 8% two quarters in a row"
python scripts/portfolio.py show
python scripts/portfolio.py stress
python scripts/portfolio.py review
```

## Recording trades

- Record a trade only when the user states it, with the number of shares, the price and the date. If any of the three is missing, ask; do not guess. Without `--date` the trade is recorded for today.
- When adding a new position, ask the user for two sentences if they did not give them: why they own it (`--thesis`) and what would make them sell (`--sell-if`). The sell condition should be something that can be checked, like a number or an event. "If it goes down" does not qualify. The review works much better with both.
- When selling, ask for the reason and pass it with `--reason`.
- If the output has a `warning` about the price, the price is far from that day's close. Read it back to the user before moving on, because it is usually a typo or a date mix-up.
- A note with `--thesis` or `--sell-if` replaces the old text and keeps the old version in the notes. Use it when the user changes their mind, and use a plain note when they check in and the thesis still holds. Either one counts as a review.

## show

```
## Portfolio, <date>: $<value_usd>
| Stock | Weight | Gain | Since first buy (with dividends) | Index, same period |
|---|---|---|---|---|
Concentration: largest position, top three, sectors.
```

For a BIST holding, show the gain in lira and the gain in dollars (`gain_in_usd_pct`) side by side. They often point in opposite directions.

## stress

```
## If it happened again: <n> past crashes on today's weights
| Crash | Portfolio | S&P 500 | Hardest hit |
|---|---|---|---|
Index down 20%: portfolio <x>%.
Last five years with today's weights: worst month <x>% (<month>), volatility <y>% a year.
Holdings that move together: <most_alike pairs>.
```

Then one paragraph on what drives the result: one large position, one sector, or high-beta stocks. Moves under `estimated_from_beta` are for stocks that were not listed at the time. Mention that a young growth stock usually falls further than its beta suggests.

## review

Start with the flags. Group them by stock, and for each say what to do next, in the user's terms. For example: "PLTR is 32% of the portfolio and has no sell condition. Decide what would make you sell before the next earnings report." Then cover:

- Trading record: win rate, average win and loss, how long winners and losers were held, and how often a sale beat the index over the same period.
- Disposition: `share_of_gains_sold` against `share_of_losses_sold`. If gains are sold far more readily, the user is cutting winners and riding losers. This is the most common habit found in studies of individual investors. Under 5 sales, `reads` says "too few sales to tell". Report it that way.
- Concentration by sector and country.
- If `scenario_scorecard` is present, add a line on whether their saved scenarios lean optimistic.

## Rules

- Never tell the user to buy or sell a stock. Describe the risk, the habit or the gap in the thesis. The decision stays with them.
- Do not moralise about a bias. Name it once, show the numbers and suggest one concrete check.
- With fewer than 10 closed trades, say the patterns are early and do not draw conclusions about the person.
- Gains here are price gains against the average cost. "Since first buy" includes dividends and runs from the first purchase date. Say which one you quote.
- The crash replays use today's weights, so a stock that was small or unowned at the time counts at today's size. Say this when the user reads them as past performance.
