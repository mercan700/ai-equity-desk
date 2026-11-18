---
name: technicals
description: Technical analysis of one stock from daily prices. Reports trend and moving averages, RSI and MACD, volatility, support and resistance from recent swing points, volume, and performance against the S&P 500 (the BIST 100 for Turkish stocks). Use for questions like "what does the chart of X say", "technical analysis of X", "is X overbought", "support and resistance for X", "X trend", "X RSI" or "is X beating the market". Built for US stocks; Borsa Istanbul works with --market BIST.
---

# Technicals

## Steps

1. Run the script from this skill's folder:

   ```
   python scripts/technicals.py AAPL
   ```

   Add `--market BIST` for Borsa Istanbul; the benchmark then switches from the S&P 500 to the BIST 100.
2. The script prints one line of JSON. `references/reading.md` explains each field; open it when you need to explain an indicator.
3. Write the brief below.

## Brief

```
## <symbol>, technicals
Source: yfinance daily closes up to <date>

Trend: <label>. Distance to the 50-day and 200-day averages, and the date of the last 50/200 cross.
Momentum: RSI <x>, up or down from 5 days ago. MACD above or below its signal line since <date>.
Volatility: average daily range (ATR) <x>% of price; largest fall in the past year <y>%.

| Support | Distance | Resistance | Distance |
|---|---|---|---|

Against the market: <+/- x> percentage points versus <benchmark> over 3 months, 6 months and 1 year.
Returns: 1-year and annualized 3- and 5-year returns from `returns`. For BIST show lira, dollar and after-inflation returns side by side.
What would change the picture: 2 or 3 concrete conditions, for example
"a close below the 200-day average at 212 would end the uptrend".

This describes past prices and is not investment advice.
```

## Rules

- Do not use trading instructions: no buy, sell, entry, exit, stop-loss or target. Write "the trend would weaken below 212" where a trader would write "sell below 212".
- Mention once that indicators describe the past and can turn quickly.
- When signals disagree (an uptrend with falling RSI and shrinking volume, say), give the disagreement one sentence.
- An empty `resistance` list means the price is above every swing high of the last six months. Use the 52-week high as the reference and say so. The same applies to `support` and the 52-week low.
- An RSI above 70 or below 30 means the move is stretched. Strong trends often stay stretched for weeks, so do not present it as a reversal signal.
- BIST stocks have daily price limits and are more volatile than US large caps. Compare their ATR and volatility with the BIST 100, not with US stocks.
- Keep fundamentals out of this brief unless the user asks; the fundamentals skill covers them.
