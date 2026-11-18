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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "skills"
DESK = S / "desk-data" / "scripts" / "desk.py"
FUND = S / "fundamentals" / "scripts" / "fundamentals.py"
TECH = S / "technicals" / "scripts" / "technicals.py"

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


def call(script, *args):
    r = subprocess.run([sys.executable, str(script), *args], capture_output=True, timeout=180)
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
        failures += not expect_error("unknown ticker", DESK, "quote", "ZZZZQQ")
        failures += not expect_error("ETF has no statements", FUND, "SPY")
        failures += not expect_error("unknown market", DESK, "quote", "AAPL", "--market", "LSE")
    print(f"\n{'PASS' if not failures else f'FAIL ({failures})'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
