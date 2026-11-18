---
name: screener
description: Finds US stocks that match a set of rules, using free data. Scans the S&P 500, the S&P 400 mid caps, the S&P 600 small caps or every US listing above a size floor, on price action (returns, momentum, distance from the high, moving averages, RSI, volume) and on fundamentals from SEC filings (P/E, free cash flow yield, growth, margins, return on equity, debt, dividends). Has ready presets for value, quality, growth, GARP, dividend, momentum, breakout, pullback and oversold. Use for "find me cheap quality stocks", "screen for X", "which stocks are breaking out", "high dividend stocks that are safe", "momentum stocks", "small caps with growth" or "stocks like X but cheaper". US only.
---

# Screener

## Steps

1. Pick a preset, filters, or both. Run from this skill's folder:

   ```
   python scripts/screener.py run --preset quality
   python scripts/screener.py run --universe sp600 --preset value --top 15
   python scripts/screener.py run --where "pe<20" --where "revenue_growth>=15" --where "debt_to_equity<=0.5" --sort fcf_yield
   python scripts/screener.py run --universe us --min-cap 10 --preset breakout --sector technology
   python scripts/screener.py run --tickers AAPL MSFT GOOGL META --sort pe --asc
   ```

   `presets` lists the presets with their filters and `fields` lists every field. A preset and `--where` filters can be combined; the filters are added to the preset's.
2. The first run of the day downloads a year of prices for the whole universe and takes 30 to 90 seconds (`us` takes longest). Later runs read the cache.
3. Write the brief below.

## Choosing the universe

- `sp500` (default): large US companies.
- `sp400` and `sp600`: mid and small caps. Fewer analysts follow them, which is why screens often find more there.
- `us`: every US listing above $2 billion, or above `--min-cap`. This includes foreign companies listed in the US. Most of them have no SEC annual figures and drop out of fundamental filters.

Translate the user's words into filters and say which ones you used. "Cheap" usually means a P/E or free cash flow yield, and "safe dividend" means the payout is covered by free cash flow. "Growing" means revenue growth, and "near highs" means `from_high>=-5`.

## Brief

```
## Screen: <preset or description>, <universe>
<matches> of <scanned> stocks pass: <filters in plain words>. Prices to <prices_to>; fundamentals from <fundamentals_year> annual reports.

| Stock | Sector | Mkt cap $bn | <the 4 to 6 columns that matter for this screen> |
|---|---|---|---|

What the list has in common: one or two lines (a sector cluster, mostly small caps, all recent losers).
What to check before reading more into it: one line per stock that stands out for a reason the numbers can't show,
e.g. a one-off gain inflating the P/E, a stock that fell 40% in a month, or a bank in a margin screen.
```

Then offer the next step for any stock the user picks: the fundamentals, technicals or scenarios skill.

## Rules

- A screen is a list of candidates, not a buy list. Never call a result a pick or a recommendation.
- Fundamentals are the last full calendar year from SEC filings, and market caps are today's. A company whose results changed sharply this year shows stale ratios. Say so when the user asks about one.
- Stocks without SEC figures do not pass fundamental filters. They are not excluded from price-only screens.
- P/E is blank for loss makers and ROE is blank when equity is negative, which large buyback programs can cause. A blank field fails any filter on it.
- `oversold` alone returns stocks that are falling for a reason as often as bargains. Pair it with a trend or quality filter unless the user wants exactly that.
- If a screen returns nothing, loosen the strictest filter one step and say which one you loosened.
