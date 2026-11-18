# AI Equity Desk

**Your own AI equity research desk for Claude.** A team of specialist skills that analyze stocks on your computer, using only free data. No paid APIs and no data shipped with the pack: your machine fetches everything fresh.

> ⚠️ **Not financial advice.** This is a research and education tool. It never tells you to buy, sell or hold, and it never gives a single price target. Free data can be delayed or wrong. Do your own research.

## Skills

| Skill | Status | What it does |
|---|---|---|
| `desk-setup` | ✅ v0.1 | Checks Python, installs packages, tests every data source |
| `desk-data` | ✅ v0.1 | Shared data layer: prices, history, profile, financials, SEC filings, FRED macro, world markets |
| `fundamentals` | 🔜 | Business quality, margins, growth, balance sheet, peers |
| `technicals` | 🔜 | Trend, momentum, support/resistance, volatility |
| `company-story` | 🔜 | Company history, business model and turning points from 10-K filings |
| `news-analyst` | 🔜 | Filters the news to catalysts and risks |
| `scenarios` | 🔜 | Bear / base / bull price ranges with probabilities and macro sensitivity |
| `committee` | 🔜 | Bull, bear and risk analysts debate; you get a one-page brief |

## Install

Requires Python 3.9+ and [Claude Code](https://claude.com/claude-code).

```
/plugin marketplace add <your-github-user>/ai-equity-desk
/plugin install ai-equity-desk@ai-equity-desk
```

Then ask Claude: **"set up the equity desk"**.

## Free data sources

| Source | Data | Key needed |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo, unofficial) | prices, profiles, statements | no |
| [SEC EDGAR](https://www.sec.gov/edgar) | official US filings | no (a contact User-Agent is required by SEC) |
| [FRED](https://fred.stlouisfed.org) | US macro data | no |

Markets: **US** (full), **BIST / Borsa Istanbul** (prices and statements; more coming).

## Why it is light on tokens

Python does the math and Claude reads only compact summaries. A price check costs a few hundred tokens, not a full table. Results are cached locally in `~/.ai-equity-desk/`.

## Try the data layer directly

```
python skills/desk-data/scripts/desk.py quote AAPL
python skills/desk-data/scripts/desk.py financials NVDA
python skills/desk-data/scripts/desk.py macro
python skills/desk-data/scripts/desk.py global
```
