#!/usr/bin/env python3
"""Bear, base and bull cases for a stock, built from the company's own history, and a
scorecard that checks saved cases against what the price actually did.

  scenarios.py build AAPL                      cases for the next 3 years
  scenarios.py build MSFT --years 5 --set bear.growth=4 --set bull.multiple=35
  scenarios.py save AAPL --note "services keep growing"   build and keep in the journal
  scenarios.py score                           every saved case against the price since
  scenarios.py list | delete ID

Each case is three numbers: revenue growth per year, net margin, and the multiple the
market pays at the end (P/E, or price to sales for companies without steady profits).
Defaults come from the company's last ten years: the 20th percentile for bear, the
median for base, the 80th percentile for bull. Claude or the user can override any of them.
"""
import argparse
import json
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore import DeskError, bis, cache, config, markets, prices, verify  # noqa: E402
from deskcore.cli import run  # noqa: E402
from deskcore.prices import _num  # noqa: E402

CASES = ("bear", "base", "bull")
QUANTILE = {"bear": 0.2, "base": 0.5, "bull": 0.8}
FIELDS = ("growth", "margin", "multiple")
MAX_PE = 150  # a P/E above this says more about a dip in earnings than about value
HISTORY_YEARS = 10
FADE_YEARS = 10  # growth moves in a straight line to the anchor over this many years
# Ceilings on the defaults. Growth of 200% a year off a small base (a young company) or a
# price-to-sales of 300 at an IPO is history, not a forecast. A user can still --set above them.
MAX_GROWTH = 0.40
MAX_PS = 30
# Reporting currency -> BIS country code, for the inflation the growth fades toward.
CURRENCY_COUNTRY = {"USD": "US", "TRY": "TR", "EUR": "XM", "GBP": "GB", "JPY": "JP", "CNY": "CN",
                    "TWD": "TW", "KRW": "KR", "INR": "IN", "BRL": "BR", "CAD": "CA", "AUD": "AU",
                    "CHF": "CH", "MXN": "MX", "ZAR": "ZA", "HKD": "HK", "SEK": "SE", "DKK": "DK"}


def journal_path():
    return config.HOME / "scenarios.json"


# ---------- small helpers ----------

def quantile(values, q):
    v = sorted(x for x in values if x is not None and not math.isnan(x))
    if not v:
        return None
    pos = (len(v) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def percentile_rank(values, x):
    v = [y for y in values if y is not None]
    if not v or x is None:
        return None
    return _num(sum(1 for y in v if y <= x) / len(v) * 100, 0)


def cagr(a, b, years):
    if not a or not b or a <= 0 or b <= 0 or years <= 0:
        return None
    return (b / a) ** (1 / years) - 1


def years_between(a, b):
    return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days / 365.25


def price_on(close, day):
    """Last close on or before `day`."""
    s = close[close.index <= str(day)[:10]]
    return float(s.iloc[-1]) if len(s) else None


def split_factors(sym):
    key = f"splits:{sym}"
    hit = cache.get_json("financials", key)
    if hit is None:
        s = prices._yf().Ticker(sym).splits
        hit = [[str(d.date()), float(r)] for d, r in s.items()] if s is not None else []
        cache.put_json("financials", key, hit)
    return hit


def splits_after(splits, day):
    f = 1.0
    for d, r in splits:
        if d > day and r > 0:
            f *= r
    return f


# ---------- annual history ----------

def sec_years(ticker, sym):
    """Annual revenue, net income, EPS and shares from 10-K filings, in millions.
    A per-share figure in a 10-K is in the share count of its day, so every split
    after the filing date is applied: Apple's 2017 EPS of $9.21 becomes $2.30."""
    data = verify.sec_annuals(ticker)
    if "_reason" in data:
        raise DeskError(data["_reason"])
    filed = data.get("_filed", {})
    splits = split_factors(sym)
    out = {}
    for end, rev in data.get("Total Revenue", {}).items():
        if not rev or rev <= 0:
            continue
        ni = data.get("Net Income", {}).get(end)
        eps = data.get("Diluted EPS", {}).get(end)
        sh = data.get("Diluted Average Shares", {}).get(end)
        if eps is not None:
            eps /= splits_after(splits, filed.get("Diluted EPS", {}).get(end, ""))
        if sh is not None:
            sh *= splits_after(splits, filed.get("Diluted Average Shares", {}).get(end, ""))
        elif ni and eps and ni > 0 and eps > 0:
            sh = ni / eps
        out[end] = {"revenue": rev / 1e6, "net_income": ni / 1e6 if ni is not None else None,
                    "shares": sh / 1e6 if sh else None}
    return dict(sorted(out.items()))


def yahoo_years(ticker, market):
    st = prices.financials(ticker, market, periods=12)["statements"]
    out = {}
    for end, r in sorted(st.items()):
        if r.get("Total Revenue") and r["Total Revenue"] > 0:
            out[end] = {"revenue": r["Total Revenue"], "net_income": r.get("Net Income"),
                        "shares": r.get("Diluted Average Shares")}
    return out


def trailing(ticker, market):
    """Last four quarters summed, when Yahoo has four consecutive ones."""
    try:
        q = prices.financials(ticker, market, quarterly=True, periods=4)["statements"]
    except DeskError:
        return None
    ends = sorted(q)
    if len(ends) < 4 or not 250 <= (date.fromisoformat(ends[-1]) - date.fromisoformat(ends[0])).days <= 300:
        return None
    rev = [q[e].get("Total Revenue") for e in ends]
    ni = [q[e].get("Net Income") for e in ends]
    if any(v is None for v in rev + ni):
        return None
    return {"end": ends[-1], "revenue": sum(rev), "net_income": sum(ni),
            "shares": q[ends[-1]].get("Diluted Average Shares")}


def fx_series(fin_ccy, px_ccy):
    """Daily rate to turn reporting currency into trading currency (USD -> TRY for THY)."""
    df, _ = prices.load_history(f"{fin_ccy}{px_ccy}=X", "max", "1d")
    return df["Close"].dropna()


def growth_anchor(country):
    """Where revenue growth heads in the long run: the country's latest inflation plus 2
    points of real growth. Few companies keep growing much faster than the economy for a
    decade, and for a lira company most of the nominal growth is inflation."""
    try:
        cpi = bis.cpi_yoy(country)
        last = float(cpi.iloc[-1])
        return last / 100 + 0.02, f"{country} inflation {last:.1f}% + 2%"
    except Exception:  # noqa: BLE001
        return 0.045, "4.5% (inflation data unavailable)"


def revenue_after(rev0, g, years, anchor):
    rev = rev0
    for i in range(1, years + 1):
        rev *= 1 + g + (anchor - g) * min(i / FADE_YEARS, 1.0)
    return rev


def history(ticker, market):
    mkt, info = markets.get(market)
    sym = markets.symbol(ticker, mkt)
    prof = prices.profile(ticker, mkt)
    px_ccy, fin_ccy = prof.get("currency"), prof.get("financial_currency") or prof.get("currency")
    if mkt == "US" and fin_ccy and px_ccy and fin_ccy != px_ccy:
        raise DeskError(f"{sym} reports in {fin_ccy} but trades in {px_ccy}, which usually means an ADR. "
                        "One ADR is not one share and free data does not give the ratio, so per-share "
                        "cases would be wrong. Use the fundamentals skill for this company.")
    source = "10-K filings (SEC XBRL)"
    years = {}
    if mkt == "US":
        try:
            years = sec_years(ticker, sym)
        except DeskError:
            years = {}
    if len(years) < 3:
        years, source = yahoo_years(ticker, mkt), "Yahoo annual statements"
    years = dict(list(years.items())[-(HISTORY_YEARS + 1):])
    if len(years) < 2:
        raise DeskError(f"Not enough annual statements for {sym} to build cases.")

    close = prices.load_history(sym, "max", "1d", dividends_adjusted=False)[0]["Close"].dropna()
    fx = fx_series(fin_ccy, px_ccy) if fin_ccy != px_ccy else None
    rows = []
    for end, y in years.items():
        rate = price_on(fx, end) if fx is not None else 1.0
        price = price_on(close, end)
        row = {"end": end, **y, "margin": y["net_income"] / y["revenue"] if y.get("net_income") is not None else None,
               "price": price, "fx": rate}
        if price and y.get("shares") and rate:
            per_share_sales = y["revenue"] * rate / y["shares"]
            row["ps"] = price / per_share_sales
            if y.get("net_income") and y["net_income"] > 0:
                pe = price / (y["net_income"] * rate / y["shares"])
                row["pe"] = pe if pe <= MAX_PE else None
        rows.append(row)
    return {"symbol": sym, "market": mkt, "benchmark": info["benchmark"], "source": source,
            "country": CURRENCY_COUNTRY.get(fin_ccy, info["country"]),
            "currency": px_ccy, "reporting_currency": fin_ccy, "rows": rows,
            "start": trailing(ticker, mkt), "fx_now": float(fx.iloc[-1]) if fx is not None else 1.0}


# ---------- cases ----------

def defaults(rows, horizon, multiple_now=None, max_growth=MAX_GROWTH):
    """Assumption ranges from the company's own record. The base multiple is today's,
    pulled back to the edge of the usual range (20th to 80th percentile) when outside it."""
    revs = [(r["end"], r["revenue"]) for r in rows if r["revenue"] and r["revenue"] > 0]
    # 3-year windows when there is enough history for at least three of them, shorter otherwise
    k = max(1, min(3, horizon, len(revs) - 3))
    growth = [cagr(revs[i][1], revs[i + k][1], years_between(revs[i][0], revs[i + k][0]))
              for i in range(len(revs) - k)]
    margins = [r["margin"] for r in rows if r.get("margin") is not None]
    profitable = sum(1 for m in margins if m > 0)
    pes = [r["pe"] for r in rows if r.get("pe")]
    method = "pe" if margins and margins[-1] > 0 and profitable >= 0.7 * len(margins) and len(pes) >= 3 else "ps"
    multiples = pes if method == "pe" else [min(r["ps"], MAX_PS) for r in rows if r.get("ps")]
    if len(multiples) < 2:
        raise DeskError("Not enough years with a price, share count and earnings to judge the multiple.")
    shares = [(r["end"], r["shares"]) for r in rows if r.get("shares")]
    share_change = None
    if len(shares) >= 2:
        a, b = shares[max(0, len(shares) - 6)], shares[-1]
        share_change = cagr(a[1], b[1], years_between(a[0], b[0]))
    cases = {}
    for c in CASES:
        cases[c] = {
            "growth": min(quantile(growth, QUANTILE[c]), max_growth) if growth else None,
            # The base margin comes from the last five years: an old regime says little
            # about today. Bear and bull use the whole record.
            "margin": quantile(margins[-5:] if c == "base" else margins, QUANTILE[c]) if method == "pe" else None,
            "multiple": quantile(multiples, QUANTILE[c]),
        }
    if multiple_now and multiple_now > 0:
        cases["base"]["multiple"] = min(max(multiple_now, cases["bear"]["multiple"]), cases["bull"]["multiple"])
    for f in FIELDS:  # keep bear <= base <= bull after mixing windows
        b = cases["base"][f]
        if b is not None:
            if cases["bear"][f] is not None:
                cases["bear"][f] = min(cases["bear"][f], b)
            if cases["bull"][f] is not None:
                cases["bull"][f] = max(cases["bull"][f], b)
    return method, cases, share_change or 0.0, {"growth": growth, "margins": margins, "multiples": multiples,
                                                 "growth_window_years": k}


def apply_overrides(cases, sets):
    """--set bear.growth=4  (percent)  --set base.multiple=22  --set shares=-1.5 (percent a year)"""
    share_change = None
    for s in sets or []:
        key, _, val = s.partition("=")
        try:
            v = float(val)
        except ValueError:
            raise DeskError(f"Bad --set value '{s}'. Use for example bear.growth=4 or base.multiple=22.")
        if key == "shares":
            share_change = v / 100
            continue
        case, _, field = key.partition(".")
        if case not in CASES or field not in FIELDS:
            raise DeskError(f"Bad --set key '{key}'. Cases: {', '.join(CASES)}; fields: {', '.join(FIELDS)}; or 'shares'.")
        cases[case][field] = v if field == "multiple" else v / 100
        cases[case]["overridden"] = sorted(set(cases[case].get("overridden", [])) | {field})
    return share_change


def project(start, price0, case, method, share_change, years, fx, anchor):
    g, m, mult = case["growth"], case["margin"], case["multiple"]
    if g is None or mult is None or (method == "pe" and m is None):
        return None
    rev = revenue_after(start["revenue"], g, years, anchor)
    shares = start["shares"] * (1 + share_change) ** years
    per_share = (rev * m if method == "pe" else rev) * fx / shares
    price = per_share * mult
    if price <= 0:
        return {"price": None, "note": "negative earnings at the end; no price"}
    return {"price": _num(price), "annual_return_pct": _num(((price / price0) ** (1 / years) - 1) * 100),
            "total_return_pct": _num((price / price0 - 1) * 100),
            "revenue_growth_avg_pct": _num(((rev / start["revenue"]) ** (1 / years) - 1) * 100)}


def growth_needed(start, price0, case, method, share_change, years, fx, annual_return):
    """Average revenue growth over the horizon that, with this case's margin and
    multiple, earns `annual_return` a year."""
    m, mult = case["margin"], case["multiple"]
    if mult is None or (method == "pe" and (m is None or m <= 0)):
        return None
    target = price0 * (1 + annual_return) ** years
    shares = start["shares"] * (1 + share_change) ** years
    rev_needed = target * shares / (mult * (m if method == "pe" else 1) * fx)
    g = cagr(start["revenue"], rev_needed, years)
    return _num(g * 100) if g is not None else None


def build(ticker, market, years=3, sets=None):
    h = history(ticker, market)
    rows = h["rows"]
    last = rows[-1]
    start = h["start"] or {"end": last["end"], "revenue": last["revenue"], "net_income": last["net_income"],
                           "shares": last["shares"]}
    start = dict(start)
    start["basis"] = "last four quarters" if h["start"] else "last fiscal year"
    if not start.get("shares"):
        start["shares"] = last.get("shares")
    if not start.get("shares") or not start.get("revenue"):
        raise DeskError(f"Share count or revenue missing for {h['symbol']}; cannot build per-share cases.")
    q = prices.quote(ticker, h["market"])
    price0 = q["close"]
    fx = h["fx_now"]
    pe_now = price0 / (start["net_income"] * fx / start["shares"]) if start.get("net_income") else None
    ps_now = price0 / (start["revenue"] * fx / start["shares"])
    anchor, anchor_label = growth_anchor(h["country"])
    # In a high-inflation currency the cap moves up with inflation.
    max_growth = max(MAX_GROWTH, anchor + 0.25)
    method = defaults(rows, years)[0]
    method, cases, hist_shares, ranges = defaults(rows, years, pe_now if method == "pe" else ps_now, max_growth)
    override_shares = apply_overrides(cases, sets)
    share_change = override_shares if override_shares is not None else hist_shares

    out_cases = {}
    for c in CASES:
        a = cases[c]
        out_cases[c] = {
            "assumptions": {"revenue_growth_pct": _num(a["growth"] * 100) if a["growth"] is not None else None,
                            "net_margin_pct": _num(a["margin"] * 100) if a["margin"] is not None else None,
                            ("exit_pe" if method == "pe" else "exit_price_to_sales"): _num(a["multiple"], 1)},
            **(project(start, price0, a, method, share_change, years, fx, anchor) or {"price": None}),
        }
        if a.get("overridden"):
            out_cases[c]["overridden"] = a["overridden"]

    multiple_now = pe_now if method == "pe" else ps_now
    if multiple_now is not None and multiple_now <= 0:
        multiple_now = None
    margin_now = start["net_income"] / start["revenue"] if start.get("net_income") is not None else None
    warnings = []
    if len(rows) < 5:
        warnings.append(f"Only {len(rows)} years of statements; the ranges rest on little history.")
    if h["currency"] != h["reporting_currency"]:
        warnings.append(f"Reports in {h['reporting_currency']}, trades in {h['currency']}; "
                        "history converted at each year-end rate, the projection at today's rate.")
    if max(ranges["growth"] or [0]) > max_growth:
        warnings.append(f"Past growth reached {max(ranges['growth']) * 100:.0f}% a year, likely off a small base; "
                        f"the cases cap starting growth at {max_growth * 100:.0f}%. Even the bear case may be "
                        "too generous.")
    lo_m, hi_m = min(ranges["multiples"]), max(ranges["multiples"])
    name_m = "P/E" if method == "pe" else "price to sales"
    if multiple_now and multiple_now > hi_m:
        warnings.append(f"Today's {name_m} of {multiple_now:.1f} is above every year-end in the record "
                        f"(highest {hi_m:.1f}). The base case assumes it falls to {cases['base']['multiple']:.1f}.")
    elif multiple_now and multiple_now < lo_m:
        warnings.append(f"Today's {name_m} of {multiple_now:.1f} is below every year-end in the record "
                        f"(lowest {lo_m:.1f}). The base case assumes it recovers to {cases['base']['multiple']:.1f}.")
    if (cases["base"]["growth"] or 0) > 0.20:
        warnings.append("Base growth above 20% a year comes from the company's own recent record. Few companies "
                        "keep that up; it already fades toward the anchor here, but say how much rests on it.")
    if method == "ps":
        warnings.append("Profits are missing or unsteady, so cases use price to sales instead of P/E.")
    if margin_now is not None and margin_now < 0 < (cases["base"]["margin"] or 0):
        warnings.append("The company is losing money now but the base case assumes its usual margin returns.")

    return {
        "symbol": h["symbol"], "price": price0, "price_date": q["date"], "currency": h["currency"],
        "years": years, "method": "P/E" if method == "pe" else "price to sales",
        "start": {"basis": start["basis"], "period_end": start["end"],
                  "revenue_m": _num(start["revenue"], 0), "net_income_m": _num(start.get("net_income"), 0),
                  "net_margin_pct": _num(margin_now * 100) if margin_now is not None else None,
                  ("pe_now" if method == "pe" else "ps_now"): _num(multiple_now, 1),
                  "reporting_currency": h["reporting_currency"]},
        "share_count_change_pct_per_year": _num(share_change * 100),
        "growth_fade": f"starting growth moves in a straight line over {FADE_YEARS} years toward {anchor_label}",
        "cases": out_cases,
        "growth_needed_pct": {
            "to_hold_price": growth_needed(start, price0, cases["base"], method, share_change, years, fx, 0.0),
            "for_10pct_a_year": growth_needed(start, price0, cases["base"], method, share_change, years, fx, 0.10),
            "at": "base margin and base multiple; average growth over the horizon",
        },
        "history": {
            "source": h["source"], "years": f"{rows[0]['end'][:4]}-{rows[-1]['end'][:4]}",
            "revenue_growth_pct_range": [_num(min(ranges["growth"]) * 100), _num(max(ranges["growth"]) * 100)]
            if ranges["growth"] else None,
            "growth_window_years": ranges["growth_window_years"],
            "net_margin_pct_range": [_num(min(ranges["margins"]) * 100), _num(max(ranges["margins"]) * 100)]
            if ranges["margins"] else None,
            "multiple_range": [_num(min(ranges["multiples"]), 1), _num(max(ranges["multiples"]), 1)]
            if ranges["multiples"] else None,
            "multiple_now_percentile": percentile_rank(ranges["multiples"], multiple_now),
        },
        "benchmark": h["benchmark"],
        "notes": warnings + ["Price return only; dividends come on top.",
                             "Bear and bull combine the low (or high) end of all three assumptions at once, "
                             "so they are wide on purpose."],
    }


# ---------- journal ----------

def load_journal():
    p = journal_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        raise DeskError(f"The scenario journal at {p} is not valid JSON. Fix or move it, then retry.")


def write_journal(entries):
    p = journal_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def save(ticker, market, years, sets, note):
    b = build(ticker, market, years, sets)
    if any(b["cases"][c].get("price") is None for c in CASES):
        raise DeskError("One of the cases has no price, so it cannot be scored later. Adjust it with --set first.")
    mkt, _ = markets.get(market)
    bench = prices.quote(b["benchmark"], mkt)
    entries = load_journal()
    today = date.today().isoformat()
    n = sum(1 for e in entries if e["symbol"] == b["symbol"] and e["saved"] == today) + 1
    entry = {
        "id": f"{b['symbol']}-{today}-{n}", "ticker": ticker.upper(), "market": mkt, "symbol": b["symbol"],
        "saved": today, "price_date": b["price_date"], "price": b["price"], "years": years,
        "benchmark": b["benchmark"], "benchmark_level": bench["close"],
        "method": b["method"], "start": b["start"],
        "cases": {c: {"price": b["cases"][c]["price"], **b["cases"][c]["assumptions"]} for c in CASES},
        "note": note or "",
    }
    entries.append(entry)
    write_journal(entries)
    return {"saved": entry, "journal": str(journal_path()), "count": len(entries)}


def position(actual, path):
    """0 at the bear path, 0.5 at base, 1 at bull, on a log scale; beyond the ends it keeps going."""
    la, (lb, lm, lu) = math.log(actual), (math.log(path["bear"]), math.log(path["base"]), math.log(path["bull"]))
    if la <= lm:
        return 0.5 * (la - lb) / (lm - lb) if lm != lb else (0.0 if la < lb else 0.5)
    return 0.5 + 0.5 * (la - lm) / (lu - lm) if lu != lm else 1.0


def band(actual, path):
    if actual < path["bear"]:
        return "below bear"
    if actual < path["base"]:
        return "between bear and base"
    if actual <= path["bull"]:
        return "between base and bull"
    return "above bull"


def score_entry(e, today=None):
    today = today or date.today()
    saved = date.fromisoformat(e["saved"])
    elapsed = years_between(saved, today)
    out = {"id": e["id"], "saved": e["saved"], "years": e["years"], "note": e.get("note", "")}
    if elapsed < 1 / 12:
        return {**out, "status": "too early", "days": (today - saved).days}
    close = prices.load_history(e["symbol"], "max", "1d", dividends_adjusted=False)[0]["Close"].dropna()
    asof = min(today, date.fromordinal(saved.toordinal() + round(e["years"] * 365.25)))
    p_then, p_now = price_on(close, e["price_date"]), price_on(close, asof)
    if not p_then or not p_now:
        return {**out, "status": "no price data"}
    frac = min(elapsed / e["years"], 1.0)
    # Prices from today's series, so splits since the save do not distort the comparison.
    path = {c: p_then * (e["cases"][c]["price"] / e["price"]) ** frac for c in CASES}
    out.update({
        "status": "final" if elapsed >= e["years"] else "in progress",
        "measured_on": str(asof), "elapsed_years": _num(min(elapsed, e["years"]), 2),
        "price_change_pct": _num((p_now / p_then - 1) * 100),
        "expected_by_now_pct": {c: _num((path[c] / p_then - 1) * 100) for c in CASES},
        "where": band(p_now, path), "position": _num(position(p_now, path), 2),
    })
    try:
        b = prices.load_history(e["benchmark"], "max", "1d", dividends_adjusted=False)[0]["Close"].dropna()
        out["benchmark_change_pct"] = _num((price_on(b, asof) / price_on(b, e["price_date"]) - 1) * 100)
    except Exception:  # noqa: BLE001  (context only)
        pass
    try:
        rows = history(e["ticker"], e["market"])["rows"]
        newer = [r for r in rows if r["end"] > e["start"]["period_end"]]
        if newer and e["start"].get("revenue_m"):
            r = newer[-1]
            yrs = years_between(e["start"]["period_end"], r["end"])
            if yrs >= 0.5:
                g = cagr(e["start"]["revenue_m"], r["revenue"], yrs)
                out["assumption_check"] = {
                    "through": r["end"],
                    "revenue_growth_pct": _num(g * 100) if g is not None else None,
                    "net_margin_pct": _num(r["margin"] * 100) if r.get("margin") is not None else None,
                    "assumed_base": {k: v for k, v in e["cases"]["base"].items() if k != "price"},
                }
    except Exception:  # noqa: BLE001
        pass
    return out


def score(ticker=None):
    entries = [e for e in load_journal() if not ticker or e["ticker"] == ticker.upper()]
    if not entries:
        return {"scored": 0, "message": "No saved scenarios yet. Save one with: scenarios.py save TICKER"}
    rows = [score_entry(e) for e in entries]
    live = [r for r in rows if "position" in r]
    summary = {"saved": len(rows), "scored": len(live)}
    if live:
        inside = sum(1 for r in live if r["where"] in ("between bear and base", "between base and bull"))
        above = sum(1 for r in live if r["position"] > 0.5)
        summary.update({
            "inside_bear_bull_pct": _num(inside / len(live) * 100, 0),
            "above_base_pct": _num(above / len(live) * 100, 0),
            "average_position": _num(sum(r["position"] for r in live) / len(live), 2),
            "how_to_read": "Inside bear-bull should be most of the time; well under 80% means the ranges are "
                           "too narrow. Above base should be near 50%; far below means the base cases lean "
                           "optimistic, far above means pessimistic. Fewer than 10 scored cases prove little.",
        })
    return {"summary": summary, "scenarios": rows}


def list_entries():
    return {"journal": str(journal_path()),
            "scenarios": [{"id": e["id"], "saved": e["saved"], "price": e["price"], "years": e["years"],
                           "bear": e["cases"]["bear"]["price"], "base": e["cases"]["base"]["price"],
                           "bull": e["cases"]["bull"]["price"], "note": e.get("note", "")}
                          for e in load_journal()]}


def delete(entry_id):
    entries = load_journal()
    keep = [e for e in entries if e["id"] != entry_id]
    if len(keep) == len(entries):
        raise DeskError(f"No saved scenario with id '{entry_id}'. Run 'scenarios.py list' to see ids.")
    write_journal(keep)
    return {"deleted": entry_id, "left": len(keep)}


def main():
    ap = argparse.ArgumentParser(description="Bear, base and bull cases with a scorecard.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_market = config.load().get("default_market", "US")
    for name in ("build", "save"):
        p = sub.add_parser(name)
        p.add_argument("ticker")
        p.add_argument("--market", default=default_market)
        p.add_argument("--years", type=int, default=3, help="horizon in years, 1 to 10 (default 3)")
        p.add_argument("--set", action="append", default=[], metavar="CASE.FIELD=VALUE",
                       help="override an assumption: bear.growth=4, base.margin=20, bull.multiple=30, shares=-1")
        if name == "save":
            p.add_argument("--note", default="", help="why you hold this view, in a sentence")
    p = sub.add_parser("score")
    p.add_argument("ticker", nargs="?")
    sub.add_parser("list")
    p = sub.add_parser("delete")
    p.add_argument("id")
    a = ap.parse_args()

    if a.cmd in ("build", "save") and not 1 <= a.years <= 10:
        return run(lambda: (_ for _ in ()).throw(DeskError("--years must be between 1 and 10.")))
    actions = {
        "build": lambda: build(a.ticker, a.market, a.years, a.set),
        "save": lambda: save(a.ticker, a.market, a.years, a.set, getattr(a, "note", "")),
        "score": lambda: score(a.ticker),
        "list": list_entries,
        "delete": lambda: delete(a.id),
    }
    return run(actions[a.cmd])


if __name__ == "__main__":
    sys.exit(main())
