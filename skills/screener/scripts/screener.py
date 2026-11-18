#!/usr/bin/env python3
"""Screen US stocks on price action and fundamentals, with free data only.

  screener.py run --preset quality
  screener.py run --universe sp400 --where "pe<15" --where "revenue_growth>10" --sort fcf_yield
  screener.py run --universe us --min-cap 10 --preset momentum --sector technology
  screener.py run --tickers AAPL MSFT NVDA --sort pe --asc
  screener.py presets | fields

Prices come from Yahoo Finance in one download. Fundamentals come from SEC filings for
the last full calendar year, through SEC's frames API. Market caps come from Nasdaq.
"""
import argparse
import math
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore import DeskError, frames, sec, universe  # noqa: E402
from deskcore.cli import run  # noqa: E402

FIELDS = {
    "market_cap_bn": "market cap, billions of dollars (Nasdaq, today)",
    "price": "last close",
    "return_1m": "price change over 1 month, %", "return_3m": "3 months, %", "return_6m": "6 months, %",
    "return_12m": "12 months, %",
    "momentum_12_1": "return from 12 months ago to 1 month ago, %; the standard momentum measure",
    "vs_sma50": "% above (+) or below (-) the 50-day average",
    "vs_sma200": "% above (+) or below (-) the 200-day average",
    "from_high": "% below the 52-week closing high (0 = at the high)",
    "from_low": "% above the 52-week closing low",
    "rsi": "14-day RSI",
    "volume_ratio": "average volume of the last 5 days over the last 50",
    "volatility": "annualised volatility over the last 3 months, %",
    "pe": "market cap over net income (loss makers left blank)",
    "ps": "market cap over revenue",
    "fcf_yield": "free cash flow (operating cash flow minus capex) over market cap, %",
    "dividend_yield": "dividends paid over market cap, %",
    "shareholder_yield": "dividends plus buybacks over market cap, %",
    "payout_of_fcf": "dividends as % of free cash flow",
    "revenue_growth": "revenue growth in the last full year, %",
    "gross_margin": "%", "operating_margin": "%", "net_margin": "%", "fcf_margin": "%",
    "roe": "net income over shareholders' equity, % (blank when equity is negative)",
    "debt_to_equity": "long-term debt over equity",
}
FUNDAMENTAL = {"pe", "ps", "fcf_yield", "dividend_yield", "shareholder_yield", "payout_of_fcf", "revenue_growth",
               "gross_margin", "operating_margin", "net_margin", "fcf_margin", "roe", "debt_to_equity"}

PRESETS = {
    "value": {"where": ["pe>0", "pe<=15", "fcf_yield>=6", "revenue_growth>=0", "debt_to_equity<=1.5"],
              "sort": "fcf_yield", "why": "cheap on earnings and cash flow, still growing, not heavily indebted"},
    "quality": {"where": ["roe>=15", "operating_margin>=15", "fcf_margin>=10", "debt_to_equity<=1"],
                "sort": "roe", "why": "high returns on equity and margins with modest debt"},
    "growth": {"where": ["revenue_growth>=20", "gross_margin>=40", "fcf_margin>=0"],
               "sort": "revenue_growth", "why": "fast revenue growth with healthy gross margins, not burning cash"},
    "garp": {"where": ["pe>0", "pe<=25", "revenue_growth>=10", "roe>=15"],
             "sort": "pe", "asc": True, "why": "growth at a reasonable price"},
    "dividend": {"where": ["dividend_yield>=3", "payout_of_fcf<=75", "revenue_growth>=0"],
                 "sort": "dividend_yield", "why": "high yield that free cash flow covers"},
    "momentum": {"where": ["vs_sma200>0", "vs_sma50>0", "from_high>=-10", "momentum_12_1>=20"],
                 "sort": "momentum_12_1", "why": "strong past-year trend, still near the high"},
    "breakout": {"where": ["from_high>=-2", "volume_ratio>=1.5", "vs_sma200>0"],
                 "sort": "volume_ratio", "why": "at or near a 52-week high on rising volume"},
    "pullback": {"where": ["vs_sma200>0", "rsi<=35", "momentum_12_1>=10"],
                 "sort": "rsi", "asc": True, "why": "an uptrend that has dipped to oversold"},
    "oversold": {"where": ["rsi<=30"], "sort": "rsi", "asc": True,
                 "why": "short-term oversold; often a falling knife without other filters"},
}
DEFAULT_COLUMNS = ["market_cap_bn", "price", "return_3m", "momentum_12_1", "vs_sma200", "pe", "fcf_yield",
                   "revenue_growth", "roe"]
OPS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b, "!=": lambda a, b: a != b,
       "<": lambda a, b: a < b, ">": lambda a, b: a > b, "=": lambda a, b: a == b}


def parse_where(text):
    m = re.fullmatch(r"\s*([a-z_0-9]+)\s*(<=|>=|!=|<|>|=)\s*(-?[\d.]+)\s*", text)
    if not m:
        raise DeskError(f"Cannot read the filter '{text}'. Write it like pe<15 or revenue_growth>=10.")
    field, op, val = m.group(1), m.group(2), float(m.group(3))
    if field not in FIELDS:
        raise DeskError(f"Unknown field '{field}'. Run 'screener.py fields' for the list.")
    return field, op, val


def build(rows):
    """One DataFrame: price metrics, market cap and SEC fundamentals for every row."""
    tickers = [r["ticker"] for r in rows]
    closes, volumes = universe.prices(tickers)
    pm = universe.price_metrics(closes, volumes)
    year, fund = frames.table()
    tmap = sec.ticker_map()
    records = []
    for r in rows:
        t = r["ticker"]
        if t not in pm.index or pd.isna(pm.at[t, "price"]) or pm.at[t, "days"] < 60:
            continue
        cap = r.get("market_cap") or None
        cik = tmap.get(t, [None])[0]
        f = fund.get(int(cik)) if cik else None
        rec = {"ticker": t, "name": r.get("name", ""), "sector": r.get("sector", ""),
               "market_cap_bn": round(cap / 1e9, 1) if cap else None, **pm.loc[t].to_dict()}
        rec.update(frames.metrics(f, cap) if f else {k: None for k in FUNDAMENTAL})
        rec["has_fundamentals"] = bool(f and f.get("net_income") is not None)
        records.append(rec)
    df = pd.DataFrame(records).set_index("ticker")
    return df, year, str(closes.index[-1].date())


def clean(v, nd=1):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    if isinstance(v, (bool,)) or hasattr(v, "dtype") and v.dtype == bool:
        return bool(v)
    return round(float(v), nd) if isinstance(v, (int, float)) or hasattr(v, "dtype") else v


def screen(universe_name="sp500", preset=None, where=(), sort=None, asc=None, top=25, sector=None,
           min_cap=0.0, tickers=None):
    conds = []
    why = None
    if preset:
        if preset not in PRESETS:
            raise DeskError(f"Unknown preset '{preset}'. Choose from: {', '.join(PRESETS)}.")
        p = PRESETS[preset]
        conds += [parse_where(w) for w in p["where"]]
        sort = sort or p["sort"]
        asc = p.get("asc", False) if asc is None else asc
        why = p["why"]
    conds += [parse_where(w) for w in where]
    if sort and sort not in FIELDS:
        raise DeskError(f"Unknown sort field '{sort}'. Run 'screener.py fields' for the list.")

    if tickers:
        lst = universe.listing()
        rows = [{"ticker": t.upper().replace(".", "-"),
                 **{k: (lst.get(t.upper().replace(".", "-")) or {}).get(k) for k in ("name", "sector", "market_cap")}}
                for t in tickers]
        label = "your list"
    else:
        rows = universe.members(universe_name, min_cap)
        label = universe.NAMES.get(universe_name.lower(), universe_name)
    if sector:
        rows = [r for r in rows if sector.lower() in (r.get("sector") or "").lower()
                or sector.lower() in (r.get("industry") or "").lower()]
        if not rows:
            raise DeskError(f"No stocks in the {label} match the sector '{sector}'.")

    df, year, prices_date = build(rows)
    scanned = len(df)
    mask = pd.Series(True, index=df.index)
    for field, op, val in conds:
        col = pd.to_numeric(df[field], errors="coerce")
        mask &= col.notna() & OPS[op](col, val)
    hits = df[mask]
    sort = sort or "market_cap_bn"
    hits = hits.sort_values(sort, ascending=bool(asc), na_position="last")

    cols = list(dict.fromkeys(["name", "sector"] + DEFAULT_COLUMNS + [c[0] for c in conds] + [sort]))
    out_rows = []
    for t, r in hits.head(top).iterrows():
        rec = {"ticker": t}
        for c in cols:
            v = r[c]
            rec[c] = v[:40] if isinstance(v, str) else clean(v, 2 if c in ("ps", "debt_to_equity", "volume_ratio") else 1)
        out_rows.append(rec)

    used_fund = any(c[0] in FUNDAMENTAL for c in conds) or sort in FUNDAMENTAL
    missing = int((~df["has_fundamentals"]).sum())
    notes = []
    if used_fund:
        notes.append(f"Fundamentals are from annual reports for calendar {year} (SEC). Market caps are today's, "
                     "so P/E and yields mix today's price with last year's results.")
        if missing:
            notes.append(f"{missing} of {scanned} stocks have no usable SEC figures (foreign filers, REIT or bank "
                         "formats, recent listings) and drop out of any fundamental filter.")
    if any(c[0] in ("pe", "roe", "net_margin", "operating_margin") for c in conds):
        notes.append("Banks and insurers report revenue and margins differently; read their ratios loosely.")
    if len(hits) > top:
        notes.append(f"Showing {top} of {len(hits)} matches, sorted by {sort}.")
    return {
        "universe": label, "scanned": scanned, "prices_to": prices_date,
        **({"fundamentals_year": year} if used_fund else {}),
        **({"preset": preset, "preset_means": why} if preset else {}),
        "filters": [f"{f}{o}{v:g}" for f, o, v in conds] + ([f"sector~{sector}"] if sector else []),
        "matches": int(len(hits)), "sorted_by": f"{sort} {'ascending' if asc else 'descending'}",
        "rows": out_rows, "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser(description="US stock screener on free data.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--universe", default="sp500", help="sp500 (default), sp400, sp600, or us (all US listings)")
    r.add_argument("--tickers", nargs="*", help="screen only these tickers instead of a universe")
    r.add_argument("--preset", help=", ".join(PRESETS))
    r.add_argument("--where", action="append", default=[], help='a filter such as "pe<15"; repeat for more')
    r.add_argument("--sector", help="keep one sector or industry (matches part of the name)")
    r.add_argument("--min-cap", type=float, default=0.0, help="minimum market cap in billions (us defaults to 2)")
    r.add_argument("--sort", help="field to sort by")
    order = r.add_mutually_exclusive_group()
    order.add_argument("--asc", dest="asc", action="store_true", default=None)
    order.add_argument("--desc", dest="asc", action="store_false")
    r.add_argument("--top", type=int, default=25)
    sub.add_parser("presets")
    sub.add_parser("fields")
    a = ap.parse_args()
    if a.cmd == "presets":
        return run(lambda: {k: {"filters": v["where"], "sort": v["sort"], "means": v["why"]} for k, v in PRESETS.items()})
    if a.cmd == "fields":
        return run(lambda: FIELDS)
    return run(lambda: screen(a.universe, a.preset, a.where, a.sort, a.asc, a.top, a.sector, a.min_cap, a.tickers))


if __name__ == "__main__":
    sys.exit(main())
