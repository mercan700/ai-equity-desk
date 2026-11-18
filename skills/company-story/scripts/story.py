#!/usr/bin/env python3
"""The material for a company's story: who it is, where it came from, how the
business and the share price have developed.

  story.py AAPL
  story.py THYAO --market BIST
  story.py EREGL --market BIST --wiki-title Erdemir

Prints compact JSON with four parts, each of which can fail on its own without
sinking the others: profile, wikipedia, sec (US only) and market_history.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore.cli import friendly_error, run  # noqa: E402
from deskcore import config, markets, prices, sec, verify, wiki  # noqa: E402
from deskcore.prices import _num  # noqa: E402

FINANCE_YEARS = 15


def drawdowns(close, top=3):
    """The deepest peak-to-trough falls, each with its peak, trough and recovery date."""
    episodes, peak_i, trough_i = [], 0, 0
    values, dates = close.values, close.index
    for i in range(1, len(values)):
        if values[i] >= values[peak_i]:
            if trough_i > peak_i:
                episodes.append((peak_i, trough_i, i))
            peak_i = trough_i = i
        elif values[i] < values[trough_i] or trough_i < peak_i:
            trough_i = i
    if trough_i > peak_i:
        episodes.append((peak_i, trough_i, None))
    rows = []
    for p, t, r in episodes:
        depth = values[t] / values[p] - 1
        rows.append({
            "fall_pct": _num(depth * 100),
            "peak": str(dates[p].date()), "trough": str(dates[t].date()),
            "recovered": str(dates[r].date()) if r is not None else "not yet",
            "months_to_recover": _num((dates[r] - dates[t]).days / 30.44, 0) if r is not None else None,
        })
    return sorted(rows, key=lambda x: x["fall_pct"])[:top]


def bad_jumps(close):
    """Dates of one-day moves no listed stock really makes. Apple's -52% on 2000-09-29 was
    real, so the bar is -75% / +300%. What trips it is Yahoo's data: unadjusted splits or
    bonus issues, and BIST prices around the 2005 lira redenomination."""
    r = close.pct_change().dropna()
    return r[(r < -0.75) | (r > 3.0)]


def market_history(sym):
    c = prices.load_history(sym, "max", "1d")[0]["Close"].dropna()
    c = c[c > 0]
    out = {}
    bad = bad_jumps(c)
    if len(bad):
        c = c[c.index >= bad.index[-1]]
        out["data_warning"] = (
            f"Price history before {bad.index[-1].date()} was dropped: one-day moves of "
            + ", ".join(f"{v * 100:+.0f}% on {d.date()}" for d, v in bad.tail(3).items())
            + " are data errors, not trading.")
    years = (c.index[-1] - c.index[0]).days / 365.25
    yearly = c.groupby(c.index.year).last()
    yr_ret = (yearly / yearly.shift(1) - 1).dropna() * 100
    full_years = yr_ret[(yr_ret.index > c.index[0].year) & (yr_ret.index < c.index[-1].year)]
    out.update({
        "first_price_date": str(c.index[0].date()),
        "years_of_data": _num(years, 1),
        "total_return_multiple": _num(c.iloc[-1] / c.iloc[0], 1),
        "cagr_pct": _num(((c.iloc[-1] / c.iloc[0]) ** (1 / years) - 1) * 100) if years > 1 else None,
        "deepest_falls": drawdowns(c),
        "best_years": {str(k): _num(v) for k, v in full_years.nlargest(3).items()},
        "worst_years": {str(k): _num(v) for k, v in full_years.nsmallest(3).items()},
        "note": "Yahoo's price history may start after the actual listing date; returns include dividends.",
    })
    return out


def sec_part(ticker):
    meta = sec.submissions(ticker)
    annual = verify.sec_annuals(ticker)
    out = {
        "registered_name": meta["company"],
        "former_names": meta.get("former_names", []),
        "state_of_incorporation": meta.get("state_of_incorporation"),
        "fiscal_year_end": meta.get("fiscal_year_end"),
        "industry_code": meta.get("sic"),
        "first_sec_filing": meta.get("first_filing"),
    }
    if "_reason" not in annual:
        def by_year(row, scale=1e6):
            vals = annual.get(row, {})
            return {k[:4]: _num(v / scale, 0) for k, v in sorted(vals.items())[-FINANCE_YEARS:]}
        out["annual_millions"] = {"revenue": by_year("Total Revenue"), "net_income": by_year("Net Income")}
        out["annual_source"] = "10-K filings, SEC XBRL company facts"
    else:
        out["annual_millions"] = annual["_reason"]
    return out


def story(ticker, market, wiki_title=None):
    mkt, _ = markets.get(market)
    sym = markets.symbol(ticker, mkt)
    out = {"symbol": sym}

    try:
        p = prices.profile(ticker, mkt, summary_chars=1500)
        out["profile"] = {k: p.get(k) for k in ("name", "sector", "industry", "country",
                                                 "employees", "website", "summary")}
        name = p.get("name") or ticker
    except Exception as e:  # noqa: BLE001
        out["profile"] = {"error": friendly_error(e)}
        name = ticker

    langs = ("en", "tr") if mkt == "BIST" else ("en",)
    try:
        out["wikipedia"] = wiki.company(name, langs, title=wiki_title, ticker=ticker.upper(), market=mkt)
    except Exception as e:  # noqa: BLE001
        out["wikipedia"] = {"error": friendly_error(e),
                            "hint": "If you know the article title, rerun with --wiki-title."}

    if mkt == "US":
        try:
            out["sec"] = sec_part(ticker)
        except Exception as e:  # noqa: BLE001
            out["sec"] = {"error": friendly_error(e)}
    else:
        try:
            fin = prices.financials(ticker, mkt, periods=5)
            out["annual_millions"] = {
                "currency": p.get("financial_currency") if "error" not in out["profile"] else None,
                "revenue": {k[:4]: v.get("Total Revenue") for k, v in sorted(fin["statements"].items())},
                "net_income": {k[:4]: v.get("Net Income") for k, v in sorted(fin["statements"].items())},
                "source": "yfinance (about 4 years; KAP history is not supported yet)",
            }
        except Exception as e:  # noqa: BLE001
            out["annual_millions"] = {"error": friendly_error(e)}

    try:
        out["market_history"] = market_history(sym)
    except Exception as e:  # noqa: BLE001
        out["market_history"] = {"error": friendly_error(e)}
    return out


def main():
    ap = argparse.ArgumentParser(description="Material for a company's story.")
    ap.add_argument("ticker")
    ap.add_argument("--market", default=config.load().get("default_market", "US"), help="US or BIST")
    ap.add_argument("--wiki-title", help="exact Wikipedia article title, when the search picks the wrong one")
    a = ap.parse_args()
    return run(lambda: story(a.ticker, a.market, a.wiki_title))


if __name__ == "__main__":
    sys.exit(main())
