#!/usr/bin/env python3
"""A portfolio with a reason attached to every position: what you own, why you own it,
what would make you sell, how it would have done in past crashes, and the habits that
show up in your own trades.

  portfolio.py add AAPL 10 182.50 --date 2024-03-01 --thesis "services keep growing" --sell-if "services growth under 5%"
  portfolio.py add THYAO 200 280 --market BIST
  portfolio.py sell AAPL 5 240 --reason "position too large"
  portfolio.py note AAPL "Q3 services +14%, thesis intact"
  portfolio.py note AAPL --sell-if "services growth under 8% two quarters in a row"
  portfolio.py show | stress | review

Everything is stored in portfolio.json in the desk folder on this computer. Totals are in
US dollars; Borsa Istanbul holdings are converted at the day's USD/TRY rate.
"""
import argparse
import json
import math
import os
import sys
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore import DeskError, config, markets, prices  # noqa: E402
from deskcore.cli import run  # noqa: E402
from deskcore.prices import _num  # noqa: E402

# Real market falls, peak to trough of the S&P 500 (the dot-com fall is to the 2002 low).
EPISODES = [
    ("Dot-com bust", "2000-03-24", "2002-10-09"),
    ("2008 financial crisis", "2007-10-09", "2009-03-09"),
    ("2018 fourth quarter", "2018-09-20", "2018-12-24"),
    ("2020 Covid crash", "2020-02-19", "2020-03-23"),
    ("2022 rate shock", "2022-01-03", "2022-10-12"),
]
SHOCK = -0.20  # hypothetical fall of each holding's home index
PRICE_CHECK = 0.25  # a buy or sell price this far outside the day's close is probably a typo


def path():
    return config.HOME / "portfolio.json"


# ---------- storage ----------

def load():
    p = path()
    if not p.exists():
        return {"positions": {}, "closed": [], "archive": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        raise DeskError(f"The portfolio file at {p} is not valid JSON. Fix or move it, then retry.")
    for k, v in (("positions", {}), ("closed", []), ("archive", [])):
        data.setdefault(k, v)
    return data


def save(data):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def key_for(ticker, market):
    mkt, _ = markets.get(market)
    return f"{ticker.upper()}:{mkt}", mkt


# ---------- prices ----------

_closes = {}


def closes(sym):
    """Dividend-adjusted daily closes, full history, kept in memory for the run."""
    if sym not in _closes:
        _closes[sym] = prices.load_history(sym, "max", "1d")[0]["Close"].dropna()
    return _closes[sym]


def raw_closes(sym):
    """Closes as traded (split-adjusted, not dividend-adjusted): what a buy price compares to."""
    k = sym + ":raw"
    if k not in _closes:
        _closes[k] = prices.load_history(sym, "max", "1d", dividends_adjusted=False)[0]["Close"].dropna()
    return _closes[k]


def on(series, day):
    s = series[series.index <= str(day)[:10]]
    return float(s.iloc[-1]) if len(s) else None


def usd_rate(currency):
    """Units of `currency` per US dollar, as a daily series (None for USD)."""
    if currency == "USD":
        return None
    return closes(f"USD{currency}=X")


def to_usd(amount, currency, day=None):
    fx = usd_rate(currency)
    if fx is None:
        return amount
    rate = on(fx, day) if day else float(fx.iloc[-1])
    return amount / rate if rate else None


def total_return(sym, start, end=None):
    """Return including dividends between two dates (to the latest close when end is None)."""
    c = closes(sym)
    a = on(c, start)
    b = on(c, end) if end else float(c.iloc[-1])
    return b / a - 1 if a and b else None


# ---------- positions ----------

def avg_cost(lots):
    sh = sum(l["shares"] for l in lots)
    return sum(l["shares"] * l["price"] for l in lots) / sh if sh else 0.0


def check_price(sym, day, price, what):
    c = raw_closes(sym)
    ref = on(c, day)
    if ref is None:
        raise DeskError(f"No price for {sym} on or before {day}. Check the date.")
    if abs(price / ref - 1) > PRICE_CHECK:
        return (f"{what} price {price} is {abs(price / ref - 1) * 100:.0f}% away from the close of "
                f"{ref:.2f} on {day}. If that is a typo, sell and re-add the position; splits since then are "
                "already reflected in today's prices.")
    return None


def add(ticker, shares, price, market, day, thesis, sell_if):
    if shares <= 0 or price <= 0:
        raise DeskError("Shares and price must be positive.")
    k, mkt = key_for(ticker, market)
    sym = markets.symbol(ticker, mkt)
    day = day or date.today().isoformat()
    warning = check_price(sym, day, price, "Buy")
    data = load()
    pos = data["positions"].get(k)
    out = {}
    if pos is None:
        pos = {"ticker": ticker.upper(), "market": mkt, "symbol": sym, "opened": day, "lots": [],
               "thesis": thesis or "", "sell_if": sell_if or "", "notes": []}
        data["positions"][k] = pos
    else:
        cost = avg_cost(pos["lots"])
        if price < cost:  # the buy price is the market that day, so the position was at a loss
            pos.setdefault("averaged_down", []).append({"date": day, "price": price, "avg_cost_before": _num(cost)})
            out["note"] = f"Bought more below the average cost of {cost:.2f} while the position is at a loss."
        if thesis:
            pos["thesis"] = thesis
        if sell_if:
            pos["sell_if"] = sell_if
    pos["lots"].append({"date": day, "shares": shares, "price": price})
    pos["lots"].sort(key=lambda l: l["date"])
    pos["opened"] = pos["lots"][0]["date"]
    save(data)
    if warning:
        out["warning"] = warning
    if not pos["thesis"]:
        out["missing"] = "No thesis recorded. Ask the user why they own it and what would make them sell."
    return {"added": k, "shares": sum(l["shares"] for l in pos["lots"]), "avg_cost": _num(avg_cost(pos["lots"])), **out}


def sell(ticker, shares, price, market, day, reason):
    k, mkt = key_for(ticker, market)
    data = load()
    pos = data["positions"].get(k)
    if not pos:
        raise DeskError(f"No open position in {k}.")
    held = sum(l["shares"] for l in pos["lots"])
    if shares <= 0 or shares > held + 1e-9:
        raise DeskError(f"Can sell between 0 and {held} shares of {k}.")
    day = day or date.today().isoformat()
    warning = check_price(pos["symbol"], day, price, "Sell")
    cost = avg_cost(pos["lots"])
    bench = markets.MARKETS[mkt]["benchmark"]
    b = total_return(bench, pos["opened"], day)
    trade = {"ticker": pos["ticker"], "market": mkt, "symbol": pos["symbol"], "date": day, "shares": shares,
             "price": price, "avg_cost": _num(cost), "opened": pos["opened"],
             "held_days": (date.fromisoformat(day) - date.fromisoformat(pos["opened"])).days,
             "return_pct": _num((price / cost - 1) * 100), "benchmark_return_pct": _num(b * 100) if b is not None else None,
             "reason": reason or "", "thesis": pos["thesis"]}
    data["closed"].append(trade)
    left = held - shares
    if left <= 1e-9:
        pos["closed"] = day
        data["archive"].append(pos)
        del data["positions"][k]
    else:  # average cost stays the same after a partial sale
        pos["lots"] = [{"date": pos["opened"], "shares": left, "price": cost}]
    save(data)
    out = {"sold": k, "shares": shares, "return_pct": trade["return_pct"], "left": _num(left, 4)}
    if warning:
        out["warning"] = warning
    if not reason:
        out["missing"] = "No reason recorded. Ask the user why they sold; the review uses it."
    return out


def note(ticker, text, market, thesis, sell_if):
    k, _ = key_for(ticker, market)
    data = load()
    pos = data["positions"].get(k)
    if not pos:
        raise DeskError(f"No open position in {k}.")
    today = date.today().isoformat()
    if text:
        pos["notes"].append({"date": today, "text": text})
    for field, val in (("thesis", thesis), ("sell_if", sell_if)):
        if val:
            pos["notes"].append({"date": today, "text": f"{field} changed from: {pos[field] or '(none)'}"})
            pos[field] = val
    pos["reviewed"] = today
    save(data)
    return {"noted": k, "notes": len(pos["notes"]), "thesis": pos["thesis"], "sell_if": pos["sell_if"]}


# ---------- show ----------

def holdings(data):
    """Current value of each position in USD plus what the review and stress test need."""
    rows = []
    for k, pos in data["positions"].items():
        sym, mkt = pos["symbol"], pos["market"]
        cur = markets.MARKETS[mkt]["currency"]
        shares = sum(l["shares"] for l in pos["lots"])
        cost = avg_cost(pos["lots"])
        price = float(raw_closes(sym).iloc[-1])
        bench = markets.MARKETS[mkt]["benchmark"]
        # Since-opened returns use the first lot's date; good enough to compare with the index.
        tr = total_return(sym, pos["opened"])
        b = total_return(bench, pos["opened"])
        try:
            prof = prices.profile(pos["ticker"], mkt)
        except Exception:  # noqa: BLE001
            prof = {}
        cost_usd = sum(to_usd(l["shares"] * l["price"], cur, l["date"]) or 0 for l in pos["lots"])
        value_usd = to_usd(shares * price, cur)
        rows.append({
            "key": k, "ticker": pos["ticker"], "market": mkt, "symbol": sym, "currency": cur,
            "shares": shares, "avg_cost": cost, "price": price, "value_usd": value_usd,
            "gain_pct": (price / cost - 1) * 100, "gain_usd_pct": (value_usd / cost_usd - 1) * 100 if cost_usd else None,
            "total_return_pct": tr * 100 if tr is not None else None,
            "benchmark_pct": b * 100 if b is not None else None, "benchmark": bench,
            "opened": pos["opened"], "days": (date.today() - date.fromisoformat(pos["opened"])).days,
            "sector": prof.get("sector") or "Unknown", "country": prof.get("country") or markets.MARKETS[mkt]["country"],
            "thesis": pos.get("thesis", ""), "sell_if": pos.get("sell_if", ""),
            "last_review": pos.get("reviewed") or pos["opened"], "notes": len(pos.get("notes", [])),
            "averaged_down": len(pos.get("averaged_down", [])),
        })
    total = sum(r["value_usd"] or 0 for r in rows)
    for r in rows:
        r["weight_pct"] = (r["value_usd"] or 0) / total * 100 if total else 0
    return sorted(rows, key=lambda r: -r["weight_pct"]), total


def concentration(rows):
    by = lambda f: {k: _num(sum(r["weight_pct"] for r in rows if r[f] == k), 1)  # noqa: E731
                    for k in sorted({r[f] for r in rows})}
    hhi = sum((r["weight_pct"] / 100) ** 2 for r in rows)
    return {"largest_position_pct": _num(rows[0]["weight_pct"], 1) if rows else None,
            "top3_pct": _num(sum(r["weight_pct"] for r in rows[:3]), 1),
            "effective_positions": _num(1 / hhi, 1) if hhi else None,
            "by_sector_pct": dict(sorted(by("sector").items(), key=lambda x: -x[1])),
            "by_country_pct": dict(sorted(by("country").items(), key=lambda x: -x[1]))}


def show():
    data = load()
    if not data["positions"]:
        return {"positions": 0, "message": "The portfolio is empty. Add a position with: portfolio.py add TICKER SHARES PRICE"}
    rows, total = holdings(data)
    return {
        "as_of": date.today().isoformat(), "value_usd": _num(total, 0), "positions": len(rows),
        "holdings": [{
            "ticker": r["ticker"], "market": r["market"], "weight_pct": _num(r["weight_pct"], 1),
            "shares": _num(r["shares"], 4), "avg_cost": _num(r["avg_cost"]), "price": _num(r["price"]),
            "gain_pct": _num(r["gain_pct"]), **({"gain_in_usd_pct": _num(r["gain_usd_pct"])} if r["currency"] != "USD" else {}),
            "first_buy": r["opened"], "since_first_buy_with_dividends_pct": _num(r["total_return_pct"]),
            "index_since_first_buy_pct": _num(r["benchmark_pct"]), "sector": r["sector"],
            "thesis": r["thesis"] or None, "sell_if": r["sell_if"] or None,
            "days_since_review": (date.today() - date.fromisoformat(r["last_review"])).days,
        } for r in rows],
        "concentration": concentration(rows),
    }


# ---------- stress ----------

def beta(sym, bench, years=2):
    a = closes(sym).pct_change()
    b = closes(bench).pct_change()
    start = pd.Timestamp(date.today() - timedelta(days=int(365 * years)))
    df = pd.concat([a, b], axis=1, keys=["s", "b"], sort=True).dropna()
    df = df[df.index >= start]
    w = df.resample("W").apply(lambda x: (1 + x).prod() - 1)
    if len(w) < 30 or w["b"].var() == 0:
        return None
    return float(w["s"].cov(w["b"]) / w["b"].var())


def scaled(index_move, b):
    """A holding's move when its index moves `index_move`, given beta `b`. Compounded rather
    than linear, so a beta of 2.4 in a 57% fall gives -86%, not an impossible -134%."""
    if index_move is None or b is None:
        return None
    return (1 + index_move) ** b - 1


def usd_move(r, currency, start, end):
    """A local-currency return seen from dollars over the same dates."""
    fx = usd_rate(currency)
    if fx is None or r is None:
        return r
    a, b = on(fx, start), on(fx, end)
    return (1 + r) * (a / b) - 1 if a and b else None


def stress():
    data = load()
    if not data["positions"]:
        raise DeskError("The portfolio is empty.")
    rows, total = holdings(data)
    betas = {r["key"]: beta(r["symbol"], r["benchmark"]) for r in rows}
    episodes = []
    for name, start, end in EPISODES:
        loss, est, detail = 0.0, [], []
        for r in rows:
            c = closes(r["symbol"])
            if c.index[0] <= pd.Timestamp(start):
                ret = total_return(r["symbol"], start, end)
                how = "actual"
            else:
                bret = total_return(r["benchmark"], start, end) if closes(r["benchmark"]).index[0] <= pd.Timestamp(start) else None
                bt = betas[r["key"]]
                ret = scaled(bret, bt)
                how = "estimated"
                est.append(r["ticker"])
            ret = usd_move(ret, r["currency"], start, end)
            if ret is None:
                detail.append({"ticker": r["ticker"], "move_pct": None})
                continue
            loss += r["weight_pct"] / 100 * ret
            detail.append({"ticker": r["ticker"], "move_pct": _num(ret * 100, 1), "how": how})
        spx = total_return("^GSPC", start, end)
        worst = sorted([d for d in detail if d["move_pct"] is not None], key=lambda d: d["move_pct"])[:3]
        episodes.append({"episode": name, "from": start, "to": end, "portfolio_pct": _num(loss * 100, 1),
                         "portfolio_usd": _num(loss * total, 0), "sp500_pct": _num(spx * 100, 1) if spx else None,
                         "worst_holdings": worst, **({"estimated_from_beta": est} if est else {})})

    shock = []
    for r in rows:
        bt = betas[r["key"]]
        mv = scaled(SHOCK, bt if bt is not None else 1.0)
        shock.append({"ticker": r["ticker"], "beta": _num(bt), "move_pct": _num(mv * 100, 1)})
    shock_total = sum(r["weight_pct"] / 100 * scaled(SHOCK, betas[r["key"]] if betas[r["key"]] is not None else 1.0)
                      for r in rows)

    # How today's weights would have moved over the last five years, month by month.
    daily = pd.concat({r["key"]: closes(r["symbol"]).pct_change() for r in rows}, axis=1, sort=True)
    daily = daily[daily.index >= pd.Timestamp(date.today() - timedelta(days=5 * 365))]
    w = pd.Series({r["key"]: r["weight_pct"] / 100 for r in rows})
    port = (daily.fillna(0) * w).sum(axis=1)
    monthly = (1 + port).resample("ME").prod() - 1
    last_year = daily[daily.index >= pd.Timestamp(date.today() - timedelta(days=365))].dropna(axis=1, how="all")
    corr = last_year.corr()
    pairs = [(a, b, corr.at[a, b]) for i, a in enumerate(corr.columns) for b in corr.columns[i + 1:]
             if not math.isnan(corr.at[a, b])]
    return {
        "value_usd": _num(total, 0),
        "past_crashes": episodes,
        "index_down_20pct": {"portfolio_pct": _num(shock_total * 100, 1), "by_holding": shock,
                             "how": "each holding's home index falls 20%; moves scaled by 2-year weekly beta "
                                    "(beta 1 where there is too little history)"},
        "last_5y_with_todays_weights": {
            "worst_month_pct": _num(monthly.min() * 100, 1), "worst_month": str(monthly.idxmin().date())[:7],
            "annual_volatility_pct": _num(port.std() * math.sqrt(252) * 100, 1),
        },
        "correlation_1y": {
            "average": _num(sum(p[2] for p in pairs) / len(pairs), 2) if pairs else None,
            "most_alike": [{"pair": f"{a.split(':')[0]}/{b.split(':')[0]}", "corr": _num(c, 2)}
                           for a, b, c in sorted(pairs, key=lambda p: -p[2])[:3]],
        },
        "notes": ["Crash moves include dividends and are in US dollars; BIST holdings include the lira's fall.",
                  "A holding listed after a crash began is estimated from its beta, which understates how far "
                  "a young growth stock can fall."],
    }


# ---------- review ----------

def disposition(data):
    """Odean's test: on each day you sold something, which of your holdings were at a gain
    or a loss, and which did you sell? Selling gains far more readily than losses is the
    disposition effect, the most documented habit of individual investors."""
    events = {}
    for t in data["closed"]:
        events.setdefault(t["date"], set()).add(f"{t['ticker']}:{t['market']}")
    if not events:
        return None
    every = list(data["positions"].values()) + data["archive"]
    rg = sum(1 for t in data["closed"] if t["return_pct"] > 0)
    rl = len(data["closed"]) - rg
    pg = pl = 0
    for day, sold in events.items():
        for pos in every:
            if f"{pos['ticker']}:{pos['market']}" in sold:
                continue
            lots = [l for l in pos["lots"] if l["date"] <= day]
            if not lots or pos.get("closed", "9999") < day:
                continue
            px = on(raw_closes(pos["symbol"]), day)
            if px is None:
                continue
            if px > avg_cost(lots):
                pg += 1
            else:
                pl += 1
    pgr = rg / (rg + pg) if rg + pg else None
    plr = rl / (rl + pl) if rl + pl else None
    out = {"sale_days": len(events), "gains_sold": rg, "gains_kept": pg, "losses_sold": rl, "losses_kept": pl,
           "share_of_gains_sold": _num(pgr, 2), "share_of_losses_sold": _num(plr, 2)}
    if pgr is not None and plr is not None and rg + rl >= 5:
        out["reads"] = ("sells winners more readily than losers (disposition effect)" if pgr > plr * 1.5 else
                        "sells losers more readily than winners" if plr > pgr * 1.5 else "no clear lean")
    else:
        out["reads"] = "too few sales to tell"
    return out


def review():
    data = load()
    rows, total = holdings(data) if data["positions"] else ([], 0)
    closed = data["closed"]
    wins = [t for t in closed if t["return_pct"] > 0]
    losses = [t for t in closed if t["return_pct"] <= 0]
    beat = [t for t in closed if t.get("benchmark_return_pct") is not None]
    flags = []
    for r in rows:
        if not r["thesis"]:
            flags.append({"ticker": r["ticker"], "flag": "no thesis recorded"})
        elif not r["sell_if"]:
            flags.append({"ticker": r["ticker"], "flag": "no sell condition recorded"})
        if r["gain_pct"] < -20 and r["last_review"] == r["opened"]:
            flags.append({"ticker": r["ticker"], "flag": f"down {abs(r['gain_pct']):.0f}% and never reviewed; "
                                                        f"check the sell condition: {r['sell_if'] or '(none)'}"})
        if r["averaged_down"]:
            flags.append({"ticker": r["ticker"], "flag": f"bought more below cost {r['averaged_down']} time(s)"})
        if r["weight_pct"] > 25:
            flags.append({"ticker": r["ticker"], "flag": f"{r['weight_pct']:.0f}% of the portfolio in one stock"})
        if (date.today() - date.fromisoformat(r["last_review"])).days > 180:
            flags.append({"ticker": r["ticker"], "flag": "thesis not reviewed in over six months"})
    sold_no_reason = sum(1 for t in closed if not t.get("reason"))

    out = {
        "open_positions": len(rows), "closed_trades": len(closed),
        "flags": flags,
        "trading": {
            "win_rate_pct": _num(len(wins) / len(closed) * 100, 0) if closed else None,
            "average_win_pct": _num(sum(t["return_pct"] for t in wins) / len(wins)) if wins else None,
            "average_loss_pct": _num(sum(t["return_pct"] for t in losses) / len(losses)) if losses else None,
            "days_held_winners": _num(sum(t["held_days"] for t in wins) / len(wins), 0) if wins else None,
            "days_held_losers": _num(sum(t["held_days"] for t in losses) / len(losses), 0) if losses else None,
            "beat_index_pct": _num(sum(1 for t in beat if t["return_pct"] > t["benchmark_return_pct"]) / len(beat) * 100, 0)
            if beat else None,
            "sales_without_reason": sold_no_reason,
        },
        "disposition": disposition(data),
        "concentration": concentration(rows) if rows else None,
        "open_vs_index": [{"ticker": r["ticker"], "first_buy": r["opened"], "since_first_buy_with_dividends_pct": _num(r["total_return_pct"]),
                           "index_pct": _num(r["benchmark_pct"])} for r in rows],
    }
    try:
        scen = _scenario_scorecard()
        if scen:
            out["scenario_scorecard"] = scen
    except Exception:  # noqa: BLE001  (optional link to the scenarios skill)
        pass
    if len(closed) < 10:
        out["sample_note"] = f"{len(closed)} closed trades. Patterns need at least 10 before they say much."
    return out


def _scenario_scorecard():
    p = config.HOME / "scenarios.json"
    if not p.exists():
        return None
    import importlib.util
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scenarios", "scripts", "scenarios.py")
    spec = importlib.util.spec_from_file_location("scenarios", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.score()["summary"]


def main():
    ap = argparse.ArgumentParser(description="Portfolio with a thesis journal, stress test and bias review.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_market = config.load().get("default_market", "US")
    for name in ("add", "sell"):
        p = sub.add_parser(name)
        p.add_argument("ticker")
        p.add_argument("shares", type=float)
        p.add_argument("price", type=float, help="per share, in the stock's trading currency")
        p.add_argument("--market", default=default_market)
        p.add_argument("--date", help="trade date YYYY-MM-DD (default today)")
        if name == "add":
            p.add_argument("--thesis", default="", help="why you own it, in a sentence")
            p.add_argument("--sell-if", default="", help="what would prove the thesis wrong")
        else:
            p.add_argument("--reason", default="")
    p = sub.add_parser("note")
    p.add_argument("ticker")
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--market", default=default_market)
    p.add_argument("--thesis", default="")
    p.add_argument("--sell-if", default="")
    for name in ("show", "stress", "review"):
        sub.add_parser(name)
    a = ap.parse_args()
    actions = {
        "add": lambda: add(a.ticker, a.shares, a.price, a.market, a.date, a.thesis, a.sell_if),
        "sell": lambda: sell(a.ticker, a.shares, a.price, a.market, a.date, a.reason),
        "note": lambda: note(a.ticker, a.text, a.market, a.thesis, a.sell_if),
        "show": show, "stress": stress, "review": review,
    }
    return run(actions[a.cmd])


if __name__ == "__main__":
    sys.exit(main())
