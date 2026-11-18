#!/usr/bin/env python3
"""Fundamental scorecard for one company, optionally against peers.

  fundamentals.py NVDA
  fundamentals.py NVDA --peers AMD AVGO INTC
  fundamentals.py THYAO --market BIST --peers PGSUS

Prints compact JSON: growth, profitability, cash quality, balance sheet,
valuation, each pillar with a rule-based signal (see references/scoring.md).
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore import DeskError, prices  # noqa: E402
from deskcore.prices import _num, _pct  # noqa: E402

FINANCIAL_SECTORS = {"Financial Services", "Financial"}


def grade(value, strong, ok, higher_is_better=True):
    if value is None:
        return "n/a"
    if not higher_is_better:
        value, strong, ok = -value, -strong, -ok
    return "strong" if value >= strong else "ok" if value >= ok else "weak"


def series(st, periods, key):
    return [st[p].get(key) for p in periods]


def cagr(values, years):
    vals = [v for v in values if v is not None]
    if len(vals) < 2 or vals[0] <= 0 or vals[-1] <= 0 or years <= 0:
        return None
    return _num(((vals[-1] / vals[0]) ** (1 / years) - 1) * 100)


def analyze(ticker, market):
    prof = prices.profile(ticker, market, summary_chars=0)
    fin = prices.financials(ticker, market, periods=5)
    st, ratios = fin["statements"], fin["ratios"]
    periods = sorted(st)  # oldest -> newest
    latest_p = periods[-1]
    L, R = st[latest_p], ratios[latest_p]
    years = len(periods) - 1
    is_fin = prof.get("sector") in FINANCIAL_SECTORS

    rev = series(st, periods, "Total Revenue")
    op_margins = [ratios[p]["operating_margin_pct"] for p in periods]
    ni, fcf = L.get("Net Income"), L.get("Free Cash Flow")
    debt, cash, ebitda = L.get("Total Debt"), L.get("Cash And Cash Equivalents"), L.get("EBITDA")
    net_debt = None if debt is None or cash is None else round(debt - cash, 1)
    shares = [s for s in series(st, periods, "Diluted Average Shares") if s]
    # Some companies report in a different currency than they trade in
    # (e.g. Turkish Airlines: statements in USD, shares in TRY). Convert the
    # market cap into the reporting currency so every ratio uses one currency.
    price_cur = prof.get("currency")
    fin_cur = prof.get("financial_currency") or price_cur
    fx = 1.0
    if fin_cur and price_cur and fin_cur != price_cur:
        fx = prices.quote(f"{fin_cur}{price_cur}=X")["close"]
    mcap_m = prof["market_cap"] / 1e6 / fx if prof.get("market_cap") and fx else None
    equity = L.get("Stockholders Equity")

    growth = {
        "revenue_cagr_pct": cagr(rev, years),
        "revenue_growth_latest_pct": R["revenue_growth_pct"],
        "eps_cagr_pct": cagr(series(st, periods, "Diluted EPS"), years),
        "years": years,
    }
    growth["signal"] = grade(growth["revenue_cagr_pct"], 10, 3)

    first_m = next((m for m in op_margins if m is not None), None)
    profitability = {
        "gross_margin_pct": R["gross_margin_pct"],
        "operating_margin_pct": R["operating_margin_pct"],
        "net_margin_pct": R["net_margin_pct"],
        "roe_pct": R["roe_pct"],
        "operating_margin_change_pp": _num(op_margins[-1] - first_m) if first_m is not None and op_margins[-1] is not None else None,
    }
    profitability["signal"] = grade(R["roe_pct"], 15, 8) if is_fin else grade(R["operating_margin_pct"], 20, 8)

    cash_q = {
        "fcf_millions": fcf,
        "fcf_to_net_income": _num(fcf / ni) if fcf is not None and ni and ni > 0 else None,
        "capex_to_revenue_pct": _num(-L["Capital Expenditure"] / L["Total Revenue"] * 100)
        if L.get("Capital Expenditure") is not None and L.get("Total Revenue") else None,
    }
    cash_q["signal"] = "n/a (financial company)" if is_fin else grade(cash_q["fcf_to_net_income"], 0.9, 0.6)

    balance = {
        "net_debt_millions": net_debt,
        "net_debt_to_ebitda": _num(net_debt / ebitda) if net_debt is not None and ebitda and ebitda > 0 else None,
        "debt_to_equity": R["debt_to_equity"],
        "share_count_change_pct": _pct(shares[-1], shares[0]) if len(shares) >= 2 else None,
    }
    if is_fin:
        balance["signal"] = "n/a (use bank metrics)"
    elif net_debt is not None and net_debt <= 0:
        balance["signal"] = "strong (net cash)"
    else:
        balance["signal"] = grade(balance["net_debt_to_ebitda"], 1, 3, higher_is_better=False)

    # P/E comes from yfinance (trailing 12 months, price and EPS in one currency).
    # EV/EBITDA, P/B and FCF yield are computed here from the latest annual
    # statements, so they stay correct when reporting and trading currency differ.
    valuation = {
        "market_cap_millions": _num(mcap_m, 0),
        "pe_ttm": prof.get("pe_ttm"),
        "pe_forward": prof.get("pe_forward"),
        "ev_ebitda": _num((mcap_m + net_debt) / ebitda) if mcap_m and net_debt is not None and ebitda and ebitda > 0 and not is_fin else None,
        "pb": _num(mcap_m / equity) if mcap_m and equity and equity > 0 else None,
        "fcf_yield_pct": _num(fcf / mcap_m * 100) if fcf is not None and mcap_m and not is_fin else None,
        "dividend_yield_pct": prof.get("dividend_yield"),
    }
    if fx != 1.0:
        valuation["currency_note"] = f"statements in {fin_cur}, shares trade in {price_cur}; market cap converted at {fin_cur}/{price_cur} {fx}"

    return {
        "symbol": prof["symbol"], "name": prof.get("name"), "sector": prof.get("sector"),
        "industry": prof.get("industry"), "currency": fin_cur,
        "latest_fiscal_year": latest_p, "financial_company": is_fin,
        "growth": growth, "profitability": profitability, "cash_quality": cash_q,
        "balance_sheet": balance, "valuation": valuation,
    }


PEER_FIELDS = {
    "pe_ttm": ("valuation", "pe_ttm"), "ev_ebitda": ("valuation", "ev_ebitda"),
    "pb": ("valuation", "pb"), "fcf_yield_pct": ("valuation", "fcf_yield_pct"),
    "operating_margin_pct": ("profitability", "operating_margin_pct"),
    "roe_pct": ("profitability", "roe_pct"), "revenue_cagr_pct": ("growth", "revenue_cagr_pct"),
}


def compare(target, peers):
    rows = {r["symbol"]: r for r in peers}
    table, medians = {}, {}
    for field, (pillar, key) in PEER_FIELDS.items():
        vals = {sym: r[pillar][key] for sym, r in rows.items()}
        table[field] = vals
        clean = [v for v in vals.values() if v is not None]
        med = statistics.median(clean) if clean else None
        medians[field] = _num(med)
        t = target[pillar][key]
        if med not in (None, 0) and t is not None:
            if field in ("operating_margin_pct", "roe_pct", "revenue_cagr_pct", "fcf_yield_pct"):
                medians[field + "_target_minus_median"] = _num(t - med)
            else:
                medians[field + "_target_vs_median_pct"] = _pct(t, med)
    return {"peers": table, "median_and_gap": medians}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--market", default="US")
    ap.add_argument("--peers", nargs="*", default=[])
    a = ap.parse_args()
    try:
        out = analyze(a.ticker, a.market)
        if a.peers:
            peer_data, failed = [], {}
            for p in a.peers:
                try:
                    peer_data.append(analyze(p, a.market))
                except Exception as e:  # noqa: BLE001
                    failed[p] = str(e)
            out["peer_comparison"] = compare(out, peer_data)
            if failed:
                out["peer_comparison"]["failed"] = failed
    except DeskError as e:
        out = {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        out = {"error": f"{type(e).__name__}: {e}"}
    sys.stdout.buffer.write((json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str) + "\n").encode("utf-8"))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    sys.exit(main())
