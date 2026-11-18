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
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deskcore import DeskError, config, macro, prices, sec  # noqa: E402


def emit(obj, pretty=False):
    text = json.dumps(obj, ensure_ascii=False, default=str,
                      indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"))
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))


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
    try:
        if a.cmd == "quote":
            out = prices.quote(a.ticker, a.market)
        elif a.cmd == "history":
            out = prices.history_summary(a.ticker, a.market, a.period, a.interval)
        elif a.cmd == "profile":
            out = prices.profile(a.ticker, a.market, a.summary_chars)
        elif a.cmd == "financials":
            out = prices.financials(a.ticker, a.market, a.quarterly, a.periods)
        elif a.cmd == "filings":
            out = sec.filings(a.ticker, a.forms, a.limit)
        elif a.cmd == "macro":
            out = macro.snapshot(a.codes)
        else:
            out = prices.global_snapshot()
    except DeskError as e:
        emit({"error": str(e)})
        return 1
    except Exception as e:  # network hiccups, upstream format changes
        emit({"error": f"{type(e).__name__}: {e}", "hint": "Retry later or run desk-setup to diagnose."})
        return 1
    emit(out, a.pretty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
