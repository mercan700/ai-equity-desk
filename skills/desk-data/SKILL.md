---
name: desk-data
description: The data layer of the AI equity research desk. Fetches free market data on demand and returns compact summaries - price snapshots and returns, long-run history stats, company profile and valuation multiples, financial statements with margins and growth, SEC filings lists, US macro from FRED, and a world-markets snapshot. Use whenever a stock question needs real numbers ("how is AAPL doing", "NVDA margins", "latest 10-K", "where are rates"), and as the shared data source for every other desk skill. Supports US stocks fully and BIST (Borsa Istanbul) prices with --market BIST.
---

# Desk data

One command-line tool, `scripts/desk.py`, wraps every free source. It prints one line of compact JSON. Read the JSON, then answer in plain language.

## Commands

| Need | Command |
|---|---|
| Price now, returns 1d-1y, 52-week range, volatility | `python scripts/desk.py quote AAPL` |
| Long-run CAGR, volatility, max drawdown (saves a CSV for other scripts) | `python scripts/desk.py history AAPL --period 10y` |
| What the company does, sector, size, P/E, P/B, EV/EBITDA, yield | `python scripts/desk.py profile AAPL` |
| Revenue, profit, cash flow, debt + margins, growth, ROE | `python scripts/desk.py financials AAPL` (add `--quarterly`) |
| Latest SEC filings with links (US only) | `python scripts/desk.py filings AAPL --forms 10-K 8-K --limit 5` |
| US macro: Fed rate, 10Y yield, curve, CPI, jobs, credit spreads | `python scripts/desk.py macro` or `macro DGS10 CPIAUCSL` |
| World markets: S&P, Nasdaq, VIX, dollar, oil, gold, EUR/USD, BTC | `python scripts/desk.py global` |

Borsa Istanbul: add `--market BIST` (`quote THYAO --market BIST`). Only prices, history, profile and financials work for BIST so far.

Any FRED series code works with `macro` (find codes at fred.stlouisfed.org).

## Rules

- **Run only what the question needs.** One `quote` answers "how is X doing". Do not run every command by default.
- **Never print or read the cached CSV files.** They exist for other scripts. Use the summary JSON.
- **Cite the source and date** of every number you report (e.g. "yfinance, close 2026-11-17"; "FRED DGS10, 2026-11-14"). Free data can lag or be wrong; say so when a number looks odd.
- **Units:** financials are in millions of the reporting currency, EPS per share, percentages already multiplied by 100.
- **Errors** come back as `{"error": ...}`. A setup-type error (missing package, missing SEC user-agent) means: use the desk-setup skill. A ticker error means: ask the user to confirm the ticker and market.
- **Not advice.** Report and explain data. Never tell the user to buy, sell or hold, and never give a single price target.

## Data sources

| Source | What | Cost | Notes |
|---|---|---|---|
| yfinance (Yahoo) | prices, profile, statements | free | unofficial; can rate-limit |
| SEC EDGAR | filings list | free | needs contact User-Agent, max 10 req/s (enforced) |
| FRED | US macro | free | public CSV, no key |

Cache lives in `~/.ai-equity-desk/cache` with sensible lifetimes (prices 15 min, statements 7 days), so repeat questions are fast and do not hit the sources again.
