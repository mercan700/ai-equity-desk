"""Offline tests: synthetic data with answers worked out by hand. No network needed.

Run from the repo root:  python -m unittest discover -s tests -v
"""
import importlib.util
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.environ["DESK_HOME"] = tempfile.mkdtemp(prefix="desk-test-")
sys.path.insert(0, str(ROOT / "skills" / "desk-data" / "scripts"))

from deskcore import (DeskError, bis, cache, frames, macro, markets, news, prices, returns,  # noqa: E402
                      universe, verify, wiki)
from deskcore.cli import friendly_error  # noqa: E402


def load_script(rel):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fundamentals = load_script("skills/fundamentals/scripts/fundamentals.py")
technicals = load_script("skills/technicals/scripts/technicals.py")
story = load_script("skills/company-story/scripts/story.py")
scen = load_script("skills/scenarios/scripts/scenarios.py")
port = load_script("skills/portfolio/scripts/portfolio.py")
screener = load_script("skills/screener/scripts/screener.py")
market = load_script("skills/market/scripts/market.py")
smart = load_script("skills/smart-money/scripts/smartmoney.py")


def frame(closes, start="2024-01-02", volume=1_000_000):
    idx = pd.bdate_range(start, periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": volume})


class Patch:
    """Swap a module attribute for the duration of a with-block."""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)


class Markets(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(markets.symbol("aapl"), "AAPL")
        self.assertEqual(markets.symbol("BRK.B"), "BRK-B")
        self.assertEqual(markets.symbol("thyao", "BIST"), "THYAO.IS")
        self.assertEqual(markets.symbol("THYAO.IS", "bist"), "THYAO.IS")
        self.assertEqual(markets.symbol("^GSPC", "BIST"), "^GSPC")
        self.assertEqual(markets.symbol("USDTRY=X"), "USDTRY=X")
        self.assertEqual(markets.symbol("DX-Y.NYB"), "DX-Y.NYB")

    def test_bad_input(self):
        with self.assertRaises(DeskError):
            markets.symbol("  ")
        with self.assertRaises(DeskError):
            markets.symbol("AAPL", "LSE")


class Cache(unittest.TestCase):
    def test_round_trip_and_expiry(self):
        cache.put_json("profile", "X", {"a": 1})
        self.assertEqual(cache.get_json("profile", "X"), {"a": 1})
        path = cache.path_for("profile", "X")
        os.utime(path, (0, 0))  # pretend the file is from 1970
        self.assertIsNone(cache.get_json("profile", "X"))

    def test_odd_keys_make_safe_paths(self):
        p = cache.path_for("quote", "DX-Y.NYB:1y:1d/../x")
        self.assertNotIn("/..", p.name)
        self.assertTrue(str(p).startswith(str(cache.CACHE_DIR)))


class Quote(unittest.TestCase):
    def test_returns_and_ytd(self):
        # 2024: flat at 100; 2025: rises 1 per day from 101.
        idx = pd.bdate_range("2024-12-02", "2025-03-31")
        closes = [100.0 if d.year == 2024 else 0.0 for d in idx]
        n25 = sum(d.year == 2025 for d in idx)
        closes[-n25:] = [101.0 + i for i in range(n25)]
        df = pd.DataFrame({"Close": closes, "Volume": 10}, index=idx)
        with Patch(prices, "load_history", lambda *a, **k: (df, None)):
            q = prices.quote("TEST")
        last = closes[-1]
        self.assertEqual(q["close"], last)
        self.assertAlmostEqual(q["change_pct"]["ytd"], round((last / 100 - 1) * 100, 2))
        self.assertAlmostEqual(q["change_pct"]["1d"], round((last / (last - 1) - 1) * 100, 2))
        self.assertEqual(q["high_52w"], last)
        self.assertEqual(q["from_high_pct"], 0.0)

    def test_nan_rows_are_ignored(self):
        df = frame([np.nan, 10, 11, 12])
        with Patch(prices, "load_history", lambda *a, **k: (df, None)):
            q = prices.quote("TEST")
        self.assertEqual(q["close"], 12)
        self.assertAlmostEqual(q["change_pct"]["1y"], 20.0)


class History(unittest.TestCase):
    def test_cagr_and_drawdown(self):
        idx = pd.to_datetime(["2020-01-01", "2020-06-01", "2021-01-01", "2022-01-01"])
        df = pd.DataFrame({"Close": [100, 50, 150, 200], "Volume": 1}, index=idx)
        with Patch(prices, "load_history", lambda *a, **k: (df, "x.csv")):
            h = prices.history_summary("T", period="max")
        years = (idx[-1] - idx[0]).days / 365.25
        self.assertEqual(h["total_return_pct"], 100.0)
        self.assertAlmostEqual(h["cagr_pct"], round((2 ** (1 / years) - 1) * 100, 2))
        self.assertEqual(h["max_drawdown_pct"], -50.0)
        self.assertEqual(h["max_drawdown_date"], "2020-06-01")


class Statements(unittest.TestCase):
    def test_rows_to_millions(self):
        df = pd.DataFrame({pd.Timestamp("2025-12-31"): [2.5e9, 1.23, np.nan]},
                          index=["Total Revenue", "Diluted EPS", "Net Income"])
        out = prices._rows(df, ["Total Revenue", "Diluted EPS", "Net Income", "EBITDA"])
        self.assertEqual(out, {"2025-12-31": {"Total Revenue": 2500.0, "Diluted EPS": 1.23, "Net Income": None}})


# A company with 4 income years, an extra (older) balance-sheet-only year,
# statements in USD and shares trading in TRY at USD/TRY = 40.
STMTS = {
    "2021-12-31": {"Total Assets": 900.0},
    "2022-12-31": {"Total Revenue": 1000.0, "Diluted EPS": 1.0, "Diluted Average Shares": 100.0},
    "2023-12-31": {"Total Revenue": 1100.0, "Diluted EPS": 1.1, "Diluted Average Shares": 100.0},
    "2024-12-31": {"Total Revenue": 1210.0, "Diluted EPS": 1.2, "Diluted Average Shares": 98.0},
    "2025-12-31": {"Total Revenue": 1331.0, "Gross Profit": 532.4, "Operating Income": 266.2,
                   "EBITDA": 300.0, "Net Income": 200.0, "Diluted EPS": 1.33,
                   "Diluted Average Shares": 96.0, "Total Debt": 500.0,
                   "Cash And Cash Equivalents": 200.0, "Stockholders Equity": 1000.0,
                   "Capital Expenditure": -50.0, "Free Cash Flow": 190.0},
}


def fake_financials(ticker, market="US", quarterly=False, periods=4):
    with Patch(cache, "get_json", lambda kind, key: STMTS), Patch(cache, "put_json", lambda *a: None):
        return ORIGINAL_FINANCIALS(ticker, market, quarterly, periods)


ORIGINAL_FINANCIALS = prices.financials


def fake_profile(industry="Airlines", currency="TRY", fin_currency="USD"):
    return lambda ticker, market="US", summary_chars=600: {
        "symbol": "TEST", "name": "Test Co", "sector": "Industrials", "industry": industry,
        "currency": currency, "financial_currency": fin_currency,
        "market_cap": 2_000 * 40 * 1e6,  # 2,000m USD expressed in TRY
        "pe_ttm": 10.0, "pe_forward": 9.0, "dividend_yield": 1.5}


class Fundamentals(unittest.TestCase):
    def run_analyze(self, **profile_kw):
        fx = lambda sym, market="US": {"close": 40.0}  # noqa: E731
        with Patch(prices, "financials", fake_financials), \
             Patch(prices, "profile", fake_profile(**profile_kw)), \
             Patch(prices, "quote", fx):
            return fundamentals.analyze("TEST", "BIST")

    def test_growth_uses_dates_not_column_count(self):
        r = self.run_analyze()
        self.assertEqual(r["latest_fiscal_year"], "2025-12-31")
        self.assertEqual(r["growth"]["years"], 3.0)
        self.assertAlmostEqual(r["growth"]["revenue_cagr_pct"], 10.0, places=1)
        self.assertEqual(r["growth"]["signal"], "strong")

    def test_ratios_and_currency_conversion(self):
        r = self.run_analyze()
        v, b, c, p = r["valuation"], r["balance_sheet"], r["cash_quality"], r["profitability"]
        self.assertEqual(r["currency"], "USD")
        self.assertEqual(v["market_cap_millions"], 2000)
        self.assertEqual(v["pb"], 2.0)                       # 2000 / 1000
        self.assertEqual(v["ev_ebitda"], 7.67)               # (2000 + 300) / 300
        self.assertEqual(v["fcf_yield_pct"], 9.5)            # 190 / 2000
        self.assertIn("USD/TRY 40.0", v["currency_note"])
        self.assertEqual(b["net_debt_millions"], 300.0)
        self.assertEqual(b["net_debt_to_ebitda"], 1.0)
        self.assertEqual(b["signal"], "strong")  # 1.0x is the edge of "strong" (<= 1x)
        self.assertEqual(b["share_count_change_pct"], -4.0)  # 96 vs 100
        self.assertEqual(c["fcf_to_net_income"], 0.95)
        self.assertEqual(c["signal"], "strong")
        self.assertEqual(p["operating_margin_pct"], 20.0)
        self.assertEqual(p["signal"], "strong")

    def test_bank_skips_non_bank_metrics(self):
        r = self.run_analyze(industry="Banks - Regional", currency="USD", fin_currency="USD")
        self.assertTrue(r["financial_company"])
        self.assertIsNone(r["valuation"]["ev_ebitda"])
        self.assertTrue(r["cash_quality"]["signal"].startswith("n/a"))

    def test_payment_network_is_not_a_bank(self):
        self.assertFalse(fundamentals.is_financial("Credit Services"))
        self.assertFalse(fundamentals.is_financial("Asset Management"))
        self.assertTrue(fundamentals.is_financial("Insurance - Life"))
        self.assertTrue(fundamentals.is_financial("Capital Markets"))

    def test_grades(self):
        self.assertEqual(fundamentals.grade(None, 1, 2), "n/a")
        self.assertEqual(fundamentals.grade(0.5, 1, 3, higher_is_better=False), "strong")
        self.assertEqual(fundamentals.grade(2.0, 1, 3, higher_is_better=False), "ok")
        self.assertEqual(fundamentals.grade(4.0, 1, 3, higher_is_better=False), "weak")

    def test_peer_gaps(self):
        target = {"valuation": {"pe_ttm": 20, "ev_ebitda": 10, "pb": 2, "fcf_yield_pct": 5},
                  "profitability": {"operating_margin_pct": 30, "roe_pct": 20},
                  "growth": {"revenue_cagr_pct": 10}}
        peer = lambda s, pe: {"symbol": s, "valuation": {"pe_ttm": pe, "ev_ebitda": 10, "pb": 2, "fcf_yield_pct": 4},  # noqa: E731
                              "profitability": {"operating_margin_pct": 20, "roe_pct": 15},
                              "growth": {"revenue_cagr_pct": 5}}
        out = fundamentals.compare(target, [peer("A", 10), peer("B", 30), peer("C", None)])
        gaps = out["median_and_gap"]
        self.assertEqual(gaps["pe_ttm"], 20.0)
        self.assertEqual(gaps["pe_ttm_target_vs_median_pct"], 0.0)
        self.assertEqual(gaps["operating_margin_pct_target_minus_median"], 10.0)


class Technicals(unittest.TestCase):
    def setUp(self):
        self.patch = Patch(returns, "real_returns", lambda *a, **k: {"1y": {}})
        self.patch.__enter__()

    def tearDown(self):
        self.patch.__exit__()

    def test_rsi_extremes(self):
        up = pd.Series(np.arange(1, 60, dtype=float))
        self.assertAlmostEqual(technicals.rsi(up).iloc[-1], 100.0)
        down = pd.Series(np.arange(60, 1, -1, dtype=float))
        self.assertAlmostEqual(technicals.rsi(down).iloc[-1], 0.0)

    def test_last_cross(self):
        idx = pd.bdate_range("2025-01-01", periods=6)
        fast = pd.Series([1, 1, 3, 3, 0, 0], index=idx, dtype=float)
        slow = pd.Series([2] * 6, index=idx, dtype=float)
        x = technicals.last_cross(fast, slow)
        self.assertEqual(x["type"], "bearish")
        self.assertEqual(x["date"], str(idx[4].date()))
        self.assertEqual(x["bars_ago"], 1)

    def test_uptrend_and_benchmark(self):
        stock = frame(np.linspace(100, 200, 300))
        bench = frame(np.linspace(100, 150, 300))

        def hist(sym, *a, **k):
            return (bench if sym.startswith("^") else stock), None

        with Patch(prices, "load_history", hist):
            r = technicals.analyze("TEST")
        self.assertTrue(r["trend"]["label"].startswith("uptrend"))
        self.assertGreater(r["relative_strength_vs_benchmark_pp"]["1y"], 0)
        self.assertEqual(r["levels"]["from_52w_high_pct"], 0.0)

    def test_benchmark_failure_keeps_report(self):
        stock = frame(np.linspace(100, 200, 300))

        def hist(sym, *a, **k):
            if sym.startswith("^"):
                raise DeskError("no benchmark")
            return stock, None

        with Patch(prices, "load_history", hist):
            r = technicals.analyze("TEST")
        self.assertIn("error", r["relative_strength_vs_benchmark_pp"])
        self.assertIn("trend", r)

    def test_too_little_history(self):
        with Patch(prices, "load_history", lambda *a, **k: (frame(range(1, 100)), None)):
            with self.assertRaises(DeskError):
                technicals.analyze("NEW")

    def test_swing_levels(self):
        # Zig-zag between 90 and 110 with the last close at 100.
        wave = [100 + 10 * math.sin(i / 5) for i in range(150)] + [100.0]
        sup, res = technicals.swing_levels(frame(wave), 100.0)
        self.assertTrue(sup and res)
        self.assertTrue(all(s["level"] < 100 for s in sup))
        self.assertTrue(all(r["level"] > 100 for r in res))


class Macro(unittest.TestCase):
    def test_yoy_and_rate_change(self):
        idx = pd.date_range("2024-01-01", periods=25, freq="MS")
        cpi = pd.Series(np.linspace(100, 110, 25), index=idx)
        rate = pd.Series(np.linspace(5, 3, 25), index=idx)
        with Patch(macro, "series", lambda code: cpi if code == "CPIAUCSL" else rate):
            out = macro.snapshot(["CPIAUCSL", "FEDFUNDS"])
        self.assertAlmostEqual(out["CPIAUCSL"]["yoy_pct"], round((110 / cpi.iloc[-13] - 1) * 100, 2))
        self.assertAlmostEqual(out["FEDFUNDS"]["change_1y_pp"], round(3 - rate.iloc[-13], 2))


class Fallbacks(unittest.TestCase):
    def test_debt(self):
        self.assertEqual(prices.debt_of({"Total Debt": 5.0, "Long Term Debt": 9.0}), 5.0)
        self.assertEqual(prices.debt_of({"Total Debt": None, "Long Term Debt": 9.0, "Current Debt": 1.0}), 10.0)
        self.assertIsNone(prices.debt_of({}))

    def test_ebitda(self):
        self.assertEqual(fundamentals.ebitda_of({"EBITDA": 7.0, "Normalized EBITDA": 8.0}), 7.0)
        self.assertEqual(fundamentals.ebitda_of({"Normalized EBITDA": 8.0}), 8.0)
        self.assertEqual(fundamentals.ebitda_of({"Operating Income": 3.0, "Reconciled Depreciation": 2.0}), 5.0)
        self.assertIsNone(fundamentals.ebitda_of({"Operating Income": 3.0}))

    def test_caveats(self):
        self.assertEqual(fundamentals.caveats("Software - Application", "USD", {"fcf_yield_pct": 3}), [])
        notes = fundamentals.caveats("Airlines", "TRY", {"fcf_yield_pct": 41})
        self.assertEqual(len(notes), 3)


class RealReturns(unittest.TestCase):
    def test_try_usd_and_real(self):
        # Over exactly one year the stock doubles in TRY, the lira halves against
        # the dollar and consumer prices rise 50%.
        idx = pd.bdate_range(end="2026-11-18", periods=400)
        stock = pd.DataFrame({"Close": np.where(idx <= idx[-1] - pd.DateOffset(years=1), 100.0, 200.0)}, index=idx)
        fx = pd.DataFrame({"Close": np.where(idx <= idx[-1] - pd.DateOffset(years=1), 20.0, 40.0)}, index=idx)
        months = pd.period_range("2024-01", "2026-09", freq="M")
        cpi = pd.Series(np.where(months <= pd.Period("2025-09", "M"), 100.0, 150.0), index=months)

        def hist(sym, *a, **k):
            return (fx if sym.endswith("=X") else stock), None

        with Patch(prices, "load_history", hist), Patch(bis, "cpi_index", lambda c: cpi):
            r = returns.real_returns("TEST", "BIST")
        self.assertEqual(r["1y"]["try_pct"], 100.0)
        self.assertEqual(r["1y"]["usd_pct"], 0.0)
        self.assertEqual(r["1y"]["inflation_pct"], 50.0)
        self.assertEqual(r["1y"]["real_pct"], 33.33)
        self.assertEqual(r["inflation_lag_months"], 2)
        self.assertNotIn("3y_annualized", r)  # not enough history

    def test_missing_cpi_still_gives_nominal(self):
        stock = frame(np.linspace(100, 200, 300))

        def no_cpi(country):
            raise DeskError("BIS down")

        with Patch(prices, "load_history", lambda *a, **k: (stock, None)), Patch(bis, "cpi_index", no_cpi):
            r = returns.real_returns("TEST", "US")
        self.assertIn("usd_pct", r["1y"])
        self.assertNotIn("real_pct", r["1y"])


class Verification(unittest.TestCase):
    FACTS = {
        "Revenues": {"units": {"USD": [
            {"start": "2024-01-01", "end": "2024-12-31", "val": 1000e6, "form": "10-K", "filed": "2025-02-01"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": 1010e6, "form": "10-K", "filed": "2026-02-01"},
            {"start": "2024-10-01", "end": "2024-12-31", "val": 300e6, "form": "10-K", "filed": "2025-02-01"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": 999e6, "form": "8-K", "filed": "2025-03-01"},
        ]}},
    }

    def test_annual_values_keep_latest_filing_and_skip_quarters(self):
        out = verify._annual(self.FACTS, ["Revenues"], instant=False)
        self.assertEqual(out, {"2024-12-31": (1010e6, "2026-02-01")})

    def test_nearest_date(self):
        self.assertEqual(verify._nearest({"2026-01-25": 5}, "2026-01-31"), 5)
        self.assertIsNone(verify._nearest({"2025-12-31": 5}, "2026-06-30"))

    def test_check_counts_matches_and_differences(self):
        sec_data = {"Total Revenue": {"2025-12-31": 1000e6}, "Net Income": {"2025-12-31": 100e6},
                    "Diluted EPS": {"2025-12-31": 1.5}}
        stmts = {"2025-12-31": {"Total Revenue": 1005.0, "Net Income": 120.0, "Diluted EPS": 1.5}}
        with Patch(verify, "sec_annuals", lambda t: sec_data):
            r = verify.check("TEST", stmts)
        self.assertEqual(r["matched"], "2/3")
        self.assertEqual(r["confidence"], "low")
        self.assertEqual(r["differences"][0]["item"], "Net Income")
        self.assertEqual(r["differences"][0]["diff_pct"], 20.0)

    def test_sec_failure_is_reported_not_raised(self):
        def boom(t):
            raise DeskError("no user agent")

        with Patch(verify, "sec_annuals", boom):
            self.assertEqual(verify.check("X", {})["status"], "not checked")


class Errors(unittest.TestCase):
    def test_messages(self):
        class YFRateLimitError(Exception):
            pass
        self.assertIn("rate-limiting", friendly_error(YFRateLimitError()))
        self.assertEqual(friendly_error(DeskError("plain")), "plain")


class WikiText(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(wiki.clean_name("Türk Hava Yollari Anonim Ortakligi"), "Türk Hava Yollari")
        self.assertEqual(wiki.clean_name("Koç Holding A.S."), "Koç Holding")
        self.assertEqual(wiki.clean_name("Eregli Demir ve Celik Fabrikalari T.A.S."), "Eregli Demir ve Celik Fabrikalari")
        self.assertEqual(wiki.clean_name("Apple Inc."), "Apple")

    def test_norm_folds_turkish(self):
        self.assertEqual(wiki.norm("Türk Hava Yolları"), wiki.norm("Turk Hava Yollari"))

    def test_sections_and_history(self):
        text = ("Lead text.\n\n== History ==\nFounded in 1933.\n\n=== Privatisation ===\nSold in 2006.\n\n"
                "== Fleet ==\nMany planes.")
        secs = wiki.split_sections(text)
        self.assertEqual([h for h, _, _ in secs], ["", "History", "Privatisation", "Fleet"])
        h = wiki.history_text(secs, 1000)
        self.assertIn("1933", h)
        self.assertIn("[Privatisation] Sold in 2006.", h)
        self.assertNotIn("planes", h)
        self.assertTrue(wiki.history_text(secs, 12).endswith("..."))

    def test_pick(self):
        hits = [
            {"title": "Apple", "snippet": "The apple is a round edible fruit"},
            {"title": "List of Turkish companies", "snippet": "Türk Hava Yolları company"},
            {"title": "Türkiye İş Bankası", "snippet": "a bank; Sanayi ve Ticaret holdings"},
            {"title": "Turkish Airlines", "snippet": "Türk Hava Yolları is the flag carrier airline"},
        ]
        self.assertEqual(wiki.pick(hits, "Türk Hava Yollari"), "Turkish Airlines")
        self.assertIsNone(wiki.pick(hits[:1], "Apple"))  # fruit, not a company
        # two generic shared words are not enough
        self.assertIsNone(wiki.pick(hits[2:3], "Aselsan Elektronik Sanayi ve Ticaret"))


class Story(unittest.TestCase):
    def test_drawdowns(self):
        c = pd.Series([100, 50, 100, 120, 60, 90], index=pd.bdate_range("2024-01-01", periods=6), dtype=float)
        d = story.drawdowns(c)
        self.assertEqual(d[0]["fall_pct"], -50.0)
        self.assertEqual(len(d), 2)
        self.assertEqual(d[0]["recovered"], "2024-01-03")  # first fall recovers; listed first by date tie
        self.assertEqual([x["recovered"] for x in d if x["peak"] == "2024-01-04"], ["not yet"])

    def test_bad_jumps_trimmed(self):
        closes = [5000.0] * 300 + [5.0] * 10 + list(np.linspace(5, 10, 400))
        with Patch(prices, "load_history", lambda *a, **k: (frame(closes), None)):
            m = story.market_history("X.IS")
        self.assertIn("data_warning", m)
        self.assertTrue(m["deepest_falls"] == [] or m["deepest_falls"][0]["fall_pct"] > -10)

    def test_real_crash_kept(self):
        closes = [100.0] * 50 + [48.0] * 50  # -52% in a day, like Apple in Sept 2000
        with Patch(prices, "load_history", lambda *a, **k: (frame(closes), None)):
            m = story.market_history("X")
        self.assertNotIn("data_warning", m)
        self.assertEqual(m["deepest_falls"][0]["fall_pct"], -52.0)


class News(unittest.TestCase):
    def test_topics(self):
        self.assertIn("earnings", news.topics("THYAO 3. çeyrek bilanço yorumu"))
        self.assertIn("capital", news.topics("Garanti Bankası pay geri alımı yaptı"))
        self.assertIn("trading_flow", news.topics("hisselerinde yüklü alım"))
        self.assertIn("rating", news.topics("Morgan Stanley upgrades Apple, raises price target"))
        self.assertEqual(news.topics("I lived with it for a week"), [])

    def test_relevance(self):
        words = news.name_words("Türk Hava Yollari Anonim Ortakligi")
        self.assertTrue(news.relevant("THYAO hissesi yükseldi", "THYAO", words))
        self.assertTrue(news.relevant("Türk Hava Yolları yolcu sayısı", "THYAO", words))
        self.assertFalse(news.relevant("Türk Telekom yeni tarife", "THYAO", words))  # 'Türk' alone is generic
        self.assertTrue(news.about_another("Energizer (NYSE:ENR) Gets Price Target from JPMorgan", "JPM"))
        self.assertFalse(news.about_another("JPMorgan (NYSE:JPM) raises dividend", "JPM"))

    def test_collect_dedupes_and_filters(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        g = [{"title": "Apple beats earnings estimates", "source": "A", "published": now, "url": "u1", "feed": "google"},
             {"title": "Apple beats earnings estimates", "source": "B", "published": now, "url": "u2", "feed": "google"},
             {"title": "Old Apple story", "source": "C", "published": now - timedelta(days=90), "url": "u3", "feed": "google"},
             {"title": "Nvidia rallies", "source": "D", "published": now, "url": "u4", "feed": "google"}]
        with Patch(news, "google", lambda q, lang: list(g)), Patch(news, "yahoo", lambda sym: []):
            out = news.collect("AAPL", "AAPL", "Apple Inc.", "US", days=30, limit=10)
        self.assertEqual(out["found"], 1)
        self.assertEqual(out["dropped_off_topic"], 1)
        self.assertEqual(out["items"][0]["topics"], ["earnings"])


class Scenarios(unittest.TestCase):
    def test_quantile_and_rank(self):
        self.assertEqual(scen.quantile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertAlmostEqual(scen.quantile([0, 10], 0.2), 2)
        self.assertIsNone(scen.quantile([], 0.5))
        self.assertEqual(scen.percentile_rank([1, 2, 3, 4], 3), 75)

    def test_split_adjusted_eps_from_old_filings(self):
        # Apple's 2017 EPS of 9.21 was filed in 2019, before the 4:1 split of 2020.
        facts = {"Total Revenue": {"2017-09-30": 229e9}, "Net Income": {"2017-09-30": 48.35e9},
                 "Diluted EPS": {"2017-09-30": 9.21}, "Diluted Average Shares": {"2017-09-30": 5.25e9},
                 "_filed": {"Diluted EPS": {"2017-09-30": "2019-10-31"},
                            "Diluted Average Shares": {"2017-09-30": "2019-10-31"}}}
        with Patch(verify, "sec_annuals", lambda t: facts), \
                Patch(scen, "split_factors", lambda sym: [["2014-06-09", 7.0], ["2020-08-31", 4.0]]):
            y = scen.sec_years("AAPL", "AAPL")["2017-09-30"]
        self.assertAlmostEqual(y["shares"], 21000.0)  # millions, in today's share count

    def test_growth_fades_to_anchor(self):
        self.assertAlmostEqual(scen.revenue_after(100, 0.05, 3, 0.05), 100 * 1.05 ** 3)
        # 30% fading to 5% over ten years: 27.5%, 25%, 22.5% in the first three years
        self.assertAlmostEqual(scen.revenue_after(100, 0.30, 3, 0.05), 100 * 1.275 * 1.25 * 1.225)

    def test_defaults_clamp_base_multiple(self):
        rows = [{"end": f"{2015 + i}-12-31", "revenue": 100 * 1.05 ** i, "net_income": 10 * 1.05 ** i,
                 "margin": 0.10, "shares": 100.0, "pe": pe} for i, pe in enumerate([10, 12, 14, 16, 18, 20])]
        method, cases, share_change, _ = scen.defaults(rows, 3, multiple_now=40)
        self.assertEqual(method, "pe")
        self.assertAlmostEqual(cases["base"]["multiple"], cases["bull"]["multiple"])  # 40 pulled back to p80
        self.assertLess(cases["bear"]["multiple"], cases["base"]["multiple"])
        self.assertAlmostEqual(cases["base"]["growth"], 0.05, places=3)
        self.assertAlmostEqual(share_change, 0.0)
        _, cases, _, _ = scen.defaults(rows, 3, multiple_now=15)
        self.assertEqual(cases["base"]["multiple"], 15)  # inside the range: today's multiple

    def test_loss_maker_uses_price_to_sales(self):
        rows = [{"end": f"{2018 + i}-12-31", "revenue": 50.0 * (i + 1), "net_income": -10.0, "margin": -0.2,
                 "shares": 10.0, "ps": 5.0 + i} for i in range(5)]
        method, cases, _, _ = scen.defaults(rows, 3)
        self.assertEqual(method, "ps")
        self.assertIsNone(cases["base"]["margin"])
        self.assertLessEqual(cases["bull"]["growth"], scen.MAX_GROWTH)

    def test_overrides(self):
        cases = {c: {"growth": 0.05, "margin": 0.1, "multiple": 15} for c in scen.CASES}
        shares = scen.apply_overrides(cases, ["bear.growth=-2", "bull.multiple=30", "shares=-1.5"])
        self.assertAlmostEqual(cases["bear"]["growth"], -0.02)
        self.assertEqual(cases["bull"]["multiple"], 30)
        self.assertAlmostEqual(shares, -0.015)
        with self.assertRaises(DeskError):
            scen.apply_overrides(cases, ["base.price=100"])

    def test_position_and_band(self):
        path = {"bear": 80.0, "base": 100.0, "bull": 125.0}
        self.assertAlmostEqual(scen.position(100.0, path), 0.5)
        self.assertAlmostEqual(scen.position(80.0, path), 0.0)
        self.assertAlmostEqual(scen.position(125.0, path), 1.0)
        self.assertGreater(scen.position(200.0, path), 1.0)
        self.assertEqual(scen.band(70.0, path), "below bear")
        self.assertEqual(scen.band(110.0, path), "between base and bull")

    def test_score_entry_uses_path_to_date(self):
        # saved at 100 one year into a 2-year case whose base ends at 121: base path is 110 by now
        closes = [100.0] * 260 + [110.0] * 10
        df = frame(closes, start="2024-01-01")
        entry = {"id": "X-1", "ticker": "X", "market": "US", "symbol": "X", "saved": "2024-01-01",
                 "price_date": "2024-01-01", "price": 100.0, "years": 2, "benchmark": "^GSPC",
                 "start": {"period_end": "2023-12-31", "revenue_m": 1000},
                 "cases": {"bear": {"price": 81.0}, "base": {"price": 121.0}, "bull": {"price": 144.0}}}
        today = df.index[-1].date()
        with Patch(prices, "load_history", lambda *a, **k: (df, None)), \
                Patch(scen, "history", lambda *a: {"rows": []}):
            r = scen.score_entry(entry, today)
        frac = scen.years_between("2024-01-01", today) / 2
        self.assertEqual(r["status"], "in progress")
        self.assertAlmostEqual(r["expected_by_now_pct"]["base"], round((1.21 ** frac - 1) * 100, 2))
        self.assertEqual(r["price_change_pct"], 10.0)

    def test_journal_roundtrip(self):
        fake = {"symbol": "X", "price": 10.0, "price_date": "2026-01-02", "benchmark": "^GSPC", "method": "P/E",
                "start": {"period_end": "2025-12-31"},
                "cases": {c: {"price": p, "assumptions": {"revenue_growth_pct": 5}} for c, p in
                          zip(scen.CASES, (8.0, 11.0, 14.0))}}
        with Patch(scen, "build", lambda *a, **k: fake), \
                Patch(prices, "quote", lambda *a, **k: {"close": 5000.0, "date": "2026-01-02"}):
            a = scen.save("X", "US", 3, [], "first")["saved"]["id"]
            b = scen.save("X", "US", 3, [], "second")["saved"]["id"]
        self.assertNotEqual(a, b)
        self.assertEqual(len(scen.list_entries()["scenarios"]), 2)
        scen.delete(a)
        self.assertEqual([e["id"] for e in scen.list_entries()["scenarios"]], [b])
        with self.assertRaises(DeskError):
            scen.delete("nope")


class Portfolio(unittest.TestCase):
    def setUp(self):
        if port.path().exists():
            port.path().unlink()
        port._closes.clear()
        # INTC-like: 25 at the start, 20 by mid-2024, 30 at the end
        idx = pd.bdate_range("2023-01-02", "2025-12-31")
        vals = np.interp(np.arange(len(idx)), [0, 400, len(idx) - 1], [25, 20, 30])
        self.series = pd.Series(vals, index=idx)
        self.patches = [Patch(port, "raw_closes", lambda sym: self.series),
                        Patch(port, "closes", lambda sym: self.series),
                        Patch(prices, "profile", lambda *a, **k: {"sector": "Technology", "country": "United States"})]
        for p in self.patches:
            p.__enter__()

    def tearDown(self):
        for p in reversed(self.patches):
            p.__exit__(None, None, None)

    def test_scaled_beta_never_below_minus_100(self):
        self.assertAlmostEqual(port.scaled(-0.10, 1.0), -0.10)
        self.assertGreater(port.scaled(-0.568, 2.36), -1.0)
        self.assertAlmostEqual(port.scaled(-0.568, 2.36), 0.432 ** 2.36 - 1)

    def test_add_sell_note_cycle(self):
        r = port.add("X", 10, 25.0, "US", "2023-01-02", "turnaround", "")
        self.assertEqual(r["avg_cost"], 25.0)
        day = str(self.series.index[400].date())
        r = port.add("X", 10, 20.0, "US", day, "", "")
        self.assertIn("note", r)  # bought below cost
        self.assertEqual(r["avg_cost"], 22.5)
        r = port.sell("X", 5, 30.0, "US", "2025-12-31", "")
        self.assertAlmostEqual(r["return_pct"], 33.33)
        self.assertIn("missing", r)  # no reason given
        with self.assertRaises(DeskError):
            port.sell("X", 50, 30.0, "US", "2025-12-31", "too many")
        port.note("X", "still fine", "US", "", "foundry losses widen")
        data = port.load()
        pos = data["positions"]["X:US"]
        self.assertEqual(pos["sell_if"], "foundry losses widen")
        self.assertEqual(pos["lots"][0]["shares"], 15)
        self.assertAlmostEqual(pos["lots"][0]["price"], 22.5)  # partial sale keeps the average cost
        port.sell("X", 15, 30.0, "US", "2025-12-31", "done")
        data = port.load()
        self.assertEqual(data["positions"], {})
        self.assertEqual(len(data["closed"]), 2)
        self.assertEqual(data["archive"][0]["ticker"], "X")

    def test_price_typo_warning(self):
        r = port.add("X", 1, 250.0, "US", "2023-01-02", "t", "s")
        self.assertIn("warning", r)

    def test_concentration(self):
        rows = [{"weight_pct": w, "sector": s, "country": "US"} for w, s in ((50, "Tech"), (30, "Tech"), (20, "Energy"))]
        c = port.concentration(rows)
        self.assertEqual(c["by_sector_pct"], {"Tech": 80.0, "Energy": 20.0})
        self.assertAlmostEqual(c["effective_positions"], round(1 / (0.25 + 0.09 + 0.04), 1))

    def test_disposition_counts(self):
        data = {"positions": {
                    "W:US": {"ticker": "W", "market": "US", "symbol": "W", "lots": [{"date": "2023-01-02", "shares": 1, "price": 10.0}]},
                    "L:US": {"ticker": "L", "market": "US", "symbol": "L", "lots": [{"date": "2023-01-02", "shares": 1, "price": 99.0}]}},
                "archive": [],
                "closed": [{"ticker": "S", "market": "US", "date": "2024-06-03", "return_pct": 40.0}]}
        d = port.disposition(data)
        # on the sale day W (cost 10) was at a gain and L (cost 99) at a loss; the sale itself was a gain
        self.assertEqual((d["gains_sold"], d["gains_kept"], d["losses_sold"], d["losses_kept"]), (1, 1, 0, 1))
        self.assertEqual(d["reads"], "too few sales to tell")


WIKI_SP500 = """== S&P 500 component stocks ==
{| class="wikitable sortable" id="constituents"
|-
![[Ticker symbol|Symbol]]
! Security !! GICS Sector !! GICS Sub-Industry
|-
|| {{NyseSymbol|MMM}}
|| [[3M]]
|| Industrials
|| Industrial Conglomerates
|-
|| {{NyseSymbol|BRK.B}}
|| [[Berkshire Hathaway|Berkshire Hathaway Inc.]]
|| Financials
|| Multi-Sector Holdings
|}"""

WIKI_SP400 = """{| class="wikitable sortable sticky-header" id="constituents"
|-
! style="border-color:inherit;" | [[Symbol]]
! Security
|-
| style="border-color:inherit;" | {{NyseSymbol|AA}}
| style="border-color:inherit;" | [[Alcoa]]
| Materials
| Aluminum
| [https://www.sec.gov/cgi-bin/browse-edgar?CIK=AA reports]
|-
|{{Anchor|A}}{{NasdaqSymbol|AAON}}
|AAON
|Industrials
|Building Products
|}"""


class Universe(unittest.TestCase):
    def test_both_wikipedia_table_styles(self):
        a = universe.parse_wiki_table(WIKI_SP500)
        self.assertEqual([(r["ticker"], r["name"], r["sector"]) for r in a],
                         [("MMM", "3M", "Industrials"), ("BRK-B", "Berkshire Hathaway Inc.", "Financials")])
        b = universe.parse_wiki_table(WIKI_SP400)
        self.assertEqual([(r["ticker"], r["name"], r["sector"], r["industry"]) for r in b],
                         [("AA", "Alcoa", "Materials", "Aluminum"), ("AAON", "AAON", "Industrials", "Building Products")])

    def test_name_filter(self):
        self.assertTrue(universe.SKIP_NAME.search("Acme Corp Warrants"))
        self.assertTrue(universe.SKIP_NAME.search("Bank 6.5% Notes due 2030"))
        self.assertFalse(universe.SKIP_NAME.search("Bright Horizons Family Solutions"))
        self.assertFalse(universe.SKIP_NAME.search("United Rentals"))

    def test_price_metrics(self):
        idx = pd.bdate_range("2024-01-01", periods=300)
        up = pd.Series(np.linspace(100, 200, 300), index=idx)
        down = pd.Series(np.linspace(200, 100, 300), index=idx)
        closes = pd.DataFrame({"UP": up, "DOWN": down})
        vol = pd.DataFrame({"UP": [1e6] * 295 + [3e6] * 5, "DOWN": [1e6] * 300}, index=idx)
        m = universe.price_metrics(closes, vol)
        self.assertGreater(m.at["UP", "vs_sma200"], 0)
        self.assertLess(m.at["DOWN", "vs_sma200"], 0)
        self.assertAlmostEqual(m.at["UP", "from_high"], 0)
        self.assertTrue(m.at["UP", "new_high"])
        self.assertTrue(m.at["DOWN", "new_low"])
        self.assertGreater(m.at["UP", "rsi"], 90)
        self.assertAlmostEqual(m.at["UP", "volume_ratio"], 3e6 / ((45 * 1e6 + 5 * 3e6) / 50))
        # 12-1 momentum: from 252 sessions back to 21 sessions back
        self.assertAlmostEqual(m.at["UP", "momentum_12_1"], (up.iloc[-22] / up.iloc[-253] - 1) * 100)


class Frames(unittest.TestCase):
    def test_latest_year(self):
        from datetime import date
        self.assertEqual(frames.latest_year(date(2026, 3, 1)), 2024)
        self.assertEqual(frames.latest_year(date(2026, 5, 1)), 2025)

    def test_metrics(self):
        f = {"revenue": 1000, "revenue_prev": 800, "net_income": 100, "ocf": 150, "capex": 50,
             "equity": 400, "long_term_debt": 200, "dividends": 40, "buybacks": 10, "gross_profit": 500}
        m = frames.metrics(f, 2000)
        self.assertEqual((m["pe"], m["ps"], m["fcf_yield"], m["revenue_growth"]), (20.0, 2.0, 5.0, 25.0))
        self.assertEqual((m["roe"], m["debt_to_equity"], m["dividend_yield"], m["shareholder_yield"]),
                         (25.0, 0.5, 2.0, 2.5))
        self.assertEqual(m["payout_of_fcf"], 40.0)
        loss = frames.metrics({"revenue": 100, "net_income": -5, "equity": -10, "ocf": 1}, 500)
        self.assertIsNone(loss["pe"])
        self.assertIsNone(loss["roe"])  # negative equity
        self.assertEqual(loss["dividend_yield"], 0.0)  # cash flow present, no dividend line

    def test_pick_revenue_takes_the_largest(self):
        data = {"Revenues": {1: 90}, "RevenueFromContractWithCustomerExcludingAssessedTax": {1: 100, 2: 50}}
        with Patch(frames, "frame", lambda tag, period, *a: data.get(tag, {})):
            self.assertEqual(frames._pick(frames.DURATION["revenue"], "CY2025", largest=True), {1: 100, 2: 50})
            self.assertEqual(frames._pick(["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
                                          "CY2025"), {1: 90, 2: 50})


class Screener(unittest.TestCase):
    def test_parse_where(self):
        self.assertEqual(screener.parse_where("pe<15"), ("pe", "<", 15.0))
        self.assertEqual(screener.parse_where(" revenue_growth >= -5 "), ("revenue_growth", ">=", -5.0))
        with self.assertRaises(DeskError):
            screener.parse_where("pe << 3")
        with self.assertRaises(DeskError):
            screener.parse_where("moon>1")

    def test_filters_sort_and_blank_values(self):
        df = pd.DataFrame([
            {"ticker": "A", "name": "a", "sector": "Tech", "pe": 10.0, "fcf_yield": 8.0, "has_fundamentals": True},
            {"ticker": "B", "name": "b", "sector": "Tech", "pe": 30.0, "fcf_yield": 3.0, "has_fundamentals": True},
            {"ticker": "C", "name": "c", "sector": "Energy", "pe": None, "fcf_yield": 12.0, "has_fundamentals": False},
            {"ticker": "D", "name": "d", "sector": "Energy", "pe": 12.0, "fcf_yield": 9.5, "has_fundamentals": True},
        ]).set_index("ticker")
        for col in screener.FIELDS:
            if col not in df:
                df[col] = 1.0
        rows = [{"ticker": t, "sector": df.at[t, "sector"]} for t in df.index]
        with Patch(screener.universe, "members", lambda *a: rows), \
                Patch(screener, "build", lambda r: (df.loc[[x["ticker"] for x in r]], 2025, "2026-11-18")):
            out = screener.screen(where=["pe<20"], sort="fcf_yield")
            self.assertEqual([r["ticker"] for r in out["rows"]], ["D", "A"])  # C has no P/E, so it fails pe<20
            self.assertEqual(out["fundamentals_year"], 2025)
            out = screener.screen(sector="energy", sort="pe", asc=True)
            self.assertEqual([r["ticker"] for r in out["rows"]], ["D", "C"])  # blanks sort last
            with self.assertRaises(DeskError):
                screener.screen(preset="nope")


class Market(unittest.TestCase):
    def test_distribution_days(self):
        closes = [100.0] * 30
        vols = [1000.0] * 30
        closes[20], vols[20] = 99.0, 1500.0   # down 1% on higher volume: counts
        closes[21] = 99.0
        closes[22], vols[22] = 98.9, 900.0    # down on lower volume: does not count
        for i in range(23, 30):
            closes[i] = 98.9
        closes[25], vols[25] = 98.0, 2000.0   # counts
        df = frame(closes)
        df["Volume"] = vols
        days = market.distribution_days(df)
        self.assertEqual(days, [str(df.index[20].date()), str(df.index[25].date())])
        df.loc[df.index[-1], "Close"] = 105.0  # 5% above both days' closes removes them
        self.assertEqual(len(market.distribution_days(df)), 0)

    def test_dd_signal(self):
        self.assertEqual([market.dd_signal(n) for n in (0, 2, 3, 5, 8)],
                         ["risk_on", "risk_on", "neutral", "risk_off", "risk_off"])

    def test_parse_fomc(self):
        html = """<h4><a>2026 FOMC Meetings</a></h4>
        <div class="fomc-meeting__month col"><strong>January</strong></div><div class="fomc-meeting__date col">27-28</div>
        Minutes (Released February 18, 2026)
        <div class="fomc-meeting__month col"><strong>March</strong></div><div class="fomc-meeting__date col">17-18*</div>
        <h4><a>2025 FOMC Meetings</a></h4>
        <div class="fomc-meeting__month col"><strong>Apr/May</strong></div><div class="fomc-meeting__date col">30-1</div>
        <div class="fomc-meeting__month col"><strong>August</strong></div><div class="fomc-meeting__date col">22 (notation vote)</div>"""
        self.assertEqual(market.parse_fomc(html), [
            {"date": "2025-05-01", "projections": False},
            {"date": "2026-01-28", "projections": False},
            {"date": "2026-03-18", "projections": True}])

    def test_blank_and_cap(self):
        self.assertIsNone(market._blank("&nbsp;"))
        self.assertIsNone(market._blank(" "))
        self.assertEqual(market._cap("$1,234,567"), 1234567.0)


FORM4 = b"""<?xml version="1.0"?><ownershipDocument>
<issuer><issuerCik>0000320193</issuerCik></issuer>
<reportingOwner><reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer><officerTitle>Chief Financial Officer</officerTitle></reportingOwnerRelationship></reportingOwner>
<aff10b5One>false</aff10b5One>
<nonDerivativeTable>
<nonDerivativeTransaction><transactionDate><value>2026-05-01</value></transactionDate>
<transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>1000</value></transactionShares><transactionPricePerShare><value>50.5</value></transactionPricePerShare></transactionAmounts>
<postTransactionAmounts><sharesOwnedFollowingTransaction><value>3000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
</nonDerivativeTransaction>
<nonDerivativeTransaction><transactionDate><value>2026-05-02</value></transactionDate>
<transactionCoding><transactionCode>F</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>100</value></transactionShares></transactionAmounts>
</nonDerivativeTransaction>
</nonDerivativeTable>
<footnotes><footnote id="F1">Weighted average price.</footnote></footnotes>
</ownershipDocument>"""

PTR = """Name: Hon. Jane Doe
ID Owner Asset Transaction Type Date Notification Date Amount
SP Brown & Brown, Inc. Common Stock
(BRO) [ST]
S 08/25/2026 09/01/2026 $100,001 -
$250,000
F S : New
Apple Inc. Common Stock (AAPL) [ST] P 08/03/2026 09/01/2026 $1,001 - $15,000
Some Fund (XYZ) [OT] S (partial) 08/04/2026 09/01/2026 Over $50,000,000"""


class FakeDate:
    """date.today() pinned to a fixed day for one test."""
    today_value = None

    @classmethod
    def today(cls):
        return cls.today_value

    @staticmethod
    def fromisoformat(s):
        import datetime
        return datetime.date.fromisoformat(s)


class SmartMoney(unittest.TestCase):
    def test_form4(self):
        f = smart.parse_form4(FORM4)
        self.assertEqual(f["owners"], [{"name": "Doe Jane", "role": "Chief Financial Officer, director"}])
        self.assertFalse(f["plan"])
        self.assertEqual(f["issuer_cik"], 320193)
        self.assertEqual([(t["code"], t["shares"], t["price"]) for t in f["trades"]],
                         [("P", 1000, 50.5), ("F", 100, 0)])

    def test_ptr(self):
        t = smart.parse_ptr(PTR)
        self.assertEqual([(x["ticker"], x["type"], x["traded"], x["amount_low"], x["amount_high"], x["owner"])
                          for x in t], [
            ("BRO", "sale", "2026-08-25", 100001, 250000, "spouse"),
            ("AAPL", "purchase", "2026-08-03", 1001, 15000, "member"),
            ("XYZ", "partial sale", "2026-08-04", 50000000, None, "member")])

    def test_resolve_fund(self):
        self.assertEqual(smart.resolve_fund("Berkshire")[0], 1067983)
        self.assertEqual(smart.resolve_fund("1336528"), (1336528, None))
        with self.assertRaises(DeskError):
            smart.resolve_fund("no such fund")

    def test_insider_summary_and_cluster(self):
        import datetime
        sub = {"company": "X CORP", "cik": "0000000001", "recent": {
            "form": ["4", "4", "4", "4"], "filingDate": ["2099-01-20", "2099-01-15", "2099-01-10", "2099-01-05"],
            "accessionNumber": ["a1", "a2", "a3", "a4"], "primaryDocument": ["x.xml"] * 4}}
        docs = {
            "a1": {"owners": [{"name": "A", "role": "CEO"}], "plan": False,
                   "trades": [{"date": "2099-01-19", "code": "P", "shares": 100, "price": 10, "owned_after": 100}]},
            "a2": {"owners": [{"name": "B", "role": "director"}], "plan": False,
                   "trades": [{"date": "2099-01-14", "code": "P", "shares": 50, "price": 10, "owned_after": 50}]},
            "a3": {"owners": [{"name": "C", "role": "CFO"}], "plan": False,
                   "trades": [{"date": "2099-01-09", "code": "P", "shares": 10, "price": 10, "owned_after": 10}]},
            "a4": {"owners": [{"name": "D", "role": "officer"}], "plan": True,
                   "trades": [{"date": "2099-01-04", "code": "S", "shares": 300, "price": 10, "owned_after": 100}]},
        }
        for acc, d in docs.items():
            cache.put_json("filed", f"f4v2:{acc}", d)
        FakeDate.today_value = datetime.date(2099, 2, 1)
        with Patch(smart.sec, "submissions", lambda t: sub), Patch(smart, "date", FakeDate):
            out = smart.insiders("X", days=60)
        self.assertEqual(out["open_market_buys"], {"count": 3, "insiders": 3, "value_usd": 1600.0})
        self.assertEqual(out["open_market_sales"]["share_under_10b5_1_plan_pct"], 100.0)
        self.assertEqual(out["cluster_buy"]["insiders"], ["A", "B", "C"])
        self.assertEqual(out["largest_sales"][0]["pct_of_holding_sold"], 75.0)


class Backtest(unittest.TestCase):
    def test_hold_until(self):
        e = pd.Series([False, True, False, False, True, False])
        x = pd.Series([False, False, False, True, False, False])
        self.assertEqual(list(technicals._hold_until(e, x)), [0, 1, 1, 0, 1, 1])

    def test_rising_stock(self):
        # A steady rise: the 200-day rule is always in, so it matches buy-and-hold.
        df = frame(list(np.linspace(50, 150, 1600)), start="2015-01-01")
        with Patch(technicals.prices, "load_history", lambda *a, **k: (df, None)):
            out = technicals.backtest("X", years=5, cost_bps=0)
        bh, tr = out["buy_and_hold"], out["rules"]["trend_200d"]
        self.assertAlmostEqual(tr["cagr_pct"], bh["cagr_pct"], delta=0.05)
        self.assertEqual(tr["time_in_market_pct"], 100)
        self.assertEqual(bh["max_drawdown_pct"], 0)

    def test_no_lookahead(self):
        # One jump: a rule that enters on the jump day's close must not earn that day's move.
        df = frame([100.0] * 400 + [200.0] * 400, start="2020-01-01")
        with Patch(technicals.prices, "load_history", lambda *a, **k: (df, None)):
            out = technicals.backtest("X", years=2, cost_bps=0)
        self.assertLess(out["rules"]["breakout_55_20"]["cagr_pct"], 1)


class PreTradeCheck(unittest.TestCase):
    def test_sizing_against_limits(self):
        rows = [{"key": "AAA:US", "ticker": "AAA", "symbol": "AAA", "value_usd": 9000.0, "sector": "Tech"},
                {"key": "BBB:US", "ticker": "BBB", "symbol": "BBB", "value_usd": 1000.0, "sector": "Energy"}]
        series = pd.Series(np.linspace(10, 20, 400), index=pd.bdate_range("2025-01-01", periods=400))

        def no_yahoo():
            raise RuntimeError("offline")

        patches = [Patch(port, "load", lambda: {"positions": {"AAA:US": {}}, "closed": [], "archive": []}),
                   Patch(port, "holdings", lambda d: (rows, 10000.0)),
                   Patch(port, "raw_closes", lambda s: series), Patch(port, "closes", lambda s: series),
                   Patch(port, "atr_pct", lambda s: 0.05),
                   Patch(prices, "profile", lambda *a, **k: {"sector": "Tech"}),
                   Patch(prices, "_yf", no_yahoo)]
        for p in patches:
            p.__enter__()
        try:
            out = port.check("NEW", 100, 10.0, "US", stop=9.0)
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)
        # 1,000 of new money: weight 1000/11000, tech (9000+1000)/11000, loss 100/11000
        self.assertEqual([c["value_pct"] for c in out["checks"]], [9.1, 90.9, 0.91])
        self.assertEqual([c["status"] for c in out["checks"]], ["ok", "over", "ok"])
        # risk: x * 1 = 0.01 * (10000 + 10x)  ->  x = 100 / 0.9
        self.assertAlmostEqual(out["max_shares_within_limits"]["by_risk"], round(100 / 0.9, 1))
        # weight: 10x / (10000 + 10x) = 0.2  ->  x = 250
        self.assertAlmostEqual(out["max_shares_within_limits"]["by_position_weight"], 250.0)


if __name__ == "__main__":
    unittest.main()
