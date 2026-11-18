# How the fundamentals signals are graded

Rule-of-thumb thresholds for a typical non-financial company. They are a starting point for discussion, not a verdict: a 6% operating margin is weak for software and normal for a grocer. Adjust the reading to the industry.

| Pillar | Metric | Strong | OK | Weak |
|---|---|---|---|---|
| Growth | Revenue CAGR over available years (usually 3-4) | >= 10% | >= 3% | < 3% |
| Profitability | Operating margin (latest year) | >= 20% | >= 8% | < 8% |
| Profitability (financials) | ROE | >= 15% | >= 8% | < 8% |
| Cash quality | Free cash flow / net income | >= 0.9 | >= 0.6 | < 0.6 |
| Balance sheet | Net debt / EBITDA | <= 1x or net cash | <= 3x | > 3x |
| Valuation | not graded | | | |

## Definitions

- **Revenue CAGR**: compound annual growth from the oldest to the newest annual revenue yfinance returns.
- **Operating margin change (pp)**: newest minus oldest operating margin, in percentage points. Positive = margins expanding.
- **FCF / net income**: above 1 means profits are backed by cash; persistently below 0.6 means earnings may be lower quality (working capital build, heavy capex).
- **Net debt** = total debt - cash and equivalents. Negative = net cash.
- **Share count change**: change in diluted average shares over the period. Positive = dilution, negative = buybacks.
- **FCF yield** = latest annual free cash flow / current market cap.
- **Peer gaps**: valuation multiples as % premium (+) or discount (-) to the peer median; margins, ROE, growth and FCF yield as the plain difference in percentage points.

## Known limits of free data

- yfinance usually gives 4 annual years; some companies return fewer.
- Market cap and multiples are current; statements are from the last fiscal year, so they can be up to a year apart.
- yfinance reports `dividend_yield` already in percent.
- Currency: BIST statements are in TRY, US in USD. Do not compare absolute amounts across currencies.
