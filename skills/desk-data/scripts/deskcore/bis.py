"""Bank for International Settlements statistics: consumer prices and central bank
policy rates for most countries, free and without an API key.
https://data.bis.org
"""
import io

import pandas as pd
import requests

from . import DeskError, cache

BASE = "https://stats.bis.org/api/v1/data"


def _series(flow, key):
    path = cache.path_for("macro", f"bis:{flow}:{key}", "csv")
    if cache.fresh(path, "macro"):
        df = pd.read_csv(path)
    else:
        r = requests.get(f"{BASE}/{flow}/{key}?format=csv", timeout=30)
        if r.status_code != 200:
            raise DeskError(f"BIS series {flow}/{key} is not available (HTTP {r.status_code}).")
        df = pd.read_csv(io.StringIO(r.text))[["TIME_PERIOD", "OBS_VALUE"]]
        df.to_csv(path, index=False)
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values,
                  index=pd.PeriodIndex(df["TIME_PERIOD"], freq="M")).dropna().sort_index()
    if s.empty:
        raise DeskError(f"BIS series {flow}/{key} returned no data.")
    return s


def cpi_index(country):
    """Monthly consumer price index (2010 = 100), indexed by month."""
    return _series("WS_LONG_CPI", f"M.{country}.628")


def cpi_yoy(country):
    """Monthly consumer price inflation, % year on year."""
    return _series("WS_LONG_CPI", f"M.{country}.771")


def policy_rate(country):
    """Central bank policy rate, % (monthly, end of period)."""
    return _series("WS_CBPOL", f"M.{country}")
