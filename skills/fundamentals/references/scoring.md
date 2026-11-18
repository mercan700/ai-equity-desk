# Fundamentals grading

The thresholds below suit a typical non-financial company. Industries differ: a 6% operating margin is weak for software and normal for a supermarket chain, so read each grade against the industry before repeating it.

| Pillar | Metric | Strong | OK | Weak |
|---|---|---|---|---|
| Growth | Revenue CAGR between the oldest and newest annual figures (usually 3 or 4 years) | 10% or more | 3% or more | below 3% |
| Profitability | Operating margin, latest year | 20% or more | 8% or more | below 8% |
| Profitability, banks and insurers | ROE | 15% or more | 8% or more | below 8% |
| Cash conversion | Free cash flow / net income | 0.9 or more | 0.6 or more | below 0.6 |
| Balance sheet | Net debt / EBITDA | 1x or less, or net cash | 3x or less | above 3x |
| Valuation | | not graded | | |

## Definitions

- Revenue CAGR: compound annual growth from the oldest to the newest year with a revenue figure. The number of years comes from the fiscal year-end dates.
- Operating margin change: newest minus oldest operating margin, in percentage points. Positive means margins widened.
- FCF / net income: above 1 means reported profit is backed by cash. A ratio that stays below 0.6 points to heavy capex or cash tied up in working capital.
- Net debt: total debt minus cash and equivalents; negative means net cash. When Yahoo leaves total debt blank, long-term plus current debt is used.
- EBITDA: reported EBITDA, else Yahoo's normalized EBITDA, else operating income plus depreciation.
- Share count change: change in diluted average shares over the period. Positive is dilution, negative means buybacks.
- FCF yield: latest annual free cash flow divided by today's market cap.
- Peer gaps: multiples as a percentage above (+) or below (-) the peer median; margins, ROE, growth and FCF yield as the difference in percentage points.

## Caveats the script adds

| Condition | Why it matters |
|---|---|
| Lease-heavy industry (airlines, retail, restaurants, hotels) | Under IFRS 16 lease payments are financing cash flows, so free cash flow and EBITDA look higher than the cash the business keeps. |
| Conglomerate | Consolidated statements can include a bank or insurer, which distorts cash flow, debt and margins. |
| Statements in TRY, ARS, EGP or NGN | High inflation makes nominal growth look strong. Compare with inflation or with USD figures. |
| FCF yield above 20% or below -20% | Usually a one-off working-capital swing rather than a lasting level. |

## Limits of the free data

- yfinance usually returns four annual years, sometimes fewer.
- Market cap and P/E are current, while the statements are from the last fiscal year, so the two can be up to a year apart.
- yfinance reports `dividend_yield` already in percent.
- Statement amounts are in the reporting currency. Do not compare absolute amounts between companies that report in different currencies.
