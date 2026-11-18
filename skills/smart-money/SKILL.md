---
name: smart-money
description: Shows what well-known investors, company insiders and members of Congress have been buying and selling, from the filings the law requires them to make. Reads any fund's latest 13F with what it bought, added, trimmed and sold since the quarter before (Berkshire, Pershing Square, Appaloosa, Baupost, Duquesne, Third Point, Tiger, Coatue and others by name, or any filer by SEC number). Finds the stocks the stock-picking funds own and bought together. Reads Form 4 insider trades for one company, separating open-market buys from planned sales and routine pay, and flags clusters of insiders buying. Lists House members' stock trades from their periodic transaction reports. Use for "what did Buffett buy", "what is Ackman holding", "what are hedge funds buying", "are insiders buying X", "who is selling X", "what stocks is Congress buying" or "did any politician trade X". US filings only.
---

# Smart money

## Steps

Run from this skill's folder:

```
python scripts/smartmoney.py funds
python scripts/smartmoney.py fund berkshire
python scripts/smartmoney.py fund 1336528 --top 30
python scripts/smartmoney.py consensus
python scripts/smartmoney.py insiders NVDA --days 180
python scripts/smartmoney.py congress --days 60
python scripts/smartmoney.py congress --ticker NVDA --days 180
python scripts/smartmoney.py congress --member pelosi --days 365
```

- `fund` takes a key from `funds` or an SEC CIK number. If the user names a fund that is not in the list, tell them to find its CIK on sec.gov (EDGAR company search) and pass the number.
- `consensus` reads about 25 funds and takes one to two minutes the first time. Later runs read the cache.
- `congress` downloads each report as a PDF. 60 days is usually 50 to 100 reports and about a minute.
- SEC needs the contact User-Agent that desk-setup stores. OpenFIGI (CUSIP to ticker) and the House Clerk need nothing.

## Fund brief

```
## <fund>: 13F for the quarter ending <quarter_end> (filed <filed>, <days> days ago)
<positions> stocks, $<value_bn> bn; the top 10 are <top10_pct>% of it.

| Stock | Weight | Change since last quarter |
|---|---|---|

New: ... Sold out: ... Biggest adds and trims: ...
What the changes say: one or two lines, e.g. "added to banks while cutting tech", without guessing motives.
```

## Insider brief

Lead with open-market buys, because they are the signal. Then sales: who, how much, what share of their holding, and how many were under a 10b5-1 plan. Mention a cluster buy if there is one. Put grants, exercises and tax withholding in one line as routine.

## Congress brief

Most bought and most sold, with the number of members and the amount range. For a ticker or a member, list the trades with trade date, filing date and owner (member, spouse, child).

## Rules

- None of this is a reason to buy on its own. Say what the filing shows and how old it is. A 13F is 45 to 135 days old when anyone reads it. A fund can have sold already, and the 13F does not show shorts or hedges.
- Never describe a member of Congress's trade as insider trading or say they acted on private knowledge. Report the trade, its timing and the filing lag, and leave conclusions to the user.
- Insider sales are common and usually say little: taxes, diversification, a house. Large sales outside a 10b5-1 plan, sales of most of a holding, or several executives selling together are worth mentioning.
- A ticker of `null` means OpenFIGI had no match for the CUSIP. Use the issuer name.
- The Congress data covers the House only. Say so when the user asks about Congress in general.
