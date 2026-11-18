# AI Equity Desk

A set of Claude skills for researching listed companies with free data. The scripts run on your computer, fetch prices, statements and macro data from public sources, and hand Claude short summaries to reason about. There are no paid APIs and no bundled data.

> Not financial advice. The skills describe and explain public data. They do not tell you to buy, sell or hold, and they do not give price targets. Free data can be late or wrong.

## Skills

| Skill | Status | What it does |
|---|---|---|
| `desk-setup` | available | Checks Python, installs packages, tests each data source |
| `desk-data` | available | Prices, returns after inflation and in dollars, statements cross-checked with SEC filings, US and Turkish macro, world markets |
| `fundamentals` | available | Grades growth, profitability, cash conversion and balance sheet; compares valuation with peers |
| `technicals` | available | Trend, RSI, MACD, volatility, support and resistance, performance against the index |
| `company-story` | available | What the company does, its turning points, 15 years of revenue and profit, and the share price's deepest falls |
| `news-analyst` | available | Recent headlines and the company's own 8-K filings, sorted into what could help, what could hurt and noise |
| `scenarios` | planned | Bear, base and bull price ranges with stated assumptions |
| `committee` | planned | Bull, bear and risk analysts argue the case; the result is a one-page brief |

## Markets

US stocks are fully supported. Borsa Istanbul (`--market BIST`) supports prices, statements, Turkish inflation and policy rate, and the fundamentals and technicals skills. KAP filings are planned.

Two features deal with the weak spots of free data:

- Statement figures for US companies are compared with what the company filed with the SEC, and every analysis says how many matched.
- Returns are shown in local currency, in US dollars and after inflation. For a Turkish stock the lira return alone mostly measures inflation: in the year to November 2026 Turkish Airlines rose 21% in lira, 2% in dollars, and fell about 7% after inflation.

Some cases the fundamentals script handles explicitly:

- Companies that report in one currency and trade in another (Turkish Airlines reports in USD, TSMC ADRs trade in USD and report in TWD). The market cap is converted before ratios are computed.
- Banks and insurers, where margins, free cash flow and net debt are not meaningful.
- Lease-heavy industries, conglomerates and high-inflation reporting currencies, which get a written caveat with the numbers.

## Install

You need Python 3.9 or newer and [Claude Code](https://claude.com/claude-code).

```
/plugin marketplace add mercan700/ai-equity-desk
/plugin install ai-equity-desk@ai-equity-desk
```

Then ask Claude to "set up the equity desk".

## Data sources

| Source | Data | Key |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo Finance, unofficial) | prices, profiles, statements | none |
| [SEC EDGAR](https://www.sec.gov/edgar) | US filings | none; SEC asks for a contact User-Agent |
| [SEC XBRL company facts](https://www.sec.gov/edgar/sec-api-documentation) | 10-K figures for cross-checks | none |
| [FRED](https://fred.stlouisfed.org) | US macro series | none |
| [BIS data portal](https://data.bis.org) | consumer prices and policy rates by country | none |
| [Wikipedia](https://www.wikipedia.org) and [Wikidata](https://www.wikidata.org) | company history; the ticker-to-article match | none |
| [Google News RSS](https://news.google.com) | recent headlines, English and Turkish | none |

yfinance is not affiliated with Yahoo. Yahoo's terms allow personal use of its data; check them before using the desk for anything else.

## Token use

The scripts do the arithmetic and print one line of JSON, so Claude reads a summary instead of a table. A price check is about 200 tokens and a full fundamentals run with three peers is under 2,000. Downloads are cached in `~/.ai-equity-desk/` (prices for 15 minutes, news for an hour, statements for a week, Wikipedia articles for a month).

## Running the scripts yourself

```
python skills/desk-data/scripts/desk.py quote AAPL
python skills/desk-data/scripts/desk.py financials NVDA
python skills/fundamentals/scripts/fundamentals.py THYAO --market BIST --peers PGSUS
python skills/technicals/scripts/technicals.py MSFT
python skills/company-story/scripts/story.py THYAO --market BIST
python skills/news-analyst/scripts/news.py AAPL --days 7
```

## Tests

```
python -m unittest discover -s tests      # offline, synthetic data with known answers
python tests/live_check.py                # live, 17 US and BIST companies, a few minutes
```

The live check runs every script on companies chosen to break naive code: share classes (BRK.B), foreign ADRs (TSM, BABA), banks (JPM, GARAN), a conglomerate (KCHOL), BIST companies that report in USD, an ETF and an unknown ticker. It flags ratios outside plausible ranges, and checks that the company-story skill lands on the right Wikipedia article for seven companies whose names trip up a search (Apple, Exxon, Aselsan, Erdemir and others).
