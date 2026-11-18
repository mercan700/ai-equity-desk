---
name: committee
description: Runs an investment committee on one stock. Gathers fundamentals, technicals, scenarios, news, company history, insider trades and the market regime in one call. Then a bull, a bear and a risk analyst each argue from that data, and the result is a one-page HTML report with a price chart and the scenario range. The bear case is always on the page, and every number in a claim is checked against the gathered data. Use for "run the committee on X", "full report on X", "should I look at X", "bull vs bear on X", "deep dive on X" or "one-page report on X". Built for US stocks; Borsa Istanbul works with --market BIST, without insider trades or market regime.
---

# Committee

## Steps

1. Gather the evidence from this skill's folder. It runs the other skills for you, so do not run them one by one:

   ```
   python scripts/committee.py gather AAPL
   ```

   This takes one to two minutes. The output holds `data_file`, `views_file`, a short version of each section, and `missing` for any section that failed. The full data stays in `data_file`.
2. Read every section, then write the three analysts' cases and the chair's summary to `views_file` in the format below. Write them one seat at a time and argue each seat honestly. The bull analyst argues for the stock even when the data looks bad, and the bear analyst argues against it even when the data looks good.
3. Build the report:

   ```
   python scripts/committee.py report AAPL --open
   ```

   If `built` is false, fix what `errors` lists and run it again. If `unverified_numbers` is not empty, a number in a claim is not in the data. Either correct it, or show the arithmetic with `=` so the inputs can be checked ("(641 - 509) / 509 = 26%"). Then rebuild. A number you cannot trace does not belong in the report.
4. Reply with the path to the report and the chair's summary in three or four sentences, including the strongest case against.

## The views file

```json
{
  "bull": {
    "thesis": "one sentence",
    "points": [{"claim": "a fact from the data and why it matters", "source": "fundamentals"}],
    "would_be_wrong_if": "the one thing that would break this case"
  },
  "bear": {"thesis": "...", "points": [...], "would_be_wrong_if": "..."},
  "risk": {"thesis": "...", "points": [...]},
  "chair": {
    "leans": "bull | bear | split",
    "summary": "three to five sentences",
    "would_change_mind": "the evidence that would flip the lean",
    "watch": ["dated, checkable things to watch"]
  }
}
```

`source` is the section a point comes from: fundamentals, technicals, scenarios, news, story, insiders, market or calendar. Only sections that came back without an error count.

The report refuses to build when:
- a seat has no thesis or no points;
- a point's source is missing or failed;
- the bear case has fewer than 3 points, or more than one point fewer than the bull case;
- the chair has no summary, no lean or no `would_change_mind`.

## The seats

- **Bull analyst:** what the business does well and why the price may be too low. Draw on growth, margins and returns from `fundamentals`. Use `growth_needed_pct` from `scenarios` against past growth, plus history and headlines.
- **Bear analyst:** what is wrong or priced too high. Look for weak cash conversion, debt, slowing growth and the bear scenario's price. Add a multiple at the top of its range, insider selling, a weak trend, and headlines that hurt the business.
- **Risk analyst:** what could go wrong whichever case is right. Cover volatility and drawdowns, the distance to support, the market posture, and the next earnings and Fed dates. Add past crashes from `story`.
- **Chair:** weighs the three. `leans` says where the evidence points now, and `split` is a fair answer. `would_change_mind` names data that would move it.

## Rules

- Every claim states a fact from the gathered data with its number, then says why it matters. Opinion without a number goes in the thesis, not in the points.
- Give the bear case as much effort as the bull case. When the data mostly points one way, the other side still argues its best case. Say in the chair's summary that the data is lopsided.
- Never write buy, sell, target price or fair value. The chair says where the evidence leans and what would change it.
- Insider sales under a 10b5-1 plan were scheduled months ahead. Say so when you cite them.
- When `missing` lists a section, do not fill the gap from memory. The report lists what was missing.
- Headlines are not facts about the business. Cite them as "headlines say".
- Reports and data files are saved under `~/.stock-trader-skills/committee/`. Running `gather` again on the same day replaces that day's data.
