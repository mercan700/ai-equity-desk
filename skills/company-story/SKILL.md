---
name: company-story
description: Tells the story of a listed company. Covers what it does, where it came from, how revenue and profit grew, and how the share price behaved through its best years, worst years and deepest falls. Built from Wikipedia, SEC filings and the full price history. Use for questions like "tell me the story of X", "history of X", "how did X get here", "what does X do", "X company background" or "what were X's worst crashes". Covers US stocks and Borsa Istanbul (--market BIST).
---

# Company story

## Steps

1. Run the script from this skill's folder:

   ```
   python scripts/story.py AAPL
   python scripts/story.py THYAO --market BIST
   ```

2. Check `wikipedia.title` before using the article. Most companies are matched by ticker through Wikidata (`matched_by: ticker (Wikidata)`), and those matches are exact. A `name search` match can be wrong. If the lead describes a different company, rerun with `--wiki-title "Exact Title"`. If no title fits, leave Wikipedia out and say so.
3. Write the story below.

## The script's output

- `profile`: Yahoo's business summary, sector, industry, employees and website.
- `wikipedia`: the article lead and its history section, cut to about 3,500 characters. For Turkish companies the history can come from the Turkish article (`history_source`), so translate it.
- `sec` (US): registered name, former names, state of incorporation, first SEC filing, and up to 15 years of revenue and net income from 10-K filings, in millions.
- `annual_millions` (BIST): about four years of revenue and net income from Yahoo, in the reporting currency. Longer history needs KAP, which the desk does not fetch yet.
- `market_history`: first price date, total return multiple, annual growth rate, the three deepest falls with how long recovery took, and the best and worst calendar years.

## Story

```
## <name>: the story so far
Sources: Wikipedia (<article url>), <SEC 10-K figures | Yahoo statements>, Yahoo price history from <first_price_date>

What it does: 2 or 3 sentences in plain words. Name the main products or services and who pays for them.

How it got here: 4 to 8 turning points in date order, one line each. Founding, listing, the big acquisitions,
crises, new products, ownership changes. Use the dates the sources give.

The numbers: revenue and net income at the start and end of the series, the growth rate in between,
and the years that broke the pattern.

The share price: total return since <date>, the deepest falls with what caused them where the history
explains it, and how long recovery took.

What to watch next: 2 or 3 open questions that follow from the story, for example "can the margins of
the last three years hold if fuel prices rise again?"

Not investment advice.
```

## Rules

- Write the turning points as a narrative, not a list of everything in the article. Leave out events that did not change the business.
- Connect events to the numbers where the sources allow it. If a fall in the share price lines up with a crisis in the history section, say so. If you cannot tie them together, do not guess a cause.
- Treat Wikipedia as background, not as a source for current figures. Use the script's numbers for revenue, profit and prices.
- `market_history.data_warning` means Yahoo's early prices were broken and the history now starts later. Mention the new start date. BIST prices before 2005 are often affected.
- Returns include dividends. For a BIST company, note that lira returns are mostly inflation. For the real return, run `desk.py returns <ticker> --market BIST` from the desk-data skill and quote it.
- Annual revenue and income in `sec` come from the company's own filings. Revenue tags changed in 2018 for many companies, so a jump that year can be an accounting change. Check the history before calling it growth.
- If a part of the output has an `error`, write the story from the other parts and say what is missing.
