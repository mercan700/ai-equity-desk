"""Returns in local currency, in US dollars and after inflation.

In a high-inflation market the local-currency return mostly measures inflation.
A BIST stock up 40% in a year when consumer prices rose 30% gained about 8% in
real terms, and its dollar return depends on how far the lira fell.
"""
import pandas as pd

from . import DeskError, bis, markets, prices
from .prices import _num

WINDOWS = (1, 3, 5)


def _annualize(total, years):
    return total if years == 1 else (1 + total) ** (1 / years) - 1


def real_returns(ticker, market="US"):
    mkt, minfo = markets.get(market)
    sym = markets.symbol(ticker, mkt)
    cur, country = minfo["currency"], minfo["country"]

    c = prices.load_history(sym, "10y", "1d")[0]["Close"].dropna()
    end = c.index[-1]
    fx = None
    if cur != "USD":
        fx = prices.load_history(f"USD{cur}=X", "10y", "1d")[0]["Close"].dropna()
    try:
        cpi = bis.cpi_index(country)
    except DeskError:
        cpi = None

    out = {"symbol": sym, "currency": cur, "end": str(end.date()),
           "note": "prices adjusted for dividends and splits, so returns include dividends"}
    if cpi is not None:
        out["inflation_source"] = f"BIS consumer prices, {country}, latest month {cpi.index[-1]}"
    for years in WINDOWS:
        start = end - pd.DateOffset(years=years)
        if c.index[0] > start + pd.Timedelta(days=10):
            continue  # not enough history for this window
        p0, p1 = float(c.asof(start)), float(c.iloc[-1])
        nominal = p1 / p0 - 1
        row = {f"{cur.lower()}_pct": _num(_annualize(nominal, years) * 100)}
        if fx is not None:
            f0, f1 = float(fx.asof(start)), float(fx.asof(end))
            row["usd_pct"] = _num(_annualize((p1 / f1) / (p0 / f0) - 1, years) * 100)
        if cpi is not None:
            # Inflation over the same number of months, ending at the latest CPI
            # month. CPI is published with a lag of one to two months, so this
            # window ends slightly earlier than the price window.
            base = cpi[cpi.index <= cpi.index[-1] - 12 * years]
            if len(base):
                inflation = float(cpi.iloc[-1]) / float(base.iloc[-1]) - 1
                row["inflation_pct"] = _num(_annualize(inflation, years) * 100)
                row["real_pct"] = _num(_annualize((1 + nominal) / (1 + inflation) - 1, years) * 100)
        key = "1y" if years == 1 else f"{years}y_annualized"
        out[key] = row
    if cpi is not None:
        lag = (pd.Period(end, freq="M") - cpi.index[-1]).n
        if lag > 0:
            out["inflation_lag_months"] = lag
    return out
