# AI Equity Desk

Claude skills for researching US stocks with free data. Ask Claude about a company and the skills fetch prices, financial statements, SEC filings and news on your computer, check the numbers against what the company filed, and give Claude a short summary to reason about. No API keys, no subscriptions, no bundled data.

> Not financial advice. The skills describe and explain public data. They do not tell you to buy, sell or hold, and they do not give price targets. Free data can be late or wrong.

## What makes it different

**It checks the data.** Free stock data comes from Yahoo Finance, and Yahoo is sometimes wrong. The desk compares Yahoo's statement figures with the 10-K figures the company filed with the SEC and reports how many matched. Apple and Microsoft match 18 of 18. Coca-Cola matches 16 of 18: Yahoo's operating income for 2025 is $14.9bn, the 10-K says $13.8bn. Every fundamentals report carries that check, so you know when to trust a ratio.

**It reads what the company said, not only what was written about it.** The company story uses 15 years of revenue and profit from 10-K filings. The news brief lists the 8-K filings from the same weeks next to the headlines, and when a headline and a filing disagree, the filing wins.

**It keeps score.** Save a bear, base and bull case for a stock, and the desk later checks where the price actually went. Over time the scorecard shows whether your ranges are too narrow and whether your base cases lean optimistic, and which assumption tends to miss.

**It runs on free sources only.** yfinance, SEC EDGAR, FRED, BIS, Wikipedia and Google News. Anthropic's own financial-services plugins connect to paid providers such as FactSet, and most finance MCP servers need an API key.

**It is tested.** 50 offline tests with hand-checked answers, plus a live check that runs every script on companies picked to break naive code: share classes (BRK.B), foreign ADRs that report in another currency (TSM, BABA), banks (JPM), an ETF and an unknown ticker.

**It is cheap on tokens.** The scripts do the arithmetic and print one line of JSON. A price check is about 200 tokens, a fundamentals report with three peers under 2,000.

## Skills

| Skill | What you can ask |
|---|---|
| `desk-setup` | "Set up the equity desk." Checks Python, installs packages, tests each data source |
| `desk-data` | "How is NVDA doing?", "Latest 10-K for MSFT", "Where are rates?" Prices, returns after inflation, statements, SEC filings, macro |
| `fundamentals` | "Is Costco a good business?", "Compare KO with PEP." Grades growth, profitability, cash conversion and balance sheet; valuation against peers |
| `technicals` | "What does the AAPL chart say?" Trend, RSI, MACD, volatility, support and resistance, performance against the S&P 500 |
| `company-story` | "Tell me the story of Exxon." What it does, its turning points, 15 years of results, the deepest share-price falls and how long recovery took |
| `news-analyst` | "Why did JPM move this week?" Recent headlines and 8-K filings, sorted into what could help the business, what could hurt it, and noise |
| `scenarios` | "Bull and bear case for Microsoft", "What growth is priced into Nvidia?", "How did my past calls do?" Cases from ten years of 10-K figures, the growth today's price assumes, and a scorecard for saved views |

Coming next: `portfolio` (a thesis journal and stress test) and `committee` (bull and bear analysts argue the case and the desk writes a one-page report).

## Install

You need Python 3.9 or newer and [Claude Code](https://claude.com/claude-code).

```
/plugin marketplace add mercan700/ai-equity-desk
/plugin install ai-equity-desk@ai-equity-desk
```

Then ask Claude to "set up the equity desk". The SEC asks automated clients for a contact name and email in the User-Agent; setup asks for yours and stores it on your computer; it is sent only to the SEC.

## Data sources

| Source | Data | Key |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo Finance, unofficial) | prices, profiles, statements, news | none |
| [SEC EDGAR](https://www.sec.gov/edgar) and [XBRL company facts](https://www.sec.gov/edgar/sec-api-documentation) | filings; 10-K figures for the cross-check | none; SEC asks for a contact User-Agent |
| [FRED](https://fred.stlouisfed.org) | US rates, inflation, unemployment | none |
| [BIS data portal](https://data.bis.org) | consumer prices and policy rates by country | none |
| [Wikipedia](https://www.wikipedia.org) and [Wikidata](https://www.wikidata.org) | company history; matching a ticker to its article | none |
| [Google News RSS](https://news.google.com) | recent headlines | none |

yfinance is not affiliated with Yahoo. Yahoo's terms allow personal use of its data; check them before using the desk for anything else.

Downloads are cached in `~/.ai-equity-desk/`: prices for 15 minutes, news for an hour, statements for a week, Wikipedia articles for a month.

## Running the scripts yourself

```
python skills/desk-data/scripts/desk.py quote AAPL
python skills/desk-data/scripts/desk.py verify KO
python skills/fundamentals/scripts/fundamentals.py COST --peers WMT TGT
python skills/technicals/scripts/technicals.py MSFT
python skills/company-story/scripts/story.py XOM
python skills/news-analyst/scripts/news.py JPM --days 7
python skills/scenarios/scripts/scenarios.py build MSFT --years 5
```

## Other markets

The scripts also work for Borsa Istanbul with `--market BIST`: Turkish inflation and policy rate from BIS, returns in lira, dollars and after inflation, Turkish-language news, and handling for companies that report in dollars but trade in lira. SEC checks do not apply there.

## Tests

```
python -m unittest discover -s tests      # offline, synthetic data with known answers
python tests/live_check.py                # live, a few minutes
```

The live check flags ratios outside plausible ranges and confirms that the company-story skill lands on the right Wikipedia article for companies whose names trip up a search.

## License

[PolyForm Noncommercial 1.0.0](LICENSE). In short: you can use, change and share the desk for personal use with no commercial application (study, research, hobby projects), and charities, schools, public research bodies and government institutions can use it too. Using it in a business, in a paid product or service, or to manage money for clients needs a commercial license from coraltechh: [open an issue](https://github.com/mercan700/ai-equity-desk/issues) to ask. The LICENSE file is what counts.

The data the desk fetches has its own terms. Yahoo Finance data in particular is for personal use.
