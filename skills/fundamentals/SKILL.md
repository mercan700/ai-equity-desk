---
name: fundamentals
description: Fundamental analysis of one listed company from its financial statements. Grades growth, profitability, cash conversion and balance sheet, describes valuation, and compares the company with peers you choose. Use for questions like "is X a good business", "analyze NVDA's fundamentals", "how profitable is X", "is X expensive", "compare X with its competitors", "X balance sheet" or "X valuation". Covers US stocks and Borsa Istanbul (--market BIST).
---

# Fundamentals

## Steps

1. Choose 3 to 5 peers in the same industry with a similar business model (BIST peers for a BIST company). No free source lists peers, so tell the user which ones you picked.
2. Run the script from this skill's folder:

   ```
   python scripts/fundamentals.py NVDA --peers AMD AVGO QCOM
   ```

   Add `--market BIST` for Borsa Istanbul. Leave out `--peers` to skip the comparison.
3. The script prints one line of JSON. Each pillar has a `signal` of strong, ok or weak, set by the thresholds in `references/scoring.md`. Open that file only when you need to explain a grade.
4. Write the brief below.

An `{"error": ...}` that mentions packages or setup means the desk-setup skill should run first. If a single peer fails, the script lists it under `peer_comparison.failed` and the brief goes on without it.

## Brief

```
## <Name> (<symbol>), fundamentals
Source: yfinance, fiscal year ending <latest_fiscal_year>, <currency> millions

| Pillar | Signal | Numbers |
|---|---|---|
| Growth | | revenue CAGR x% over n years, last year y% |
| Profitability | | operating margin, ROE, margin change over the period |
| Cash conversion | | FCF / net income, capex as % of revenue |
| Balance sheet | | net debt / EBITDA, change in share count |
| Valuation | not graded | P/E, EV/EBITDA, P/B, FCF yield, gap to peer median |

What stands out: 2 to 4 points, each tied to a number in the table.
What would change the picture: 2 or 3 numbers to watch in the next reports.
Caveats: every item from the `caveats` list, in plain words, plus anything else that looks off.

This is a summary of public data, not investment advice.
```

## Rules

- Do not tell the user to buy, sell or hold, and do not give a price target. Describe valuation as a fact about the market price, for example "trades at 35% above the peer median EV/EBITDA".
- Give the reason a number matters in a short clause. Skip textbook definitions unless the user asks.
- Banks and insurers (`financial_company: true`) have no meaningful gross margin, free cash flow or net debt, so the script leaves those out. Discuss ROE, P/B and growth, and say that a full bank analysis needs loan, deposit and capital ratios that this skill does not fetch.
- `currency` is the currency of the financial statements. When `valuation.currency_note` is present, the shares trade in another currency and the script converted the market cap; mention the conversion once.
- `pe_ttm` is taken from yfinance unchanged and is sometimes wrong for non-US stocks (a P/E in the hundreds next to a double-digit FCF yield is a sign). EV/EBITDA, P/B and FCF yield are computed from the statements and are more reliable. When they disagree with the P/E, say the P/E looks unreliable.
- If the net margin moves far from the operating margin in one year, look for a one-off gain or write-down before drawing conclusions.
- Target length: the table plus 6 to 8 short points.
