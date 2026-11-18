---
name: news-analyst
description: Reads the recent news about one company and sorts it into what could move the business and what is noise. Pulls headlines from Google News and Yahoo Finance and, for US companies, the 8-K filings the company made in the same weeks. Use for questions like "what's the news on X", "why did X move", "anything happening with X", "X catalysts", "X risks this month" or "X haberleri". Covers US stocks and Borsa Istanbul (--market BIST, Turkish-language sources).
---

# News analyst

## Steps

1. Run the script from this skill's folder:

   ```
   python scripts/news.py AAPL
   python scripts/news.py THYAO --market BIST --days 14
   ```

   The default window is 30 days and 25 items. Use `--days 7` for "this week" and `--limit 40` when the user wants everything.
2. Read the items. Each has a date, headline, source, topic tags and a link. Yahoo items also carry a short summary.
3. Write the brief below.

## The script's output

- `news.items`: the newest headlines that name the company. Duplicates and stories about other companies are already removed (`dropped_off_topic` counts them).
- `topics` are keyword tags: earnings, guidance, deal, legal_regulatory, management, capital, rating, product_operations, ownership, trading_flow, macro. They are rough. Read each headline yourself before you rely on its tag.
- `company_filings_8k` (US): what the company itself filed. An 8-K for "results of operations" is an earnings release, and "director or officer change" is a management change. A filing is a primary source. Rank it above any headline.
- `company_disclosures` (BIST): KAP is not fetched yet. Point the user to it for anything that matters.

## Brief

```
## <name>: news, last <days> days
Sources: Google News, Yahoo Finance<, SEC 8-K filings>. <found> relevant items.

What happened: the 2 to 4 stories that matter, each in one or two sentences with its date and source.
Combine several headlines about the same event into one story.

Could help the business: developments that could raise revenue or margins, or return cash to shareholders, and why.
Could hurt the business: the risks, and why.
Noise: what got coverage but does not change the business (broker flows, price-move articles, listicles). One line.

What the company itself said: 8-K filings or KAP disclosures in the window, or "nothing filed".
Open questions: what to check next, for example "the next earnings date" or "whether the contract is binding".

Headlines can be wrong or one-sided. Not investment advice.
```

## Rules

- Do not predict the share price from the news, and do not call news bullish or bearish for the stock. Describe what it could mean for the business.
- Give each story's date. A three-week-old story that the market has already priced in reads differently from yesterday's.
- When a headline and an 8-K disagree, go with the filing and say so.
- Treat `trading_flow` items (large broker buys, block trades, money flow) and stock-forecast articles as noise unless several point the same way. Name them once and move on.
- Many BIST headlines repeat a KAP disclosure. If the headline names the disclosure ("pay geri alımı", "bedelsiz sermaye artırımı"), report the event and the amount, and tell the user to confirm it on KAP.
- If `found` is low (under 5), say the coverage is thin rather than stretching it. If `source_errors` is present, name the source that failed.
- A name like Apple also matches stories about the fruit. Skip items that are plainly about something else.
- Answer in the user's language. Translate Turkish headlines when the user writes in English, and the other way round.
