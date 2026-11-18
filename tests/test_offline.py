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

from deskcore import DeskError, bis, cache, macro, markets, news, prices, returns, verify, wiki  # noqa: E402
from deskcore.cli import friendly_error  # noqa: E402


def load_script(rel):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fundamentals = load_script("skills/fundamentals/scripts/fundamentals.py")
technicals = load_script("skills/technicals/scripts/technicals.py")
story = load_script("skills/company-story/scripts/story.py")


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
        self.assertEqual(out, {"2024-12-31": 1010e6})

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


if __name__ == "__main__":
    unittest.main()
