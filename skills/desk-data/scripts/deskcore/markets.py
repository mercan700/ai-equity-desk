"""Market adapters. Add a market here and every skill can use it.

Only US has full coverage (prices + SEC filings + FRED macro).
BIST is prices-only for now; its own filings and macro come in a later version.
"""
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
    if t.startswith("^") or "=" in t or not sfx or t.endswith(sfx):
        return t
    return t + sfx
