#!/usr/bin/env python3
"""The state of the US stock market, and what is on the calendar.

  market.py regime          trend, distribution days, breadth, volatility, credit, sector leadership
  market.py calendar        US economic releases, Fed meetings and large earnings for the next days
  market.py calendar --days 14 --tickers NVDA AAPL

Every signal in `regime` is a fixed rule with its threshold in the output, so the
reading can be checked by hand. Nothing here forecasts the market.
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore import DeskError, cache, config, macro, prices, universe  # noqa: E402
from deskcore.cli import run  # noqa: E402
from deskcore.prices import _num  # noqa: E402

SECTORS = {"XLK": "Technology", "XLC": "Communication", "XLY": "Consumer discretionary", "XLF": "Financials",
           "XLI": "Industrials", "XLB": "Materials", "XLE": "Energy", "XLP": "Consumer staples",
           "XLV": "Health care", "XLU": "Utilities", "XLRE": "Real estate"}
DEFENSIVE, CYCLICAL = ["XLP", "XLU", "XLV"], ["XLY", "XLI", "XLF", "XLK"]


def closes_of(sym, period="2y"):
    return prices.load_history(sym, period, "1d")[0]


# ---------- the signals ----------

def trend(sym="^GSPC"):
    c = closes_of(sym)["Close"].dropna()
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    last = float(c.iloc[-1])
    rising = bool(s200.iloc[-1] > s200.iloc[-21])
    above = last > s200.iloc[-1]
    return {"close": _num(last), "vs_sma50_pct": _num((last / s50.iloc[-1] - 1) * 100),
            "vs_sma200_pct": _num((last / s200.iloc[-1] - 1) * 100), "sma200_rising": rising,
            "from_high_pct": _num((last / c.tail(252).max() - 1) * 100),
            "signal": "risk_on" if above and rising else "risk_off" if not above and not rising else "neutral"}


def distribution_days(df, window=25):
    """William O'Neil's distribution days: the index closes down at least 0.2% on higher
    volume than the day before. A day drops out after 25 sessions, or once the index
    closes 5% above that day's close."""
    df = df.dropna(subset=["Close", "Volume"])
    df = df[df["Volume"] > 0]
    c, v = df["Close"], df["Volume"]
    chg = c.pct_change()
    recent = df.index[-window:]
    days = []
    for d in recent:
        i = df.index.get_loc(d)
        if i == 0 or chg.iloc[i] > -0.002 or v.iloc[i] <= v.iloc[i - 1]:
            continue
        if (c.iloc[i + 1:] >= c.iloc[i] * 1.05).any():
            continue
        days.append(str(d.date()))
    return days


def dd_signal(n):
    return "risk_off" if n >= 5 else "risk_on" if n <= 2 else "neutral"


def breadth():
    rows = universe.members("sp500")
    closes, _ = universe.prices([r["ticker"] for r in rows])
    c = closes.ffill(limit=3)
    valid = c.iloc[-1].notna()
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    above50 = (c.iloc[-1] > s50.iloc[-1])[valid].mean() * 100
    above200 = (c.iloc[-1] > s200.iloc[-1])[valid].mean() * 100
    month_ago = (c.iloc[-22] > s200.iloc[-22])[valid].mean() * 100
    hi, lo = c.tail(252).max(), c.tail(252).min()
    new_hi = int((c.iloc[-1] >= hi)[valid].sum())
    new_lo = int((c.iloc[-1] <= lo)[valid].sum())
    adv = c.iloc[-1] > c.iloc[-2]
    sig = "risk_on" if above200 >= 60 else "risk_off" if above200 <= 40 else "neutral"
    hl = "risk_on" if new_hi > new_lo and new_hi >= 10 else "risk_off" if new_lo > new_hi and new_lo >= 10 else "neutral"
    return {"stocks": int(valid.sum()), "date": str(c.index[-1].date()),
            "pct_above_50d": _num(above50, 0), "pct_above_200d": _num(above200, 0),
            "pct_above_200d_month_ago": _num(month_ago, 0),
            "new_52w_highs": new_hi, "new_52w_lows": new_lo,
            "advancers_last_day_pct": _num(adv[valid].mean() * 100, 0),
            "signal": sig, "highs_lows_signal": hl}


def volatility():
    vix = closes_of("^VIX")["Close"].dropna()
    v3 = closes_of("^VIX3M")["Close"].dropna()
    last, ratio = float(vix.iloc[-1]), float(vix.iloc[-1] / v3.iloc[-1])
    pctile = (vix.tail(252) <= last).mean() * 100
    sig = "risk_off" if ratio > 1 or last >= 30 else "risk_on" if last < 20 and ratio < 0.9 else "neutral"
    return {"vix": _num(last), "vix_1y_percentile": _num(pctile, 0), "vix_to_vix3m": _num(ratio),
            "reading": "near-term fear above longer-term (inverted)" if ratio > 1 else "normal upward slope",
            "signal": sig}


def credit():
    s = macro.series("BAMLH0A0HYM2")
    last = float(s.iloc[-1])
    month = s[s.index <= s.index[-1] - pd.Timedelta(days=30)]
    chg = last - float(month.iloc[-1]) if len(month) else None
    sig = ("risk_off" if last >= 5 or (chg is not None and chg >= 0.5) else
           "risk_on" if last < 4 and (chg is None or chg <= 0) else "neutral")
    curve = macro.series("T10Y2Y")
    return {"high_yield_spread_pct": _num(last), "change_1m_pp": _num(chg), "date": str(s.index[-1].date()),
            "yield_curve_10y_2y_pp": _num(float(curve.iloc[-1])), "signal": sig}


def sectors():
    spy = closes_of("SPY")["Close"].dropna()
    out = []
    for sym, name in SECTORS.items():
        c = closes_of(sym)["Close"].dropna()
        r1 = (c.iloc[-1] / c.iloc[-22] - 1) * 100
        r3 = (c.iloc[-1] / c.iloc[-64] - 1) * 100
        s3 = (spy.iloc[-1] / spy.iloc[-64] - 1) * 100
        out.append({"etf": sym, "sector": name, "return_1m_pct": _num(r1), "return_3m_pct": _num(r3),
                    "vs_sp500_3m_pp": _num(r3 - s3)})
    out.sort(key=lambda x: -x["vs_sp500_3m_pp"])
    by = {x["etf"]: x["return_3m_pct"] for x in out}
    gap = sum(by[s] for s in DEFENSIVE) / 3 - sum(by[s] for s in CYCLICAL) / 4
    sig = "risk_off" if gap > 3 else "risk_on" if gap < -3 else "neutral"
    return {"ranked_3m": out, "defensive_minus_cyclical_3m_pp": _num(gap), "signal": sig}


RULES = {
    "trend": "S&P 500 above a rising 200-day average is risk-on; below a falling one is risk-off",
    "distribution_days": "5 or more in 25 sessions on SPY is risk-off; 2 or fewer is risk-on",
    "breadth": "60% or more of S&P 500 stocks above their 200-day average is risk-on; 40% or less is risk-off",
    "new_highs_lows": "more new 52-week highs than lows (at least 10) is risk-on, the reverse is risk-off",
    "volatility": "VIX above VIX3M or VIX at 30+ is risk-off; VIX under 20 with VIX/VIX3M under 0.9 is risk-on",
    "credit": "high-yield spread at 5%+ or up 0.5 points in a month is risk-off; under 4% and not rising is risk-on",
    "sector_leadership": "defensive sectors beating cyclicals by 3+ points over 3 months is risk-off; the reverse is risk-on",
}


def regime():
    out, signals = {}, {}

    def attempt(name, fn):
        try:
            out[name] = fn()
        except (DeskError, requests.RequestException, KeyError, IndexError) as e:
            out[name] = {"error": str(e)}

    attempt("sp500_trend", trend)
    attempt("nasdaq_trend", lambda: trend("^IXIC"))
    for sym in ("SPY", "QQQ"):
        attempt(f"distribution_days_{sym}", lambda s=sym: (lambda d: {"count_25_sessions": len(d), "dates": d,
                                                                      "signal": dd_signal(len(d))})(
            distribution_days(closes_of(s, "1y"))))
    attempt("breadth", breadth)
    attempt("volatility", volatility)
    attempt("credit", credit)
    attempt("sectors", sectors)

    pick = {"trend": ("sp500_trend", "signal"), "distribution_days": ("distribution_days_SPY", "signal"),
            "breadth": ("breadth", "signal"), "new_highs_lows": ("breadth", "highs_lows_signal"),
            "volatility": ("volatility", "signal"), "credit": ("credit", "signal"),
            "sector_leadership": ("sectors", "signal")}
    for k, (sec, field) in pick.items():
        signals[k] = out.get(sec, {}).get(field, "missing")
    on = sum(v == "risk_on" for v in signals.values())
    off = sum(v == "risk_off" for v in signals.values())
    posture = "risk-on" if on >= 5 and off <= 1 else "risk-off" if off >= 4 else "mixed"
    return {"as_of": date.today().isoformat(), "posture": posture, "risk_on": on, "risk_off": off,
            "signals": signals, "rules": RULES, **out,
            "notes": ["Posture is a count of seven rules, not a forecast. Markets often stay in one state for "
                      "months and turn without warning.",
                      "Risk-on needs 5 of 7 with at most one risk-off; risk-off needs 4 of 7."]}


# ---------- calendar ----------

IMPORTANT = re.compile(
    r"\bCPI\b|Core CPI|\bPPI\b|Nonfarm|Unemployment Rate|Average Hourly|\bGDP\b|PCE|Retail Sales|ISM|JOLTS|"
    r"Initial Jobless|Fed Interest Rate|FOMC|Fed Chair|Powell|Michigan Consumer Sentiment|CB Consumer Confidence|"
    r"Durable Goods|Housing Starts|Existing Home Sales|New Home Sales|Industrial Production|S&P Global.*PMI", re.I)
NASDAQ = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _nasdaq(kind, day):
    key = f"{kind}:{day}"
    data = cache.get_json("calendar", key)
    if data is None:
        r = requests.get(f"https://api.nasdaq.com/api/calendar/{kind}", params={"date": day}, headers=NASDAQ,
                         timeout=30)
        r.raise_for_status()
        data = ((r.json() or {}).get("data") or {}).get("rows") or []
        cache.put_json("calendar", key, data)
    return data


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def parse_fomc(html):
    """Decision days (the last day of each meeting) from the Fed's calendar page."""
    out = []
    parts = re.split(r"(\d{4}) FOMC Meetings", html)
    for i in range(1, len(parts) - 1, 2):
        year = int(parts[i])
        for month, days in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?'
                                      r'fomc-meeting__date[^>]*>([^<]+)<', parts[i + 1], re.S):
            if "notation" in days or "unscheduled" in days.lower():
                continue
            m = month.strip().lower().split("/")[-1]
            m = next((v for k, v in MONTHS.items() if k.startswith(m[:3])), None)
            d = re.findall(r"\d+", days)
            if m and d:
                out.append({"date": date(year, m, int(d[-1])).isoformat(), "projections": "*" in days})
    return sorted({x["date"]: x for x in out}.values(), key=lambda x: x["date"])


def fomc():
    data = cache.get_json("calendar", "fomc")
    if data is None:
        r = requests.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", timeout=30)
        r.raise_for_status()
        data = parse_fomc(r.text)
        cache.put_json("calendar", "fomc", data)
    return data


def _blank(v):
    v = (v or "").replace("&nbsp;", "").strip()
    return v or None


def _cap(text):
    try:
        return float(re.sub(r"[^\d.]", "", text or "") or 0)
    except ValueError:
        return 0.0


def portfolio_tickers():
    p = config.HOME / "portfolio.json"
    if not p.exists():
        return []
    try:
        pos = json.loads(p.read_text(encoding="utf-8")).get("positions", {})
    except ValueError:
        return []
    return [v["ticker"] for v in pos.values() if v.get("market") == "US"]


def calendar(days=7, tickers=None, min_cap_bn=100):
    start = date.today()
    watch = {t.upper() for t in (tickers or [])} | set(portfolio_tickers())
    econ, earnings, mine = [], [], []
    errors = []
    for i in range(days + 1):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ds = d.isoformat()
        try:
            for r in _nasdaq("economicevents", ds):
                if r.get("country") == "United States" and IMPORTANT.search(r.get("eventName", "")):
                    val = {k: _blank(r.get(k)) for k in ("consensus", "previous", "actual")}
                    econ.append({"date": ds, "time_et": r.get("gmt"), "event": r.get("eventName"),
                                 **{k: v for k, v in val.items() if v is not None}})
        except (requests.RequestException, ValueError) as e:
            errors.append(f"economic calendar {ds}: {e}")
        try:
            for r in _nasdaq("earnings", ds):
                sym = (r.get("symbol") or "").upper()
                cap = _cap(r.get("marketCap"))
                row = {"date": ds, "ticker": sym, "name": (r.get("name") or "")[:40],
                       "when": {"time-pre-market": "before open", "time-after-hours": "after close"}.get(
                           r.get("time"), "time not given"),
                       "eps_forecast": r.get("epsForecast") or None, "market_cap_bn": _num(cap / 1e9, 0)}
                if sym in watch:
                    mine.append(row)
                if cap >= min_cap_bn * 1e9:
                    earnings.append(row)
        except (requests.RequestException, ValueError) as e:
            errors.append(f"earnings calendar {ds}: {e}")
    end = (start + timedelta(days=days)).isoformat()
    try:
        meetings = fomc()
        fed = [m for m in meetings if start.isoformat() <= m["date"] <= end]
        nxt = next((m for m in meetings if m["date"] >= start.isoformat()), None)
    except (requests.RequestException, ValueError) as e:
        fed, nxt = [], None
        errors.append(f"Fed calendar: {e}")
    # Next earnings date from Yahoo for watched tickers Nasdaq did not list in the window.
    later = []
    for t in sorted(watch - {m["ticker"] for m in mine}):
        try:
            cal = prices._yf().Ticker(t).calendar or {}
            ed = cal.get("Earnings Date")
            if ed:
                later.append({"ticker": t, "next_earnings": str(ed[0] if isinstance(ed, list) else ed)})
        except Exception:  # noqa: BLE001 - optional detail
            pass
    out = {"from": start.isoformat(), "to": end,
           "fed_decisions_in_window": fed, "next_fed_decision": nxt,
           "us_releases": econ,
           "your_stocks_reporting": mine, **({"your_stocks_next_earnings": later} if later else {}),
           f"earnings_over_{min_cap_bn}bn": sorted(earnings, key=lambda x: -(x["market_cap_bn"] or 0))[:25],
           "notes": ["Times are US Eastern. Consensus figures are from Nasdaq's calendar and can change.",
                     "Fed decisions marked projections=true come with new economic projections and usually move "
                     "markets more."]}
    if errors:
        out["errors"] = errors
    return out


def main():
    ap = argparse.ArgumentParser(description="US market regime and calendar.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("regime")
    c = sub.add_parser("calendar")
    c.add_argument("--days", type=int, default=7)
    c.add_argument("--tickers", nargs="*", default=[])
    c.add_argument("--min-cap", type=float, default=100, help="list earnings of companies above this size, $bn")
    a = ap.parse_args()
    if a.cmd == "regime":
        return run(regime)
    return run(lambda: calendar(min(a.days, 30), a.tickers, a.min_cap))


if __name__ == "__main__":
    sys.exit(main())
