---
name: market
description: Reads the state of the US stock market and what is on the calendar. Checks the S&P 500 and Nasdaq trend, distribution days, breadth (how many stocks are above their 200-day average, new highs against new lows), VIX and its term structure, high-yield credit spreads, the yield curve and which sectors are leading. Counts seven fixed rules into a risk-on, mixed or risk-off reading. The calendar lists US economic releases with consensus figures, Fed decision days, large company earnings and the earnings dates of the user's own holdings. Use for "how is the market", "is this a good time to be aggressive", "market breadth", "is the market healthy", "what's on the calendar this week", "when is the next Fed meeting", "when does X report" or "what could move the market". US market.
---

# Market

## Steps

1. Run from this skill's folder:

   ```
   python scripts/market.py regime
   python scripts/market.py calendar
   python scripts/market.py calendar --days 14 --tickers NVDA AMD
   ```

   The calendar adds earnings dates for US stocks in the portfolio skill's journal automatically.
2. The first `regime` run of the day downloads prices for the whole S&P 500 for the breadth figures and takes about half a minute.
3. Write the brief for what was asked. When the user asks a general "how is the market" question, run both.

## Regime brief

```
## US market, <as_of>: <posture> (<risk_on> of 7 rules risk-on, <risk_off> risk-off)

| Rule | Reading | Signal |
|---|---|---|
| Trend | S&P 500 <vs_sma200_pct>% vs its 200-day, average rising/falling | |
| Distribution days | <n> on SPY, <n> on QQQ in 25 sessions | |
| Breadth | <pct_above_200d>% of S&P 500 above 200-day (<month ago>% a month ago) | |
| Highs/lows | <new highs> new highs, <new lows> new lows | |
| Volatility | VIX <x> (<percentile> percentile of the year), VIX/VIX3M <ratio> | |
| Credit | high-yield spread <x>%, <change> in a month | |
| Sectors | leaders and laggards over 3 months; defensive minus cyclical <x> points | |

What stands out: two or three lines on the readings that disagree or changed most, for example "the index is
at its 200-day average but most distribution days came in the last week".
```

## Calendar brief

List by day: the Fed first, then releases that usually move stocks (CPI, payrolls, PCE, GDP, retail sales, ISM), then the user's own stocks reporting, then large companies. Give consensus and previous figures where there are any. Leave out speeches and minor releases unless the user asks.

## Rules

- The posture counts rules. It does not predict. Never say the market will rise or fall, and never turn the posture into an instruction to buy or sell.
- Distribution days and breadth are trend-following tools. They lag at turning points and give false alarms in choppy markets. Say so when a reading has just flipped.
- A risk-off posture is a reason to check position sizes and stop levels in the portfolio skill. It is not a reason to sell everything. Offer that check instead of advice.
- When a source fails, its rule shows "missing". Report it and work with the others.
- Times in the calendar are US Eastern. Convert them when the user is in another time zone and you know which.
