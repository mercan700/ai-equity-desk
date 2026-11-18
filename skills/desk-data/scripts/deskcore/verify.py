"""Cross-check Yahoo's statement figures against what the company filed with the SEC.

SEC's XBRL "company facts" API returns every number a company has tagged in its
10-K filings. We keep the annual values for a handful of line items and compare
them with yfinance. US companies filing 10-Ks only: foreign filers (20-F, IFRS
tags) and BIST companies are reported as not checked.
"""
from datetime import date

from . import DeskError, cache, sec
from .prices import _num

# yfinance row -> US-GAAP tags that can hold it, most common first.
CONCEPTS = {
    "Total Revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                      "SalesRevenueNet", "RevenuesNetOfInterestExpense"],
    "Operating Income": ["OperatingIncomeLoss"],
    "Net Income": ["NetIncomeLoss"],
    "Diluted EPS": ["EarningsPerShareDiluted"],
    "Operating Cash Flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Total Assets": ["Assets"],
    "Stockholders Equity": ["StockholdersEquity"],
    "Cash And Cash Equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
}
INSTANT = {"Total Assets", "Stockholders Equity", "Cash And Cash Equivalents"}
TOLERANCE_PCT = 2.0


def _annual(facts, tags, instant):
    """{period_end: value} from 10-K filings; the latest filing wins (restatements)."""
    out = {}
    for tag in tags:
        units = facts.get(tag, {}).get("units", {})
        for unit, rows in units.items():
            for r in rows:
                if r.get("form") not in ("10-K", "10-K/A") or "end" not in r:
                    continue
                if not instant:
                    if "start" not in r:
                        continue
                    days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
                    if not 350 <= days <= 380:
                        continue
                prev = out.get(r["end"])
                if prev is None or r.get("filed", "") >= prev[1]:
                    out[r["end"]] = (r["val"], r.get("filed", ""))
        if out:  # first tag with data wins, so a company's own choice of tag is respected
            break
    return {k: v[0] for k, v in out.items()}


def sec_annuals(ticker):
    cik, _ = sec.cik_for(ticker)
    data = cache.get_json("facts", cik)
    if data is None:
        raw = sec._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").json()
        gaap = raw.get("facts", {}).get("us-gaap", {})
        data = {row: _annual(gaap, tags, row in INSTANT) for row, tags in CONCEPTS.items()}
        if not any(data.values()):
            data["_reason"] = ("files under IFRS rather than US GAAP (foreign filer)" if not gaap
                               else "no annual 10-K figures under this SEC registration yet, only quarterly filings")
        cache.put_json("facts", cik, data)
    return data


def _nearest(values, period, max_days=10):
    """SEC uses exact fiscal year-end dates, Yahoo sometimes rounds to month end."""
    target = date.fromisoformat(period)
    best = None
    for end, v in values.items():
        gap = abs((date.fromisoformat(end) - target).days)
        if gap <= max_days and (best is None or gap < best[0]):
            best = (gap, v)
    return None if best is None else best[1]


def check(ticker, statements, years=2):
    """Compare the latest `years` annual periods. statements: {period: {row: value_in_millions}}."""
    try:
        sec_data = sec_annuals(ticker)
    except DeskError as e:
        return {"status": "not checked", "reason": str(e)}
    if "_reason" in sec_data:
        return {"status": "not checked", "reason": sec_data["_reason"]}

    rows, matched, compared = [], 0, 0
    for period in sorted(statements, reverse=True)[:years]:
        for row in CONCEPTS:
            y = statements[period].get(row)
            s = _nearest(sec_data.get(row, {}), period)
            if y is None or s is None:
                continue
            s_cmp = s if row == "Diluted EPS" else s / 1e6
            diff = abs(y - s_cmp) / abs(s_cmp) * 100 if s_cmp else (0.0 if y == 0 else 100.0)
            compared += 1
            ok = diff <= TOLERANCE_PCT
            matched += ok
            if not ok:
                rows.append({"period": period, "item": row, "yahoo": y,
                             "sec": _num(s_cmp, 2), "diff_pct": _num(diff, 1)})
    if not compared:
        return {"status": "not checked", "reason": "no overlapping periods with SEC data"}
    share = matched / compared * 100
    return {
        "status": "checked",
        "source": "SEC XBRL company facts (10-K)",
        "matched": f"{matched}/{compared}",
        "confidence": "high" if share >= 90 else "medium" if share >= 70 else "low",
        "differences": rows,
    }
