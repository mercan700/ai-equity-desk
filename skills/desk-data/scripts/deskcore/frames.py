"""Fundamentals for every US filer at once, from SEC's XBRL "frames" API.

One request returns one line item for every company for one period, so a screen of
1,500 stocks needs about twenty requests instead of thousands. Periods are calendar
years as SEC aligns them: a fiscal year ending within about a month of December counts
as that calendar year, and other fiscal years go to the calendar year they mostly cover.
"""
from datetime import date

import requests

from . import DeskError, cache, sec

# Line items: several tags mean the same thing at different companies; the first one
# a company reports wins, except revenue, where the largest wins (some companies report
# a narrower contract-revenue figure next to total revenue).
DURATION = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dividends": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
}
INSTANT = {
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
}


def frame(tag, period, unit="USD", taxonomy="us-gaap"):
    """{cik (int): value} for one tag and period. Empty when SEC has no such frame."""
    key = f"frame:{taxonomy}:{tag}:{unit}:{period}"
    data = cache.get_json("facts", key)
    if data is None:
        try:
            r = sec.get(f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{tag}/{unit}/{period}.json")
            data = {str(d["cik"]): d["val"] for d in r.json().get("data", [])}
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 404:
                raise
            data = {}
        cache.put_json("facts", key, data)
    return {int(k): v for k, v in data.items()}


def latest_year(today=None):
    """The most recent calendar year whose annual reports are nearly all filed.
    Large companies file 10-Ks by early March, smaller ones by the end of March."""
    today = today or date.today()
    return today.year - 1 if (today.month, today.day) >= (4, 15) else today.year - 2


def _pick(tags, period, largest=False):
    out = {}
    for tag in tags:
        for cik, v in frame(tag, period).items():
            if cik not in out:
                out[cik] = v
            elif largest and v > out[cik]:
                out[cik] = v
    return out


def table(year=None):
    """{cik: {item: value}} for every filer, for `year` and the year before (revenue only)."""
    year = year or latest_year()
    key = f"table:{year}"
    cached = cache.get_json("facts", key)
    if cached is not None:
        return year, {int(k): v for k, v in cached.items()}
    items = {}
    for name, tags in DURATION.items():
        items[name] = _pick(tags, f"CY{year}", largest=(name == "revenue"))
    items["revenue_prev"] = _pick(DURATION["revenue"], f"CY{year - 1}", largest=True)
    for name, tags in INSTANT.items():
        items[name] = _pick(tags, f"CY{year}Q4I")
    if len(items["net_income"]) < 1000:
        raise DeskError(f"SEC returned too little data for {year}. Try again later.")
    out = {}
    for name, values in items.items():
        for cik, v in values.items():
            out.setdefault(cik, {})[name] = v
    cache.put_json("facts", key, out)
    return year, out


def metrics(f, market_cap):
    """Ratios from one company's line items and today's market cap. Percentages, None when
    a ratio would mislead (a P/E on a loss, a return on negative equity)."""
    def pct(a, b):
        return round(a / b * 100, 1) if a is not None and b not in (None, 0) else None

    rev, ni, eq = f.get("revenue"), f.get("net_income"), f.get("equity")
    fcf = f["ocf"] - (f.get("capex") or 0) if f.get("ocf") is not None else None
    cap = market_cap or None
    dividends = f.get("dividends")
    return {
        "pe": round(cap / ni, 1) if cap and ni and ni > 0 else None,
        "ps": round(cap / rev, 2) if cap and rev and rev > 0 else None,
        "fcf_yield": pct(fcf, cap),
        # No dividend line in a cash flow statement that exists means no dividend.
        "dividend_yield": pct(dividends, cap) if dividends else 0.0 if cap and f.get("ocf") is not None else None,
        "shareholder_yield": pct((dividends or 0) + (f.get("buybacks") or 0), cap)
        if cap and f.get("ocf") is not None else None,
        "revenue_growth": pct(rev - f["revenue_prev"], f["revenue_prev"])
        if rev is not None and f.get("revenue_prev") and f["revenue_prev"] > 0 else None,
        "gross_margin": pct(f.get("gross_profit"), rev) if rev and rev > 0 else None,
        "operating_margin": pct(f.get("operating_income"), rev) if rev and rev > 0 else None,
        "net_margin": pct(ni, rev) if rev and rev > 0 else None,
        "fcf_margin": pct(fcf, rev) if rev and rev > 0 else None,
        "roe": pct(ni, eq) if eq and eq > 0 else None,
        "debt_to_equity": round(f["long_term_debt"] / eq, 2) if eq and eq > 0 and f.get("long_term_debt") is not None
        else None,
        "payout_of_fcf": pct(dividends, fcf) if dividends and fcf and fcf > 0 else None,
    }
