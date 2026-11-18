"""Live check against the real free sources. Needs internet; takes a few minutes.

  python tests/live_check.py            all tickers
  python tests/live_check.py AAPL       one ticker

Runs every script on a spread of companies that break naive code (share classes,
foreign ADRs, banks, a holding, BIST stocks reporting in USD/EUR, an ETF, a bad
ticker) and flags numbers outside plausible ranges. Exit code 1 if anything fails.
"""
import json
import os
import subprocess
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "skills"
DESK = S / "desk-data" / "scripts" / "desk.py"
FUND = S / "fundamentals" / "scripts" / "fundamentals.py"
TECH = S / "technicals" / "scripts" / "technicals.py"
STORY = S / "company-story" / "scripts" / "story.py"
NEWS = S / "news-analyst" / "scripts" / "news.py"
SCEN = S / "scenarios" / "scripts" / "scenarios.py"
PORT = S / "portfolio" / "scripts" / "portfolio.py"
SCREEN = S / "screener" / "scripts" / "screener.py"
MARKET = S / "market" / "scripts" / "market.py"
SMART = S / "smart-money" / "scripts" / "smartmoney.py"
COMMITTEE = S / "committee" / "scripts" / "committee.py"

# ticker, market -> the Wikipedia article it must land on
STORIES = [("AAPL", "US", "Apple Inc."), ("XOM", "US", "ExxonMobil"), ("BRK.B", "US", "Berkshire Hathaway"),
           ("THYAO", "BIST", "Turkish Airlines"), ("ASELS", "BIST", "Aselsan"), ("EREGL", "BIST", "Erdemir"),
           ("TUPRS", "BIST", "Tüpraş")]

US = ["AAPL", "MSFT", "BRK.B", "JPM", "V", "TSM", "BABA", "XOM", "KO"]
BIST = ["THYAO", "PGSUS", "GARAN", "ASELS", "BIMAS", "KCHOL", "TUPRS", "EREGL"]

# (path in JSON, low, high): values outside are reported as suspicious.
RANGES = [
    (("growth", "revenue_cagr_pct"), -60, 200),
    (("profitability", "operating_margin_pct"), -100, 90),
    (("profitability", "roe_pct"), -100, 200),
    (("valuation", "pb"), 0, 150),
    (("valuation", "ev_ebitda"), 0, 150),
    (("valuation", "fcf_yield_pct"), -50, 40),
    (("valuation", "dividend_yield_pct"), 0, 25),
]


def call(script, *args, env=None):
    r = subprocess.run([sys.executable, str(script), *args], capture_output=True, timeout=300, env=env)
    out = r.stdout.decode("utf-8", "replace").strip()
    try:
        return json.loads(out.splitlines()[-1]), r.stderr.decode("utf-8", "replace").strip()
    except (ValueError, IndexError):
        return {"error": f"not JSON: {out[:200]}"}, r.stderr.decode("utf-8", "replace")


def dig(d, path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def check_ticker(t, market):
    issues = []
    m = ["--market", market]
    for name, script, args in (("quote", DESK, ["quote", t, *m]), ("profile", DESK, ["profile", t, *m]),
                               ("financials", DESK, ["financials", t, *m]),
                               ("fundamentals", FUND, [t, *m]), ("technicals", TECH, [t, *m])):
        res, err = call(script, *args)
        if "error" in res:
            issues.append(f"{name}: ERROR {res['error']}")
            continue
        if err:
            issues.append(f"{name}: wrote to stderr: {err[:120]}")
        if name == "fundamentals":
            for path, lo, hi in RANGES:
                v = dig(res, path)
                if v is not None and not lo <= v <= hi:
                    issues.append(f"suspicious {'.'.join(path)} = {v}")
            summary = (f"cur={res['currency']} fin={res['financial_company']} "
                       f"cagr={dig(res, ('growth', 'revenue_cagr_pct'))} "
                       f"opm={dig(res, ('profitability', 'operating_margin_pct'))} "
                       f"pb={dig(res, ('valuation', 'pb'))} ev/ebitda={dig(res, ('valuation', 'ev_ebitda'))} "
                       f"fcfy={dig(res, ('valuation', 'fcf_yield_pct'))}")
        if name == "technicals":
            rs = res["relative_strength_vs_benchmark_pp"]
            if "error" in rs:
                issues.append(f"technicals: {rs['error']}")
            rsi = res["momentum"]["rsi14"]
            if rsi is None or not 0 <= rsi <= 100:
                issues.append(f"bad RSI {rsi}")
    return issues, locals().get("summary", "")


def expect_error(label, script, *args):
    res, _ = call(script, *args)
    ok = "error" in res and "Traceback" not in res["error"]
    print(f"{'ok ' if ok else 'BAD'} {label}: {res.get('error', res)}"[:200])
    return ok


def main():
    only = sys.argv[1:]
    failures = 0
    todo = [(t, "US") for t in US] + [(t, "BIST") for t in BIST]
    for t, market in todo:
        if only and t not in only:
            continue
        issues, summary = check_ticker(t, market)
        failures += any("ERROR" in i for i in issues)
        print(f"{'ok ' if not issues else '!! '} {market:4} {t:6} {summary}")
        for i in issues:
            print(f"        {i}")
    if not only:
        print("-- macro, global, filings, error paths")
        for args in (["macro"], ["global"], ["macro", "--market", "BIST"]):
            res, _ = call(DESK, *args)
            bad = [k for k, v in res.items() if isinstance(v, dict) and "error" in v]
            failures += bool(bad) or "error" in res
            print(f"{'ok ' if not bad and 'error' not in res else 'BAD'} {' '.join(args)}: {len(res)} items, failed: {bad}")
        for t, market in (("THYAO", "BIST"), ("AAPL", "US")):
            res, _ = call(DESK, "returns", t, "--market", market)
            one = res.get("1y", {})
            good = "error" not in res and "real_pct" in one
            failures += not good
            print(f"{'ok ' if good else 'BAD'} returns {t}: {one}")
        if os.environ.get("DESK_SEC_USER_AGENT"):
            for t in ("AAPL", "MSFT", "KO", "PG", "V"):
                res, _ = call(DESK, "verify", t)
                good = res.get("status") == "checked" and res.get("confidence") != "low"
                failures += not good
                print(f"{'ok ' if good else 'BAD'} verify {t}: {res.get('matched')} {res.get('confidence')} {res.get('differences') or res.get('reason', '')}"[:200])
            res, _ = call(DESK, "filings", "BRK.B", "--forms", "10-K", "--limit", "1")
            failures += "error" in res
            print(f"{'ok ' if 'error' not in res else 'BAD'} filings BRK.B: {res.get('filings', res)}"[:200])
        print("-- company story, news")
        for t, market, title in STORIES:
            res, _ = call(STORY, t, "--market", market)
            w, m = res.get("wikipedia", {}), res.get("market_history", {})
            good = w.get("title") == title and "error" not in m
            failures += not good
            print(f"{'ok ' if good else 'BAD'} story {t}: {w.get('title') or w} ({w.get('matched_by')}), "
                  f"prices from {m.get('first_price_date')}, deepest {dig(m, ('deepest_falls',))[:1] if m.get('deepest_falls') else m}"[:200])
        for t, market in (("AAPL", "US"), ("THYAO", "BIST")):
            res, _ = call(NEWS, t, "--market", market, "--limit", "5")
            n = res.get("news", {})
            good = n.get("found", 0) >= 3 and not n.get("source_errors")
            failures += not good
            print(f"{'ok ' if good else 'BAD'} news {t}: {n.get('found')} items, {n.get('topic_counts')} {n.get('source_errors', '')}"[:200])
        print("-- scenarios")
        for t, market in (("AAPL", "US"), ("NVDA", "US"), ("JPM", "US"), ("KO", "US"), ("TSLA", "US"),
                          ("THYAO", "BIST")):
            res, _ = call(SCEN, "build", t, "--market", market)
            px = [dig(res, ("cases", c, "price")) for c in ("bear", "base", "bull")]
            good = "error" not in res and None not in px and px[0] <= px[1] <= px[2]
            failures += not good
            print(f"{'ok ' if good else 'BAD'} scenarios {t}: {res.get('method')} price {res.get('price')} "
                  f"bear/base/bull {px} {res.get('error', '')}"[:200])
        failures += not expect_error("ADR refused", SCEN, "build", "TSM")
        print("-- portfolio (in a temporary folder, never the user's own)")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DESK_HOME": tmp}
            for args in (("add", "AAPL", "10", "125.07", "--date", "2023-01-03", "--thesis", "t", "--sell-if", "s"),
                         ("add", "THYAO", "300", "130.8", "--market", "BIST", "--date", "2023-02-01"),
                         ("add", "PLTR", "100", "7.78", "--date", "2023-05-01"),
                         ("sell", "PLTR", "50", "67.26", "--date", "2025-01-10", "--reason", "r")):
                res, _ = call(PORT, *args, env=env)
                failures += "error" in res
            for cmd in ("show", "stress", "review"):
                res, err = call(PORT, cmd, env=env)
                good = "error" not in res and not err
                if cmd == "stress":
                    moves = [e["portfolio_pct"] for e in res.get("past_crashes", [])]
                    good = good and all(m is not None and -100 < m < 0 for m in moves)
                failures += not good
                summary = (f"{res.get('value_usd')} USD, {len(res.get('holdings', []))} holdings" if cmd == "show" else
                           [(e["episode"], e["portfolio_pct"]) for e in res.get("past_crashes", [])] if cmd == "stress" else
                           f"{len(res.get('flags', []))} flags, disposition {dig(res, ('disposition', 'reads'))}")
                print(f"{'ok ' if good else 'BAD'} portfolio {cmd}: {res.get('error') or summary} {err[:80]}"[:200])
            res, err = call(PORT, "check", "MSFT", "10", "--stop", "1", env=env)
            good = "error" not in res and len(res.get("checks", [])) == 3
            failures += not good
            print(f"{'ok ' if good else 'BAD'} portfolio check: {res.get('error') or res.get('verdict')}"[:200])
        print("-- backtest, screener, market")
        res, err = call(TECH, "SPY", "--backtest")
        good = "error" not in res and len(res.get("rules", {})) == 5 and dig(res, ("buy_and_hold", "cagr_pct"))
        failures += not good
        print(f"{'ok ' if good else 'BAD'} backtest SPY: buy-and-hold {dig(res, ('buy_and_hold', 'cagr_pct'))}% a year, "
              f"trend_200d {dig(res, ('rules', 'trend_200d', 'cagr_pct'))}% {res.get('error', '')}"[:200])
        for args in (("--preset", "quality"), ("--preset", "momentum"), ("--universe", "sp600", "--preset", "value"),
                     ("--tickers", "AAPL", "BRK.B", "JPM", "--sort", "pe")):
            res, err = call(SCREEN, "run", *args, "--top", "5")
            rows = res.get("rows", [])
            pes = [r.get("pe") for r in rows if r.get("pe") is not None]
            good = "error" not in res and res.get("scanned", 0) >= (3 if "--tickers" in args else 300) \
                and rows and all(0 < x < 500 for x in pes)
            failures += not good
            print(f"{'ok ' if good else 'BAD'} screener {' '.join(args)}: {res.get('matches')} of {res.get('scanned')}, "
                  f"top {[r['ticker'] for r in rows]} {res.get('error', '')}"[:200])
        res, err = call(MARKET, "regime")
        missing = [k for k, v in res.get("signals", {}).items() if v == "missing"]
        good = "error" not in res and not missing and res.get("posture")
        failures += not good
        print(f"{'ok ' if good else 'BAD'} market regime: {res.get('posture')} on={res.get('risk_on')} "
              f"off={res.get('risk_off')} missing={missing} {res.get('error', '')}"[:200])
        res, err = call(MARKET, "calendar", "--days", "10", "--tickers", "NVDA")
        good = "error" not in res and not res.get("errors") and res.get("next_fed_decision")
        failures += not good
        print(f"{'ok ' if good else 'BAD'} market calendar: {len(res.get('us_releases', []))} releases, "
              f"next Fed {res.get('next_fed_decision')} {res.get('errors', '')}"[:200])
        if os.environ.get("DESK_SEC_USER_AGENT"):
            print("-- smart money")
            res, _ = call(SMART, "fund", "berkshire")
            hold = res.get("holdings", [])
            mapped = sum(1 for h in hold if h.get("ticker"))
            good = "error" not in res and len(hold) >= 10 and mapped >= len(hold) - 2
            failures += not good
            print(f"{'ok ' if good else 'BAD'} 13F berkshire: {res.get('quarter_end')}, {res.get('positions')} stocks, "
                  f"{mapped}/{len(hold)} tickers, top {[h.get('ticker') for h in hold[:5]]} {res.get('error', '')}"[:200])
            for t in ("AAPL", "BRK.B"):
                res, _ = call(SMART, "insiders", t, "--days", "120")
                good = "error" not in res and "open_market_sales" in res
                failures += not good
                print(f"{'ok ' if good else 'BAD'} insiders {t}: {res.get('form4_filings')} filings, buys "
                      f"{res.get('open_market_buys')}, sales {dig(res, ('open_market_sales', 'value_usd'))} "
                      f"{res.get('error', '')}"[:200])
            res, _ = call(SMART, "congress", "--days", "30")
            good = "error" not in res and res.get("reports_read", 0) > 0 and res.get("stock_trades", 0) > 0
            failures += not good
            print(f"{'ok ' if good else 'BAD'} congress 30 days: {res.get('reports_read')} reports, "
                  f"{res.get('stock_trades')} trades, top {[r['ticker'] for r in res.get('most_bought', [])[:5]]} "
                  f"{res.get('error', '')}"[:200])
        print("-- committee (in a temporary folder)")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DESK_HOME": tmp}
            res, _ = call(COMMITTEE, "gather", "AAPL", env=env)
            sec = res.get("sections", {})
            allowed = {"insiders"} if not os.environ.get("DESK_SEC_USER_AGENT") else set()
            good = "error" not in res and not (set(res.get("missing", {})) - allowed) and len(sec) >= 7
            failures += not good
            print(f"{'ok ' if good else 'BAD'} committee gather AAPL: {sorted(sec)} missing {res.get('missing')} "
                  f"{res.get('error', '')}"[:200])
            if good:
                f, t, sc = sec["fundamentals"], sec["technicals"], sec["scenarios"]
                pt = lambda c, src: {"claim": c, "source": src}  # noqa: E731
                views = {
                    "bull": {"thesis": "t", "points": [
                        pt(f"Operating margin is {dig(f, ('profitability', 'operating_margin_pct'))}%.", "fundamentals")]},
                    "bear": {"thesis": "t", "points": [
                        pt(f"The bear case ends near {dig(sc, ('cases', 'bear', 'price'))}.", "scenarios"),
                        pt(f"P/E is {dig(f, ('valuation', 'pe_ttm'))}.", "fundamentals"),
                        pt(f"RSI is {dig(t, ('momentum', 'rsi14'))} and P/E is 97.13.", "technicals")]},
                    "risk": {"thesis": "t", "points": [
                        pt(f"ATR is {dig(t, ('volatility', 'atr14_pct'))}%.", "technicals")]},
                    "chair": {"leans": "split", "summary": "s", "would_change_mind": "w"}}
                Path(res["views_file"]).write_text(json.dumps(views), encoding="utf-8")
                out, _ = call(COMMITTEE, "report", "AAPL", env=env)
                page = Path(out.get("report", "")).read_text(encoding="utf-8") if out.get("built") else ""
                flagged = [n for u in out.get("unverified_numbers", []) for n in u["numbers"]]
                good = out.get("built") and "<polyline" in page and "Bear analyst" in page and flagged == ["97.13"]
                failures += not good
                print(f"{'ok ' if good else 'BAD'} committee report: built {out.get('built')}, "
                      f"{len(page)} bytes, flagged {flagged} {out.get('errors', '')} {out.get('error', '')}"[:200])
        failures += not expect_error("unknown ticker", DESK, "quote", "ZZZZQQ")
        failures += not expect_error("ETF has no statements", FUND, "SPY")
        failures += not expect_error("unknown market", DESK, "quote", "AAPL", "--market", "LSE")
    print(f"\n{'PASS' if not failures else f'FAIL ({failures})'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
