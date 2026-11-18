---
name: desk-data
description: Fetches free market data and returns short JSON summaries. Covers price and returns, long-run history, company profile and multiples, financial statements with margins and growth, SEC filing lists, US macro series from FRED, and a snapshot of world markets. Use whenever a question about a stock or the economy needs real numbers ("how is AAPL doing", "NVDA margins", "latest 10-K", "where are rates"). The other desk skills use it as their data source. Covers US stocks and Borsa Istanbul (--market BIST).
---

# Desk data

`scripts/desk.py` wraps every data source behind one command line and prints a single line of JSON. Read the JSON and answer in plain language.

## Commands

| Question | Command |
|---|---|
| Last price, returns from 1 day to 1 year, 52-week range, recent volatility | `python scripts/desk.py quote AAPL` |
| Long-run CAGR, volatility and largest drawdown; also saves the prices as CSV | `python scripts/desk.py history AAPL --period 10y` |
| Business description, sector, size, P/E, P/B, EV/EBITDA, dividend yield | `python scripts/desk.py profile AAPL` |
| Revenue, profit, cash flow and debt, with margins, growth and ROE | `python scripts/desk.py financials AAPL` (add `--quarterly` for quarters) |
| Recent SEC filings with links, US companies only | `python scripts/desk.py filings AAPL --forms 10-K 8-K --limit 5` |
| Fed funds rate, 10-year yield, yield curve, CPI, unemployment, credit spreads | `python scripts/desk.py macro` |
| Any other FRED series by its code | `python scripts/desk.py macro DGS10 CPIAUCSL` |
| S&P 500, Nasdaq, VIX, dollar index, Brent, gold, EUR/USD, Bitcoin | `python scripts/desk.py global` |

For Borsa Istanbul add `--market BIST`, for example `quote THYAO --market BIST`. BIST supports quote, history, profile and financials; filings and macro are US only for now.

## Rules

- Run the commands the question needs and no more. "How is X doing" needs one `quote`.
- Do not open the cached CSV files. They are there for other scripts; the JSON already holds the summary.
- Give the source and date with every number, for example "yfinance close, 2026-11-17" or "FRED DGS10, 2026-11-14". Free data can lag or contain errors, so point out a number that looks wrong.
- Statement amounts are in millions of the currency the company reports in. EPS is per share. Percentages are already multiplied by 100.
- Errors come back as `{"error": "..."}`. A missing package or SEC user-agent means the desk-setup skill should run. An unknown ticker means the user should confirm the symbol and market.
- Report and explain the data. Do not tell the user to buy, sell or hold, and do not give a price target.

## Sources

| Source | Data | Notes |
|---|---|---|
| yfinance (Yahoo Finance) | prices, profiles, statements | free and unofficial; Yahoo may rate-limit heavy use |
| SEC EDGAR | filing lists | free; SEC requires a contact User-Agent and allows 10 requests a second, which the script respects |
| FRED | US macro series | free public CSV, no key |

Results are cached in `~/.ai-equity-desk/cache`: prices for 15 minutes, statements and profiles for 7 days. A repeated question reads the cache and makes no network call.
