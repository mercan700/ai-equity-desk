# Reading the technicals output

| Field | What it is | How to read it |
|---|---|---|
| `trend.label` | Price vs 50-day and 200-day simple moving averages | Uptrend: price > 50d > 200d. Downtrend: the reverse. Anything else: mixed / range. |
| `vs_smaXX_pct` | % distance of price from each average | Far above the 50d (e.g. +15%) = extended; near it = testing. |
| `sma200_slope_1m_pct` | Change of the 200d average over the last month | Positive = long-term trend rising. |
| `last_50_200_cross` | Last time the 50d crossed the 200d | Bullish = "golden cross", bearish = "death cross". Lagging; `bars_ago` says how stale. |
| `rsi14` | Relative Strength Index, 14 days (Wilder) | > 70 stretched up, < 30 stretched down, 40-60 neutral. Compare with `rsi14_5d_ago` for direction. |
| `macd_hist` | MACD (12, 26) minus its 9-day signal | Positive = short-term momentum above trend. `macd_last_cross` dates the last flip. |
| `atr14_pct` | Average true range as % of price | Typical daily move. 1-2% calm large cap; 3%+ volatile. |
| `bollinger_pct_b` | Position inside 20-day Bollinger bands (2 std) | 1 = at upper band, 0 = at lower band, > 1 or < 0 = outside. |
| `annual_vol_1y_pct` | Annualized volatility of daily returns, last year | Compare with the benchmark's. |
| `max_drawdown_1y_pct` | Worst peak-to-trough fall in the last year | Shows how deep a pullback holders already sat through. |
| `support` / `resistance` | Swing lows/highs of the last ~6 months, merged within 1.5%, nearest 3 | Areas where price turned before. Not guaranteed to hold. |
| `avg20_vs_avg60_pct` | Recent vs longer-run average volume | Rising volume confirms the move; fading volume weakens it. |
| `relative_strength_vs_benchmark_pp` | Stock return minus benchmark return, percentage points | Positive = outperforming the market (S&P 500 or BIST 100). |

Prices are split- and dividend-adjusted (yfinance `auto_adjust`), so levels can differ slightly from a broker chart.
