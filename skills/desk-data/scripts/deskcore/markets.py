"""Market adapters. A market added here is available to every skill.

US: prices, statements, SEC filings and FRED macro.
BIST: prices and statements. KAP filings and Turkish macro are not wired up yet.
"""
import re

from . import DeskError

MARKETS = {
    "US": {"suffix": "", "currency": "USD", "benchmark": "^GSPC", "filings": "sec"},
    "BIST": {"suffix": ".IS", "currency": "TRY", "benchmark": "XU100.IS", "filings": None},
}


def get(market):
    m = (market or "US").upper()
    if m not in MARKETS:
        raise DeskError(f"Unknown market '{market}'. Supported: {', '.join(MARKETS)}")
    return m, MARKETS[m]


def symbol(ticker, market="US"):
    """Turn a user ticker into the yfinance symbol, e.g. THYAO + BIST -> THYAO.IS."""
    t = ticker.strip().upper()
    if not t:
        raise DeskError("Empty ticker.")
    _, m = get(market)
    sfx = m["suffix"]
    if t.startswith("^") or "=" in t:
        return t
    if not sfx:
        # Yahoo writes share classes with a dash (BRK.B -> BRK-B), but other
        # symbols such as DX-Y.NYB keep their dot.
        return re.sub(r"^([A-Z]+)\.([A-Z])$", r"\1-\2", t)
    return t if t.endswith(sfx) else t + sfx
