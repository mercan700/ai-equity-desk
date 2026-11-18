#!/usr/bin/env python3
"""Technical picture of one stock from daily prices.

  technicals.py AAPL
  technicals.py THYAO --market BIST

Prints compact JSON: trend and moving averages, momentum (RSI, MACD),
volatility (ATR, Bollinger), support/resistance from swing points,
volume trend, and relative strength against the market benchmark.
"""
import argparse
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore.cli import friendly_error, run  # noqa: E402
from deskcore import DeskError, config, markets, prices, returns  # noqa: E402
from deskcore.prices import _num, _pct  # noqa: E402


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down)


def last_cross(fast, slow):
    """Date and direction of the most recent crossing of fast over slow."""
    diff = (fast - slow).dropna()
    sign = diff.apply(lambda x: 1 if x > 0 else -1)
    changes = sign[sign.diff().fillna(0) != 0]
    if changes.empty:
        return None
    d = changes.index[-1]
    return {"date": str(d.date()), "type": "bullish" if changes.iloc[-1] > 0 else "bearish",
            "bars_ago": int(len(diff) - diff.index.get_loc(d) - 1)}


def swing_levels(df, last, lookback=126, k=5, merge_pct=1.5):
    """Support/resistance from swing highs/lows in the last ~6 months, nearest first."""
    d = df.tail(lookback)
    win = 2 * k + 1
    highs = d["High"][d["High"] == d["High"].rolling(win, center=True).max()]
    lows = d["Low"][d["Low"] == d["Low"].rolling(win, center=True).min()]

    def merge(levels):
        out = []
        for lv in sorted(levels):
            if out and abs(lv / out[-1] - 1) * 100 < merge_pct:
                out[-1] = (out[-1] + lv) / 2
            else:
                out.append(lv)
        return out

    levels = merge(list(highs) + list(lows))
    res = sorted([x for x in levels if x > last * 1.003])[:3]
    sup = sorted([x for x in levels if x < last * 0.997], reverse=True)[:3]
    return ([{"level": _num(x), "distance_pct": _pct(x, last)} for x in sup],
            [{"level": _num(x), "distance_pct": _pct(x, last)} for x in res])


def analyze(ticker, market="US"):
    mkt, minfo = markets.get(market)
    sym = markets.symbol(ticker, mkt)
    df, _ = prices.load_history(sym, "2y", "1d")
    df = df.dropna(subset=["Close"])
    if len(df) < 210:
        raise DeskError(f"Only {len(df)} trading days of data for {sym}; need about 210 for the 200-day average.")
    c, last = df["Close"], float(df["Close"].iloc[-1])

    sma = {n: c.rolling(n).mean() for n in (20, 50, 200)}
    s20, s50, s200 = (float(sma[n].iloc[-1]) for n in (20, 50, 200))
    if last > s50 > s200:
        trend = "uptrend (price > 50d > 200d)"
    elif last < s50 < s200:
        trend = "downtrend (price < 50d < 200d)"
    else:
        trend = "mixed / range"
    slope200 = _pct(s200, float(sma[200].iloc[-21]))

    r = rsi(c)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()

    tr = pd.concat([df["High"] - df["Low"], (df["High"] - c.shift()).abs(), (df["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    std20 = float(c.rolling(20).std().iloc[-1])
    bb_up, bb_lo = s20 + 2 * std20, s20 - 2 * std20
    yr = c.tail(252)
    rets = c.pct_change()

    sup, res = swing_levels(df, last)

    # Stock return minus benchmark return over the same calendar dates.
    rel = {"benchmark": minfo["benchmark"]}
    try:
        bdf, _ = prices.load_history(minfo["benchmark"], "2y", "1d")
        b = bdf["Close"].dropna()
        end_b = b.asof(c.index[-1])
        for label, n in (("3m", 63), ("6m", 126), ("1y", 252)):
            if len(c) <= n:
                continue
            start = c.index[-1 - n]
            stock_ret = _pct(last, float(c.iloc[-1 - n]))
            bench_ret = _pct(float(end_b), float(b.asof(start)))
            if stock_ret is not None and bench_ret is not None:
                rel[label] = _num(stock_ret - bench_ret)
    except Exception as e:  # noqa: BLE001 - the rest of the analysis is still useful
        rel["error"] = f"benchmark unavailable: {e}"

    try:
        ret = returns.real_returns(ticker, mkt)
        ret = {k: v for k, v in ret.items() if k not in ("symbol", "end", "note")}
    except Exception as e:  # noqa: BLE001 - the chart reading is still useful without it
        ret = {"error": friendly_error(e)}

    vol20, vol60 = float(df["Volume"].tail(20).mean()), float(df["Volume"].tail(60).mean())
    return {
        "symbol": sym, "date": str(c.index[-1].date()), "close": _num(last),
        "trend": {
            "label": trend,
            "vs_sma20_pct": _pct(last, s20), "vs_sma50_pct": _pct(last, s50), "vs_sma200_pct": _pct(last, s200),
            "sma200_slope_1m_pct": slope200,
            "last_50_200_cross": last_cross(sma[50], sma[200]),
        },
        "momentum": {
            "rsi14": _num(r.iloc[-1], 1),
            "rsi14_5d_ago": _num(r.iloc[-6], 1),
            "macd_hist": _num(macd.iloc[-1] - signal.iloc[-1], 3),
            "macd_last_cross": last_cross(macd, signal),
        },
        "volatility": {
            "atr14_pct": _num(atr / last * 100),
            "bollinger_pct_b": _num((last - bb_lo) / (bb_up - bb_lo)) if bb_up != bb_lo else None,
            "annual_vol_1y_pct": _num(rets.tail(252).std() * math.sqrt(252) * 100),
            "max_drawdown_1y_pct": _num((yr / yr.cummax() - 1).min() * 100),
        },
        "levels": {
            "support": sup, "resistance": res,
            "high_52w": _num(yr.max()), "low_52w": _num(yr.min()),
            "from_52w_high_pct": _pct(last, float(yr.max())),
        },
        "volume": {"avg20_vs_avg60_pct": _pct(vol20, vol60)},
        "relative_strength_vs_benchmark_pp": rel,
        "returns": ret,
    }


def main():
    ap = argparse.ArgumentParser(description="Technical picture of one stock.")
    ap.add_argument("ticker")
    ap.add_argument("--market", default=config.load().get("default_market", "US"), help="US or BIST")
    a = ap.parse_args()
    return run(lambda: analyze(a.ticker, a.market))

if __name__ == "__main__":
    sys.exit(main())
