---
name: scenarios
description: Builds bear, base and bull cases for a stock from the company's own ten-year record (revenue growth, net margin and the P/E or price-to-sales the market paid). Shows what each case means for the share price, and what growth today's price already assumes. Saves cases to a journal and later scores them against what the price actually did, so the user learns whether their views run optimistic. Use for questions like "what could X be worth in 3 years", "bull and bear case for X", "what is priced into X", "what growth does X need", "save this view", "how did my past calls do" or "score my scenarios". Built for US stocks; Borsa Istanbul works with --market BIST.
---

# Scenarios

## Steps

1. Build the cases from this skill's folder:

   ```
   python scripts/scenarios.py build AAPL
   python scripts/scenarios.py build MSFT --years 5
   ```

2. Read the output (see below). If an assumption is unrealistic, rebuild with `--set`. You might do this because of something the user knows, or because a warning in `notes` says so.

   ```
   python scripts/scenarios.py build NVDA --set bear.growth=5 --set base.multiple=30 --set shares=-1
   ```

   Growth, margin and the share-count change are percent per year. The multiple is a plain number. Say which numbers you changed and why.
3. Write the brief below.
4. Offer to save the cases. Save only when the user agrees, and put their reason in the note:

   ```
   python scripts/scenarios.py save AAPL --note "services growth keeps margins above 25%"
   ```

5. When the user asks how past views did, run `python scripts/scenarios.py score` (optionally with a ticker) and write the scorecard below. `list` shows saved ids and `delete ID` removes one, but only delete when the user asks.

## The build output

- `cases`: for each case, the three assumptions, the price at the end of the horizon, and the annual and total return from today. `revenue_growth_avg_pct` is the average after the fade (see below).
- `start`: the figures the cases grow from. These are the last four quarters where Yahoo has them, otherwise the last fiscal year. Includes today's margin and multiple.
- `growth_needed_pct`: the average revenue growth needed, at the base margin and multiple, to keep the price where it is (`to_hold_price`) or to earn 10% a year. Comparing this with past growth is the most useful line in the output. It tells the user what the price already assumes.
- `history`: the range of past growth, margins and multiples, and where today's multiple sits in that range (`multiple_now_percentile`).
- `growth_fade`: starting growth moves in a straight line toward inflation plus 2% over ten years. A company growing 30% today is assumed to grow about 27%, 25% and 22% over the next three years.
- `notes`: warnings to pass on. These cover a short history, a multiple outside its historical range, capped growth, or a company valued on sales because profits are unsteady.

How the defaults are set:
- Bear and bull use the 20th and 80th percentile of the last ten years.
- Base growth is the median.
- The base margin comes from the last five years.
- The base multiple is today's, pulled back to the edge of its usual range when it sits outside that range.

## Brief

```
## <name>: scenarios to <year>
Price <price> on <date>. Built from <history.source>, <history.years>.

| | Bear | Base | Bull |
|---|---|---|---|
| Revenue growth a year | | | |
| Net margin | | | |
| P/E (or price to sales) | | | |
| Price in <year> | | | |
| Return a year | | | |

What the price assumes: at today's price the company needs about <to_hold_price>% growth a year just to hold
the price. It grew <range> over <history.years>.

What would make each case happen: one concrete line per case, tied to the business.
What the cases leave out: dividends, a recession year, a big acquisition, or whatever applies here.

These are ranges built from the company's own history, not forecasts. Not investment advice.
```

## Scorecard

```
## Scorecard: <n> saved views, <scored> old enough to score

| Saved | Stock | Moved | Expected by now (bear / base / bull) | Where it is | Index |
|---|---|---|---|---|---|

Range: <inside_bear_bull_pct>% landed between bear and bull.
Lean: <above_base_pct>% came in above base. Near 50% is balanced.
What went differently: the assumption that missed most, from assumption_check (for example
"assumed 6% revenue growth, the company grew 11%").
```

## Rules

- Never call a case a target or recommend acting on it. Write "the base case ends near $370". Do not write "fair value is $370".
- Explain where each number came from: the history, the fade, the clamp, or an override. Do not present a default as your own judgment.
- When `notes` says the growth was capped or the company is young, the history is from a small base. Lower the bear growth with `--set` to what a mature company in the industry would do, and say so.
- When today's multiple is above its whole history, say that most of the base case's downside comes from the multiple returning to normal, not from the business.
- Bear and bull combine the low or high end of all three assumptions at once. Real outcomes usually fall inside them, so do not call the bear case "the worst case" or the bull case "the best case".
- A scorecard needs more than ten scored views before it says anything about the user. With fewer, say the sample is too small and only describe the individual cases.
- Banks and insurers: revenue and margin are defined loosely in the data, so treat their cases as rough and say so.
- ADRs such as TSM or BABA are refused because one ADR does not equal one share. Use the fundamentals skill for them.
