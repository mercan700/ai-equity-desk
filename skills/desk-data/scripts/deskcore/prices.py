"""Prices, company profile and financial statements from yfinance (free, unofficial)."""
import math

import pandas as pd

from . import DeskError, cache, markets

try:
    import yfinance as yf
except ImportError:  # setup skill explains how to install
    yf = None


def _yf():
    if yf is None:
        raise DeskError("yfinance is not installed. Run the desk-setup skill.")
    return yf


def _num(x, nd=2):
    """NaN-safe rounding for JSON output."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd)


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return _num((a / b - 1) * 100)


def load_history(sym, period="1y", interval="1d", kind="history"):
    """OHLCV DataFrame, cached as CSV. Other skills call this, Claude never reads the CSV."""
    path = cache.path_for(kind, f"{sym}:{period}:{interval}", "csv")
    if cache.fresh(path, kind):
        return pd.read_csv(path, index_col=0, parse_dates=True), path
    df = _yf().Ticker(sym).history(period=period, interval=interval, auto_adjust=True)
    if df is None or df.empty:
        raise DeskError(f"No price data for '{sym}'. Check the ticker and market.")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.to_csv(path)
    return df, path


def quote(ticker, market="US"):
    sym = markets.symbol(ticker, market)
    df, _ = load_history(sym, "1y", "1d", kind="quote")
    c = df["Close"].dropna()
    last = float(c.iloc[-1])

    def back(n):
        return float(c.iloc[-1 - n]) if len(c) > n else None

    year_start = c[c.index.year == c.index[-1].year]
    rets = c.pct_change().dropna()
    hi, lo = float(c.max()), float(c.min())
    return {
        "symbol": sym,
        "date": str(c.index[-1].date()),
        "close": _num(last),
        "change_pct": {
            "1d": _pct(last, back(1)),
            "1w": _pct(last, back(5)),
            "1m": _pct(last, back(21)),
            "3m": _pct(last, back(63)),
            "ytd": _pct(last, float(year_start.iloc[0])) if len(year_start) else None,
            "1y": _pct(last, float(c.iloc[0])),
        },
        "high_52w": _num(hi),
        "low_52w": _num(lo),
        "from_high_pct": _pct(last, hi),
        "vol_20d_annual_pct": _num(rets.tail(20).std() * math.sqrt(252) * 100),
        "avg_volume_20d": _num(df["Volume"].tail(20).mean(), 0),
    }


def history_summary(ticker, market="US", period="5y", interval="1d"):
    sym = markets.symbol(ticker, market)
    df, path = load_history(sym, period, interval)
    c = df["Close"].dropna()
    years = max((c.index[-1] - c.index[0]).days / 365.25, 1e-9)
    total = float(c.iloc[-1] / c.iloc[0])
    per_year = {"1d": 252, "1wk": 52, "1mo": 12}.get(interval, 252)
    dd = c / c.cummax() - 1
    return {
        "symbol": sym,
        "rows": len(c),
        "start": str(c.index[0].date()),
        "end": str(c.index[-1].date()),
        "total_return_pct": _num((total - 1) * 100),
        "cagr_pct": _num((total ** (1 / years) - 1) * 100),
        "annual_vol_pct": _num(c.pct_change().std() * math.sqrt(per_year) * 100),
        "max_drawdown_pct": _num(dd.min() * 100),
        "max_drawdown_date": str(dd.idxmin().date()),
        "csv": str(path),
    }


PROFILE_KEYS = {
    "longName": "name", "sector": "sector", "industry": "industry", "country": "country",
    "website": "website", "fullTimeEmployees": "employees", "currency": "currency",
    "marketCap": "market_cap", "enterpriseValue": "enterprise_value",
    "trailingPE": "pe_ttm", "forwardPE": "pe_forward", "priceToBook": "pb",
    "enterpriseToEbitda": "ev_ebitda", "dividendYield": "dividend_yield",
    "payoutRatio": "payout_ratio", "beta": "beta", "sharesOutstanding": "shares",
    "financialCurrency": "financial_currency",
}


def profile(ticker, market="US", summary_chars=600):
    sym = markets.symbol(ticker, market)
    cached = cache.get_json("profile", sym)
    if cached is None:
        info = _yf().Ticker(sym).info or {}
        if not info.get("longName") and not info.get("shortName"):
            raise DeskError(f"No profile found for '{sym}'.")
        cached = {v: info.get(k) for k, v in PROFILE_KEYS.items()}
        cached["name"] = cached["name"] or info.get("shortName")
        cached["summary"] = info.get("longBusinessSummary") or ""
        cached["symbol"] = sym
        cache.put_json("profile", sym, cached)
    out = dict(cached)
    if summary_chars and len(out["summary"]) > summary_chars:
        out["summary"] = out["summary"][:summary_chars].rsplit(" ", 1)[0] + " ..."
    for k in ("pe_ttm", "pe_forward", "pb", "ev_ebitda", "beta", "payout_ratio"):
        out[k] = _num(out.get(k))
    return out


# Statement rows we keep, in the order an analyst reads them. Values in millions.
ROWS = {
    "income": ["Total Revenue", "Gross Profit", "Operating Income", "EBITDA",
               "Net Income", "Diluted EPS", "Diluted Average Shares"],
    "balance": ["Total Assets", "Cash And Cash Equivalents", "Total Debt",
                "Stockholders Equity"],
    "cashflow": ["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"],
}


def _rows(df, names):
    out = {}
    if df is None or df.empty:
        return out
    for col in df.columns:
        period = str(getattr(col, "date", lambda: col)())
        rec = out.setdefault(period, {})
        for n in names:
            if n in df.index:
                v = df.at[n, col]
                if n == "Diluted EPS":
                    rec[n] = _num(v)
                else:
                    raw = _num(v, 0)
                    rec[n] = None if raw is None else round(raw / 1e6, 1)
    return out


def financials(ticker, market="US", quarterly=False, periods=4):
    sym = markets.symbol(ticker, market)
    key = f"{sym}:{'q' if quarterly else 'a'}"
    data = cache.get_json("financials", key)
    if data is None:
        t = _yf().Ticker(sym)
        if quarterly:
            frames = (t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow)
        else:
            frames = (t.income_stmt, t.balance_sheet, t.cashflow)
        data = {}
        for df, names in zip(frames, ROWS.values()):
            for period, rec in _rows(df, names).items():
                data.setdefault(period, {}).update(rec)
        if not data:
            raise DeskError(f"No financial statements for '{sym}'.")
        cache.put_json("financials", key, data)

    periods_sorted = sorted(data, reverse=True)[:periods]
    table = {p: data[p] for p in periods_sorted}
    ratios = {}
    for i, p in enumerate(periods_sorted):
        r = table[p]
        rev = r.get("Total Revenue")
        prev = table[periods_sorted[i + 1]].get("Total Revenue") if i + 1 < len(periods_sorted) else None
        eq = r.get("Stockholders Equity")
        ratios[p] = {
            "gross_margin_pct": _num(r["Gross Profit"] / rev * 100) if rev and r.get("Gross Profit") is not None else None,
            "operating_margin_pct": _num(r["Operating Income"] / rev * 100) if rev and r.get("Operating Income") is not None else None,
            "net_margin_pct": _num(r["Net Income"] / rev * 100) if rev and r.get("Net Income") is not None else None,
            "fcf_margin_pct": _num(r["Free Cash Flow"] / rev * 100) if rev and r.get("Free Cash Flow") is not None else None,
            "revenue_growth_pct": _pct(rev, prev),
            "roe_pct": _num(r["Net Income"] / eq * 100) if eq and r.get("Net Income") is not None else None,
            "debt_to_equity": _num(r["Total Debt"] / eq) if eq and r.get("Total Debt") is not None else None,
        }
    return {"symbol": sym, "units": "millions (EPS per share)",
            "basis": "quarterly" if quarterly else "annual",
            "statements": table, "ratios": ratios}


GLOBAL = {
    "S&P 500": "^GSPC", "Nasdaq": "^IXIC", "VIX": "^VIX", "US 10Y yield": "^TNX",
    "Dollar index": "DX-Y.NYB", "Brent oil": "BZ=F", "Gold": "GC=F",
    "EUR/USD": "EURUSD=X", "Bitcoin": "BTC-USD",
}


def global_snapshot():
    out = {}
    for name, sym in GLOBAL.items():
        try:
            q = quote(sym)
            out[name] = {"close": q["close"], **{k: q["change_pct"][k] for k in ("1d", "1m", "ytd")}}
        except DeskError as e:
            out[name] = {"error": str(e)}
    return out
