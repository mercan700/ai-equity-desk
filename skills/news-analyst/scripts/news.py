#!/usr/bin/env python3
"""Recent news for one company, plus the company's own disclosures where we can get them.

  news.py AAPL
  news.py THYAO --market BIST --days 14
  news.py MSFT --days 60 --limit 40

Headlines come from Google News RSS and Yahoo Finance, filtered to items that name
the company, deduplicated and tagged by topic. For US companies the 8-K filings of
the same window are added: those are what the company itself reported.
"""
import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore.cli import friendly_error, run  # noqa: E402
from deskcore import config, markets, news, prices, sec  # noqa: E402


def report(ticker, market, days, limit):
    mkt, _ = markets.get(market)
    sym = markets.symbol(ticker, mkt)
    try:
        name = prices.profile(ticker, mkt).get("name") or ticker
    except Exception:  # noqa: BLE001  (the news can still be found by ticker)
        name = ticker
    out = {"symbol": sym, "name": name, "news": news.collect(ticker.upper(), sym, name, mkt, days, limit)}
    if mkt == "US":
        try:
            since = (date.today() - timedelta(days=days)).isoformat()
            out["company_filings_8k"] = sec.filings(ticker, forms=["8-K"], limit=10, since=since)["filings"]
        except Exception as e:  # noqa: BLE001
            out["company_filings_8k"] = {"error": friendly_error(e)}
    else:
        out["company_disclosures"] = ("KAP disclosures are not fetched yet; check "
                                      f"https://www.kap.org.tr for {ticker.upper()} before relying on a headline.")
    return out


def main():
    ap = argparse.ArgumentParser(description="Recent news for one company.")
    ap.add_argument("ticker")
    ap.add_argument("--market", default=config.load().get("default_market", "US"), help="US or BIST")
    ap.add_argument("--days", type=int, default=30, help="look-back window in days (default 30)")
    ap.add_argument("--limit", type=int, default=25, help="most items to print (default 25)")
    a = ap.parse_args()
    return run(lambda: report(a.ticker, a.market, max(1, min(a.days, 365)), max(1, a.limit)))


if __name__ == "__main__":
    sys.exit(main())
