"""FRED macro data via the public CSV download (no API key needed)."""
import io

import pandas as pd
import requests

from . import DeskError, cache
from .prices import _num

# kind "rate": report change in percentage points. kind "index": report % change (e.g. inflation).
SERIES = {
    "FEDFUNDS": ("Fed funds rate", "rate"),
    "DGS10": ("US 10-year Treasury yield", "rate"),
    "DGS2": ("US 2-year Treasury yield", "rate"),
    "T10Y2Y": ("10Y minus 2Y spread", "rate"),
    "CPIAUCSL": ("US CPI (inflation index)", "index"),
    "PCEPILFE": ("Core PCE price index", "index"),
    "UNRATE": ("US unemployment rate", "rate"),
    "GDPC1": ("US real GDP", "index"),
    "BAMLH0A0HYM2": ("High-yield credit spread", "rate"),
}
DEFAULT = ["FEDFUNDS", "DGS10", "T10Y2Y", "CPIAUCSL", "UNRATE", "BAMLH0A0HYM2"]


def series(code):
    code = code.upper()
    path = cache.path_for("macro", code, "csv")
    if cache.fresh(path, "macro"):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}", timeout=20)
        if r.status_code != 200 or "<html" in r.text[:200].lower():
            raise DeskError(f"FRED series '{code}' not found.")
        df = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True, na_values=".")
        df.to_csv(path)
    s = pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()
    if s.empty:
        raise DeskError(f"FRED series '{code}' has no data.")
    return s


def snapshot(codes=None):
    out = {}
    for code in [c.upper() for c in (codes or DEFAULT)]:
        try:
            s = series(code)
        except (DeskError, requests.RequestException) as e:
            out[code] = {"error": str(e)}
            continue
        name, kind = SERIES.get(code, (code, "rate"))
        last_date = s.index[-1]
        year_ago = s[s.index <= last_date - pd.DateOffset(years=1)]
        prev = float(year_ago.iloc[-1]) if len(year_ago) else None
        last = float(s.iloc[-1])
        rec = {"name": name, "date": str(last_date.date()), "value": _num(last)}
        if prev is not None:
            if kind == "index":
                rec["yoy_pct"] = _num((last / prev - 1) * 100)
            else:
                rec["change_1y_pp"] = _num(last - prev)
        out[code] = rec
    return out
