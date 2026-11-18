# Claude Stock Trader Skills

Claude Code skills for stock traders and investors, built on free data. They research US stocks and keep your trading journal. They do not place trades. Ask Claude about a company and the skills fetch prices, financial statements, SEC filings and news on your computer, check the numbers against what the company filed, and give Claude a short summary to reason about. No API keys, no subscriptions, no bundled data.

> Not financial advice. The skills describe and explain public data. They do not tell you to buy, sell or hold, and they do not give price targets. Free data can be late or wrong.

## What makes it different

**It checks the data.** Free stock data comes from Yahoo Finance, and Yahoo is sometimes wrong. The fundamentals skill compares Yahoo's statement figures with the 10-K figures the company filed with the SEC and reports how many matched. Apple and Microsoft match 18 of 18. Coca-Cola matches 16 of 18: Yahoo's operating income for 2025 is $14.9bn, the 10-K says $13.8bn. Every fundamentals report carries that check, so you know when to trust a ratio.

**It reads what the company said, not only what was written about it.** The company story uses 15 years of revenue and profit from 10-K filings. The news brief lists the 8-K filings from the same weeks next to the headlines, and when a headline and a filing disagree, the filing wins.

**It keeps score.** Save a bear, base and bull case for a stock, and the skill later checks where the price actually went. Over time the scorecard shows whether your ranges are too narrow and whether your base cases lean optimistic, and which assumption tends to miss.

**It reviews your own trading.** The portfolio skill keeps a thesis and a sell condition for every position, replays the 2000, 2008, 2018, 2020 and 2022 crashes on your current weights, and reviews your own trades for the habits that cost individual investors most: selling winners and keeping losers, averaging down, and piling into one sector.

**It follows the money from the filings.** The smart-money skill reads any fund's 13F straight from SEC EDGAR and shows what changed since the quarter before. It separates insiders' open-market buys from planned sales and routine pay, and reads House members' trade reports. Every result says how old the filing is.

**It runs on free sources only.** yfinance, SEC EDGAR, FRED, BIS, Nasdaq's public calendars, the House Clerk, Wikipedia and Google News. Anthropic's own financial-services plugins connect to paid providers such as FactSet, and most finance MCP servers need an API key.

**It is tested.** 75 offline tests with hand-checked answers, plus a live check that runs every script on companies picked to break naive code: share classes (BRK.B), foreign ADRs that report in another currency (TSM, BABA), banks (JPM), an ETF and an unknown ticker.

**It is cheap on tokens.** The scripts do the arithmetic and print one line of JSON. A price check is about 200 tokens, a fundamentals report with three peers under 2,000.

## Skills

| Skill | What you can ask |
|---|---|
| `desk-setup` | "Set up the stock trader skills." Checks Python, installs packages, tests each data source |
| `desk-data` | "How is NVDA doing?", "Latest 10-K for MSFT", "Where are rates?" Prices, returns after inflation, statements, SEC filings, macro |
| `fundamentals` | "Is Costco a good business?", "Compare KO with PEP." Grades growth, profitability, cash conversion and balance sheet; valuation against peers |
| `technicals` | "What does the AAPL chart say?", "Backtest the 200-day rule on SPY." Trend, RSI, MACD, volatility, support and resistance, performance against the S&P 500, and five classic rules tested against buy-and-hold |
| `company-story` | "Tell me the story of Exxon." What it does, its turning points, 15 years of results, the deepest share-price falls and how long recovery took |
| `news-analyst` | "Why did JPM move this week?" Recent headlines and 8-K filings, sorted into what could help the business, what could hurt it, and noise |
| `portfolio` | "Add 10 AAPL at 180", "How many NVDA can I buy with a stop at 135?", "How would my portfolio do in a crash?", "Review my trades." Positions with a thesis and sell condition, pre-trade checks against your own limits, crash replays, and a review of your trading habits |
| `screener` | "Find cheap quality stocks", "Which small caps are breaking out?" Screens the S&P 500, 400, 600 or every US listing on price action and SEC fundamentals, with nine ready presets |
| `market` | "How is the market?", "What's on the calendar this week?" Trend, distribution days, breadth, VIX, credit spreads and sector leadership counted into risk-on, mixed or risk-off; economic releases, Fed days and earnings dates |
| `smart-money` | "What did Berkshire buy?", "Are insiders buying NVDA?", "What is Congress trading?" 13F holdings and changes, a consensus of 27 stock-picking funds, Form 4 insider trades, House members' trade reports |
| `scenarios` | "Bull and bear case for Microsoft", "What growth is priced into Nvidia?", "How did my past calls do?" Cases from ten years of 10-K figures, the growth today's price assumes, and a scorecard for saved views |

Coming next: `committee` (bull and bear analysts argue the case and Claude writes a one-page report).

## Install

You need Python 3.9 or newer and [Claude Code](https://claude.com/claude-code).

```
/plugin marketplace add mercan700/claude-stock-trader-skills
/plugin install stock-trader-skills@stock-trader-skills
```

Then ask Claude to "set up the stock trader skills". The SEC asks automated clients for a contact name and email in the User-Agent; setup asks for yours and stores it on your computer; it is sent only to the SEC.

## Data sources

| Source | Data | Key |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo Finance, unofficial) | prices, profiles, statements, news | none |
| [SEC EDGAR](https://www.sec.gov/edgar) and [XBRL company facts](https://www.sec.gov/edgar/sec-api-documentation) | filings; 10-K figures for the cross-check | none; SEC asks for a contact User-Agent |
| [FRED](https://fred.stlouisfed.org) | US rates, inflation, unemployment | none |
| [BIS data portal](https://data.bis.org) | consumer prices and policy rates by country | none |
| [Wikipedia](https://www.wikipedia.org) and [Wikidata](https://www.wikidata.org) | company history; matching a ticker to its article | none |
| [Google News RSS](https://news.google.com) | recent headlines | none |
| [SEC XBRL frames](https://www.sec.gov/edgar/sec-api-documentation) | one line item for every filer at once, for the screener | none; contact User-Agent |
| [Nasdaq](https://www.nasdaq.com/market-activity/stocks/screener) (public website data) | market caps, economic and earnings calendars | none |
| [Federal Reserve](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | FOMC meeting dates | none |
| [House Clerk](https://disclosures-clerk.house.gov) | members' periodic transaction reports | none |
| [OpenFIGI](https://www.openfigi.com) | CUSIP to ticker for 13F holdings | none |

yfinance is not affiliated with Yahoo. Yahoo's terms allow personal use of its data; check them before using these skills for anything else.

Your portfolio and saved scenarios are kept in `~/.stock-trader-skills/` as plain JSON files. They stay on your computer; only ticker symbols go out, to fetch prices. Downloads are cached there too: prices for 15 minutes, news for an hour, statements for a week, Wikipedia articles for a month, and filings that never change (13F, Form 4, House reports) for a year.

## Running the scripts yourself

```
python skills/desk-data/scripts/desk.py quote AAPL
python skills/desk-data/scripts/desk.py verify KO
python skills/fundamentals/scripts/fundamentals.py COST --peers WMT TGT
python skills/technicals/scripts/technicals.py MSFT
python skills/company-story/scripts/story.py XOM
python skills/news-analyst/scripts/news.py JPM --days 7
python skills/scenarios/scripts/scenarios.py build MSFT --years 5
python skills/portfolio/scripts/portfolio.py stress
python skills/portfolio/scripts/portfolio.py check NVDA 40 --stop 135
python skills/technicals/scripts/technicals.py SPY --backtest --years 20
python skills/screener/scripts/screener.py run --universe sp600 --preset quality
python skills/market/scripts/market.py regime
python skills/smart-money/scripts/smartmoney.py fund berkshire
python skills/smart-money/scripts/smartmoney.py insiders NVDA
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

[PolyForm Noncommercial 1.0.0](LICENSE). In short: you can use, change and share these skills for personal use with no commercial application (study, research, hobby projects), and charities, schools, public research bodies and government institutions can use it too. Using it in a business, in a paid product or service, or to manage money for clients needs a commercial license from coraltechh: [open an issue](https://github.com/mercan700/claude-stock-trader-skills/issues) to ask. The LICENSE file is what counts.

The data these skills fetch has its own terms. Yahoo Finance data in particular is for personal use.
