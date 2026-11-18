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


# ---------- backtest ----------

def _sma_signal(c, fast, slow):
    return (c.rolling(fast).mean() > c.rolling(slow).mean()) if fast else (c > c.rolling(slow).mean())


def _hold_until(enter, leave):
    """Long from an entry day until an exit day, as a 0/1 series."""
    state, out = 0, []
    for e, x in zip(enter, leave):
        if state == 0 and e:
            state = 1
        elif state == 1 and x:
            state = 0
        out.append(state)
    return pd.Series(out, index=enter.index)


def signals(df):
    """Position wanted at each close, one column per rule (1 = in the stock, 0 = in cash)."""
    c = df["Close"]
    r = rsi(c)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    return {
        "trend_200d": _sma_signal(c, None, 200).astype(int),
        "golden_cross_50_200": _sma_signal(c, 50, 200).astype(int),
        "macd_above_signal": (macd > macd.ewm(span=9, adjust=False).mean()).astype(int),
        "rsi_dip_buy": _hold_until(r < 30, r > 55),
        "breakout_55_20": _hold_until(c > c.shift(1).rolling(55).max(), c < c.shift(1).rolling(20).min()),
    }


RULE_TEXT = {
    "trend_200d": "in the stock while the close is above its 200-day average",
    "golden_cross_50_200": "in the stock while the 50-day average is above the 200-day",
    "macd_above_signal": "in the stock while MACD is above its signal line",
    "rsi_dip_buy": "buy when RSI(14) falls under 30, sell when it rises above 55",
    "breakout_55_20": "buy on a close above the 55-day high, sell on a close below the 20-day low",
}


def stats(daily, position=None):
    eq = (1 + daily).cumprod()
    years = len(daily) / 252
    vol = daily.std() * math.sqrt(252)
    out = {"cagr_pct": _num((eq.iloc[-1] ** (1 / years) - 1) * 100) if years > 0 else None,
           "max_drawdown_pct": _num((eq / eq.cummax() - 1).min() * 100),
           "volatility_pct": _num(vol * 100),
           "return_per_risk": _num(daily.mean() * 252 / vol) if vol else None}
    if position is not None:
        trips = []
        entry = None
        for d, p in position.items():
            if p and entry is None:
                entry = d
            elif not p and entry is not None:
                trips.append(float(eq.loc[d] / eq.loc[entry] - 1))
                entry = None
        out.update({"time_in_market_pct": _num(position.mean() * 100, 0), "trades": len(trips),
                    "win_rate_pct": _num(sum(t > 0 for t in trips) / len(trips) * 100, 0) if trips else None})
    return out


def backtest(ticker, market="US", years=10, cost_bps=10):
    """Each rule against buy-and-hold on dividend-adjusted closes. A signal at today's close
    is traded at the next close, and every switch in or out pays cost_bps."""
    mkt, _ = markets.get(market)
    sym = markets.symbol(ticker, mkt)
    df, _ = prices.load_history(sym, "max", "1d")
    df = df.dropna(subset=["Close"])
    warm = 260  # the 200-day rules need history before the test starts
    start = df.index[-1] - pd.DateOffset(years=years)
    if len(df) < warm + 252:
        raise DeskError(f"{sym} has {len(df)} trading days; a backtest needs at least four years.")
    if df.index[warm] > start:
        start = df.index[warm]
    ret = df["Close"].pct_change().fillna(0)
    test = df.index >= start
    hold = ret[test]
    halves = [hold.index[0], hold.index[len(hold) // 2], hold.index[-1]]
    out = {"symbol": sym, "from": str(hold.index[0].date()), "to": str(hold.index[-1].date()),
           "cost_per_switch_pct": cost_bps / 100,
           "buy_and_hold": {**stats(hold), "first_half": stats(hold[hold.index < halves[1]]),
                            "second_half": stats(hold[hold.index >= halves[1]])},
           "rules": {}}
    for name, sig in signals(df).items():
        pos = sig.shift(1).fillna(0)  # decided at the close, held from the next day
        daily = pos * ret - pos.diff().abs().fillna(0) * cost_bps / 10000
        d, p = daily[test], pos[test]
        first, second = d[d.index < halves[1]], d[d.index >= halves[1]]
        res = {"rule": RULE_TEXT[name], **stats(d, p),
               "first_half_cagr_pct": stats(first)["cagr_pct"], "second_half_cagr_pct": stats(second)["cagr_pct"]}
        bh = out["buy_and_hold"]
        res["beat_buy_and_hold"] = bool(res["cagr_pct"] is not None and bh["cagr_pct"] is not None
                                        and res["cagr_pct"] > bh["cagr_pct"])
        res["shallower_drawdown"] = bool(res["max_drawdown_pct"] > bh["max_drawdown_pct"])
        out["rules"][name] = res
    out["notes"] = ["Dividend-adjusted prices, no taxes, no slippage beyond the cost per switch. Cash earns nothing.",
                    "Five fixed rules tested on one stock. The best of five on past data usually does worse afterwards; "
                    "check that it held up in both halves."]
    return out


def main():
    ap = argparse.ArgumentParser(description="Technical picture of one stock.")
    ap.add_argument("ticker")
    ap.add_argument("--market", default=config.load().get("default_market", "US"), help="US or BIST")
    ap.add_argument("--backtest", action="store_true", help="test five classic rules against buy-and-hold")
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--cost", type=float, default=10, help="cost per switch in basis points (default 10)")
    a = ap.parse_args()
    if a.backtest:
        return run(lambda: backtest(a.ticker, a.market, a.years, a.cost))
    return run(lambda: analyze(a.ticker, a.market))

if __name__ == "__main__":
    sys.exit(main())
