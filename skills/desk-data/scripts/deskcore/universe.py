"""Lists of US stocks to scan, and their daily prices in one download.

Index members come from Wikipedia's S&P 500, 400 and 600 tables. Market caps come
from Nasdaq's public stock list, which covers every US-listed company in one call.
"""
import hashlib
import re

import pandas as pd
import requests

from . import DeskError, cache
from .prices import _yf

WIKI_PAGES = {
    "sp500": "List_of_S%26P_500_companies",
    "sp400": "List_of_S%26P_400_companies",
    "sp600": "List_of_S%26P_600_companies",
}
NAMES = {"sp500": "S&P 500", "sp400": "S&P MidCap 400", "sp600": "S&P SmallCap 600",
         "us": "all US-listed stocks above the size floor"}
WIKI_UA = {"User-Agent": "stock-trader-skills/0.7 (personal stock research tool)"}
WEB_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _clean(cell):
    cell = re.sub(r'^\s*style="[^"]*"\s*\|', "", cell)
    cell = re.sub(r"\{\{Anchor\|[^}]*\}\}", "", cell)
    cell = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", cell)
    cell = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", cell)
    cell = re.sub(r"<[^>]+>|\{\{[^}]*\}\}", "", cell)
    return cell.strip()


def parse_wiki_table(wikitext):
    """Rows of the first 'constituents' table: ticker, name, sector, industry."""
    start = wikitext.find('id="constituents"')
    if start < 0:
        start = wikitext.find("{|")
    body = wikitext[start:wikitext.find("\n|}", start)]
    out = []
    for block in body.split("\n|-")[1:]:
        m = re.search(r"Symbol\|([^}|]+)", block)
        if not m:
            continue
        cells = []
        for line in block.strip("\n").split("\n"):
            if line.startswith("!") or not line.startswith("|"):
                continue
            cells += [c for c in line.lstrip("|").split("||")]
        cells = [_clean(c) for c in cells]
        if len(cells) < 3:
            continue
        out.append({"ticker": m.group(1).strip().upper().replace(".", "-"),
                    "name": cells[1], "sector": cells[2], "industry": cells[3] if len(cells) > 3 else ""})
    return out


def index_members(name):
    name = name.lower()
    if name not in WIKI_PAGES:
        raise DeskError(f"Unknown index '{name}'. Use one of: {', '.join(list(WIKI_PAGES) + ['us'])}.")
    rows = cache.get_json("universe", name)
    if rows is None:
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=WIKI_UA, timeout=30, params={
            "action": "parse", "page": WIKI_PAGES[name].replace("%26", "&"), "prop": "wikitext", "format": "json"})
        r.raise_for_status()
        rows = parse_wiki_table(r.json()["parse"]["wikitext"]["*"])
        if len(rows) < 300:
            raise DeskError(f"Could not read the {NAMES[name]} member list from Wikipedia (got {len(rows)} rows).")
        cache.put_json("universe", name, rows)
    return rows


def listing():
    """{ticker: {name, market_cap, sector, industry, country}} for every US-listed stock (Nasdaq)."""
    data = cache.get_json("listing", "nasdaq")
    if data is None:
        r = requests.get("https://api.nasdaq.com/api/screener/stocks", headers=WEB_UA, timeout=60,
                         params={"tableonly": "true", "download": "true"})
        r.raise_for_status()
        rows = (r.json().get("data") or {}).get("rows") or []
        if len(rows) < 3000:
            raise DeskError("Nasdaq's stock list came back short. Try again later.")
        data = {}
        for x in rows:
            sym = x["symbol"].strip().upper().replace("/", "-")
            try:
                cap = float(x.get("marketCap") or 0)
            except ValueError:
                cap = 0.0
            data[sym] = {"name": x.get("name", ""), "market_cap": cap, "sector": x.get("sector") or "",
                         "industry": x.get("industry") or "", "country": x.get("country") or ""}
        cache.put_json("listing", "nasdaq", data)
    return data


SKIP_NAME = re.compile(r"\bwarrants?\b|\brights?\b|\bunits?\b|preferred|depositary shares? representing|"
                       r"notes due|\d%|trust certificate", re.I)


def members(name, min_cap_bn=0.0):
    """Stocks in a universe with market cap attached. 'us' is every US listing above min_cap_bn
    (default 2 billion), without preferreds, warrants and units."""
    lst = listing()
    if name.lower() == "us":
        floor = (min_cap_bn or 2.0) * 1e9
        rows = [{"ticker": t, "name": v["name"], "sector": v["sector"], "industry": v["industry"],
                 "market_cap": v["market_cap"]}
                for t, v in lst.items() if v["market_cap"] >= floor and not SKIP_NAME.search(v["name"])
                and re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", t)]
    else:
        rows = []
        for r in index_members(name):
            cap = (lst.get(r["ticker"]) or {}).get("market_cap")
            if min_cap_bn and (cap or 0) < min_cap_bn * 1e9:
                continue
            rows.append({**r, "market_cap": cap})
    return rows


def prices(tickers, period="1y"):
    """Daily closes and volumes for many tickers in one download, cached for 12 hours.
    Returns (closes, volumes) as DataFrames with one column per ticker."""
    tickers = sorted(set(tickers))
    if not tickers:
        raise DeskError("No tickers to download.")
    key = hashlib.sha1(",".join(tickers).encode()).hexdigest()[:16] + ":" + period
    pc, pv = cache.path_for("history", "bulkc:" + key, "csv"), cache.path_for("history", "bulkv:" + key, "csv")
    if cache.fresh(pc, "history") and cache.fresh(pv, "history"):
        return (pd.read_csv(pc, index_col=0, parse_dates=True), pd.read_csv(pv, index_col=0, parse_dates=True))
    df = _yf().download(tickers, period=period, auto_adjust=True, progress=False, threads=True, group_by="column")
    if df is None or df.empty:
        raise DeskError("The price download returned nothing. Check the connection and try again.")
    if isinstance(df.columns, pd.MultiIndex):
        closes, volumes = df["Close"], df["Volume"]
    else:  # one ticker
        closes, volumes = df[["Close"]].set_axis(tickers, axis=1), df[["Volume"]].set_axis(tickers, axis=1)
    if closes.index.tz is not None:
        closes.index = closes.index.tz_localize(None)
        volumes.index = volumes.index.tz_localize(None)
    closes = closes.dropna(how="all")
    volumes = volumes.reindex(closes.index)
    closes.to_csv(pc)
    volumes.to_csv(pv)
    return closes, volumes


def _ret(c, n):
    return (c.iloc[-1] / c.iloc[-1 - n] - 1) * 100 if len(c) > n else pd.Series(float("nan"), index=c.columns)


def price_metrics(closes, volumes):
    """One row per ticker: returns, trend, momentum and volume, from the last close."""
    c = closes.ffill(limit=3)
    last = c.iloc[-1]
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / down)).iloc[-1]
    sma50, sma200 = c.rolling(50).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
    high, low = c.tail(252).max(), c.tail(252).min()
    vol5, vol50 = volumes.tail(5).mean(), volumes.tail(50).mean()
    daily = c.pct_change(fill_method=None).tail(63)
    out = pd.DataFrame({
        "price": last,
        "return_1m": _ret(c, 21), "return_3m": _ret(c, 63), "return_6m": _ret(c, 126),
        "return_12m": _ret(c, min(252, len(c) - 1)),
        "vs_sma50": (last / sma50 - 1) * 100, "vs_sma200": (last / sma200 - 1) * 100,
        "from_high": (last / high - 1) * 100, "from_low": (last / low - 1) * 100,
        "rsi": rsi, "volume_ratio": vol5 / vol50,
        "volatility": daily.std() * (252 ** 0.5) * 100,
    })
    # 12-1 momentum: the past year without the last month, the classic momentum measure.
    out["momentum_12_1"] = (c.iloc[-22] / c.iloc[-min(253, len(c))] - 1) * 100 if len(c) > 60 else float("nan")
    out["new_high"] = c.iloc[-1] >= high
    out["new_low"] = c.iloc[-1] <= low
    out["days"] = c.notna().sum()
    return out
