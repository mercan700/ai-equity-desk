---
name: desk-data
description: Fetches free market data and returns short JSON summaries. Covers price and returns, returns after inflation and in US dollars, long-run history, company profile and multiples, financial statements with margins and growth, a cross-check of those statements against SEC filings, SEC filing lists, US macro data (Turkish macro for BIST), and a snapshot of world markets. Use whenever a question about a stock or the economy needs real numbers ("how is AAPL doing", "NVDA margins", "latest 10-K", "where are rates"). The other desk skills use it as their data source. Built for US stocks; Borsa Istanbul works with --market BIST.
---

# Desk data

`scripts/desk.py` wraps every data source behind one command line and prints a single line of JSON. Read the JSON and answer in plain language.

## Commands

| Question | Command |
|---|---|
| Last price, returns from 1 day to 1 year, 52-week range, recent volatility | `python scripts/desk.py quote AAPL` |
| Return over 1, 3 and 5 years in local currency, in US dollars and after inflation | `python scripts/desk.py returns AAPL` |
| Long-run CAGR, volatility and largest drawdown; also saves the prices as CSV | `python scripts/desk.py history AAPL --period 10y` |
| Business description, sector, size, P/E, P/B, EV/EBITDA, dividend yield | `python scripts/desk.py profile AAPL` |
| Revenue, profit, cash flow and debt, with margins, growth and ROE | `python scripts/desk.py financials AAPL` (add `--quarterly` for quarters) |
| Check Yahoo's statement figures against the company's SEC 10-K filings | `python scripts/desk.py verify AAPL` |
| Recent SEC filings with links, US companies only | `python scripts/desk.py filings AAPL --forms 10-K 8-K --limit 5` |
| Fed funds rate, 10-year yield, yield curve, CPI, unemployment, credit spreads | `python scripts/desk.py macro` |
| Any other FRED series by its code | `python scripts/desk.py macro DGS10 CPIAUCSL` |
| Turkish policy rate, inflation, real policy rate, USD/TRY, EUR/TRY, BIST 100 | `python scripts/desk.py macro --market BIST` |
| S&P 500, Nasdaq, VIX, dollar index, Brent, gold, EUR/USD, Bitcoin | `python scripts/desk.py global` |

For Borsa Istanbul add `--market BIST`, for example `quote THYAO --market BIST`. BIST supports quote, returns, history, profile, financials and macro. SEC filings and verification are US only; KAP is not supported yet.

## Rules

- Run the commands the question needs and no more. "How is X doing" needs one `quote`.
- Do not open the cached CSV files. They are there for other scripts; the JSON already holds the summary.
- Give the source and date with every number, for example "yfinance close, 2026-11-17" or "FRED DGS10, 2026-11-14". Free data can lag or contain errors, so point out a number that looks wrong.
- For BIST stocks, quote the inflation-adjusted and dollar returns next to the lira return whenever returns come up. A lira return on its own mostly measures inflation.
- `returns` measures inflation over the same number of months, ending at the latest published CPI month (`inflation_lag_months` says how far that is behind the price date).
- `verify` reports `matched` as items within 2% of the SEC figure and a `confidence` of high (90% or more), medium (70% or more) or low. Mention any item in `differences`; for banks a revenue gap of a few percent is normal because revenue definitions differ.
- Statement amounts are in millions of the currency the company reports in. EPS is per share. Percentages are already multiplied by 100.
- Errors come back as `{"error": "..."}`. A missing package or SEC user-agent means the desk-setup skill should run. An unknown ticker means the user should confirm the symbol and market.
- Report and explain the data. Do not tell the user to buy, sell or hold, and do not give a price target.

## Sources

| Source | Data | Notes |
|---|---|---|
| yfinance (Yahoo Finance) | prices, profiles, statements | free and unofficial; Yahoo may rate-limit heavy use |
| SEC EDGAR | filing lists | free; SEC requires a contact User-Agent and allows 10 requests a second, which the script respects |
| SEC XBRL company facts | figures from 10-K filings, for `verify` | free; same User-Agent rule |
| FRED | US macro series | free public CSV, no key |
| BIS (Bank for International Settlements) | consumer prices and policy rates by country | free, no key |

Results are cached in `~/.ai-equity-desk/cache`: prices for 15 minutes, statements and profiles for 7 days. A repeated question reads the cache and makes no network call.
