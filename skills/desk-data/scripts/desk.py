#!/usr/bin/env python3
"""ai-equity-desk data CLI. Prints compact JSON so Claude reads summaries, not tables.

  desk.py quote AAPL
  desk.py quote THYAO --market BIST
  desk.py history MSFT --period 5y
  desk.py profile NVDA
  desk.py financials NVDA [--quarterly] [--periods 4]
  desk.py filings AAPL [--forms 10-K 8-K] [--limit 10]
  desk.py macro [DGS10 CPIAUCSL ...]
  desk.py global
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deskcore import config, macro, prices, sec  # noqa: E402
from deskcore.cli import run  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(prog="desk.py", description="ai-equity-desk data layer")
    p.add_argument("--pretty", action="store_true", help="indented JSON (more tokens)")
    sub = p.add_subparsers(dest="cmd", required=True)
    default_market = config.load().get("default_market", "US")

    def with_ticker(name, help_text):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("ticker")
        sp.add_argument("--market", default=default_market, help="US (default) or BIST")
        return sp

    with_ticker("quote", "price snapshot and returns")
    h = with_ticker("history", "long-run return, volatility, drawdown; saves CSV")
    h.add_argument("--period", default="5y")
    h.add_argument("--interval", default="1d", choices=["1d", "1wk", "1mo"])
    pr = with_ticker("profile", "company profile and valuation multiples")
    pr.add_argument("--summary-chars", type=int, default=600)
    f = with_ticker("financials", "key statement lines and ratios")
    f.add_argument("--quarterly", action="store_true")
    f.add_argument("--periods", type=int, default=4)
    fl = sub.add_parser("filings", help="SEC filings list (US only)")
    fl.add_argument("ticker")
    fl.add_argument("--forms", nargs="*", default=["10-K", "10-Q", "8-K"])
    fl.add_argument("--limit", type=int, default=10)
    m = sub.add_parser("macro", help="FRED macro snapshot")
    m.add_argument("codes", nargs="*")
    sub.add_parser("global", help="world markets snapshot")

    a = p.parse_args(argv)
    commands = {
        "quote": lambda: prices.quote(a.ticker, a.market),
        "history": lambda: prices.history_summary(a.ticker, a.market, a.period, a.interval),
        "profile": lambda: prices.profile(a.ticker, a.market, a.summary_chars),
        "financials": lambda: prices.financials(a.ticker, a.market, a.quarterly, a.periods),
        "filings": lambda: sec.filings(a.ticker, a.forms, a.limit),
        "macro": lambda: macro.snapshot(a.codes),
        "global": prices.global_snapshot,
    }
    return run(commands[a.cmd], a.pretty)


if __name__ == "__main__":
    sys.exit(main())
