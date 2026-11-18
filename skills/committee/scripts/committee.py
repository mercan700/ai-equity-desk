#!/usr/bin/env python3
"""An investment committee for one stock: gather the evidence, then render the report.

  committee.py gather AAPL            run the other skills and save everything to one file
  committee.py report AAPL            check the analysts' cases and write the HTML report
  committee.py report AAPL --open     ... and open it in the browser

Between the two steps Claude writes the bull, bear and risk analysts' cases and the
chair's summary to a views file next to the data. The report refuses to build without a
bear case, and marks every number in a claim that it cannot find in the gathered data.
"""
import argparse
import html
import json
import math
import os
import re
import subprocess
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent
sys.path.insert(0, str(SKILLS / "desk-data" / "scripts"))

from deskcore import DeskError, config, markets, prices  # noqa: E402
from deskcore.cli import run  # noqa: E402
from deskcore.prices import _num  # noqa: E402

SECTIONS = {
    "fundamentals": ("fundamentals/scripts/fundamentals.py", "{t}"),
    "technicals": ("technicals/scripts/technicals.py", "{t}"),
    "scenarios": ("scenarios/scripts/scenarios.py", "build {t}"),
    "news": ("news-analyst/scripts/news.py", "{t} --limit 12"),
    "story": ("company-story/scripts/story.py", "{t}"),
    "insiders": ("smart-money/scripts/smartmoney.py", "insiders {t} --days 180"),
    "market": ("market/scripts/market.py", "regime"),
    "calendar": ("market/scripts/market.py", "calendar --days 30 --tickers {t}"),
}
US_ONLY = {"insiders", "market", "calendar"}
SEATS = ("bull", "bear", "risk")
LEANS = {"bull": "Leans to the bull case", "bear": "Leans to the bear case", "split": "Evenly split"}
MIN_BEAR_POINTS = 3


def out_dir():
    d = config.HOME / "committee"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_skill(script, args, timeout=420):
    """Run another skill's script and return its JSON, or {"error": ...}."""
    try:
        p = subprocess.run([sys.executable, str(SKILLS / script), *args], capture_output=True,
                           timeout=timeout, env=os.environ.copy())
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout} s"}
    lines = [x for x in p.stdout.decode("utf-8", "replace").splitlines() if x.strip()]
    try:
        return json.loads(lines[-1])
    except (IndexError, ValueError):
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        return {"error": (err[-1] if err else "no output")[:300]}


def chart_series(ticker, market, every=5):
    """Five years of closes, sampled weekly, with the 200-day average."""
    df, _ = prices.load_history(markets.symbol(ticker, market), "5y", "1d")
    c = df["Close"].dropna()
    sma = c.rolling(200).mean()
    idx = list(range(len(c) - 1, -1, -every))[::-1]
    return [[str(c.index[i].date()), _num(c.iloc[i]), _num(sma.iloc[i]) if not math.isnan(sma.iloc[i]) else None]
            for i in idx]


def gather(ticker, market="US"):
    m, _ = markets.get(market)
    t = ticker.upper()
    wanted = {k: v for k, v in SECTIONS.items() if m == "US" or k not in US_ONLY}
    if m == "US" and not (os.environ.get("DESK_SEC_USER_AGENT") or config.load().get("sec_user_agent")):
        wanted.pop("insiders")

    def one(item):
        name, (script, args) = item
        extra = ["--market", m] if name not in ("market", "calendar", "insiders") else []
        return name, run_skill(script, args.format(t=t).split() + extra)

    with ThreadPoolExecutor(max_workers=4) as pool:
        data = dict(pool.map(one, wanted.items()))
    if "error" in data.get("technicals", {}) and "error" in data.get("fundamentals", {}):
        raise DeskError(f"No data for '{t}': {data['technicals']['error']}")
    try:
        chart = chart_series(t, m)
    except Exception as e:  # noqa: BLE001 - the report works without the chart
        chart, data["chart_error"] = [], str(e)
    record = {"ticker": t, "market": m, "gathered": datetime.now().isoformat(timespec="minutes"),
              "sections": data, "chart": chart}
    path = out_dir() / f"{t}-{date.today().isoformat()}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, default=str), encoding="utf-8")
    return {"data_file": str(path), "views_file": str(views_path(path)),
            "missing": {k: v["error"] for k, v in data.items() if isinstance(v, dict) and "error" in v},
            "skipped": sorted(set(SECTIONS) - set(wanted)),
            "sections": {k: brief(k, v) for k, v in data.items() if isinstance(v, dict) and "error" not in v}}


def _obj(x):
    """A sub-part of a section; a source that failed inside a skill gives {"error": ...} or a string."""
    return x if isinstance(x, dict) else {}


def _rows(x):
    """A list of dicts, or [] when the source failed and returned an error instead of a list."""
    return [r for r in x if isinstance(r, dict)] if isinstance(x, list) else []


def _failed(x):
    return x.get("error") if isinstance(x, dict) else (x if isinstance(x, str) else None)


def brief(name, d):
    """What Claude needs to read from each section; the full output stays in the data file."""
    if name == "story":
        p, w = _obj(d.get("profile")), _obj(d.get("wikipedia"))
        out = {"profile": {k: p.get(k) for k in ("name", "sector", "industry", "country", "employees")},
               "summary": (p.get("summary") or "")[:500], "lead": (w.get("lead") or "")[:700],
               "history": (w.get("history") or "")[:1500], "market_history": d.get("market_history")}
        for part in ("profile", "wikipedia"):
            if _failed(d.get(part)):
                out[f"{part}_error"] = _failed(d.get(part))
        return out
    if name == "news":
        n = _obj(d.get("news"))
        out = {"topic_counts": n.get("topic_counts"),
               "items": [{k: i.get(k) for k in ("date", "title", "source", "topics", "summary")}
                         for i in _rows(n.get("items"))],
               "company_filings_8k": [{k: f.get(k) for k in ("filed", "items")}
                                      for f in _rows(d.get("company_filings_8k"))]}
        for part, value in (("news", d.get("news")), ("company_filings_8k", d.get("company_filings_8k"))):
            if _failed(value):
                out[f"{part}_error"] = _failed(value)
        return out
    if name == "calendar":
        return {k: d.get(k) for k in ("next_fed_decision", "your_stocks_reporting", "your_stocks_next_earnings")} | {
            "us_releases": [f"{r.get('date')} {r.get('event')}" for r in _rows(d.get("us_releases"))][:10]}
    if name == "insiders":
        return {k: v for k, v in d.items() if k not in ("largest_sales",)} | {
            "largest_sales": _rows(d.get("largest_sales"))[:5]}
    return d


# ---------- the analysts' cases ----------

def views_path(data_path):
    p = Path(data_path)
    return p.with_name(p.stem + ".views.json")


def find_data(arg):
    p = Path(arg)
    if p.suffix == ".json" and p.exists():
        return p
    hits = sorted(out_dir().glob(f"{arg.upper()}-*.json"))
    hits = [h for h in hits if not h.name.endswith(".views.json")]
    if not hits:
        raise DeskError(f"No gathered data for '{arg}'. Run: committee.py gather {arg.upper()}")
    return hits[-1]


NUM = re.compile(r"(?<![\w.])([-+]?\$?\d[\d,]*(?:\.\d+)?)\s*(%|pp|x|bn|billion|b\b|m\b|million|mn|tn|trillion|t\b)?",
                 re.I)


def numbers_in(text):
    """(value, raw) for each number a claim states. Years, small counts and anything after
    '=' (the writer's own arithmetic, whose inputs are checked) are left out."""
    found = []
    text = re.sub(r"\d{4}-\d{2}(-\d{2})?", " ", text)
    for part_i, part in enumerate(re.split(r"=", text)):
        if part_i:
            part = re.sub(r"^\s*[-+]?\$?\d[\d,]*(?:\.\d+)?\s*(%|pp|x)?", "", part)
        for m in NUM.finditer(part):
            raw, unit = m.group(1), (m.group(2) or "").lower()
            try:
                v = float(raw.replace("$", "").replace(",", ""))
            except ValueError:
                continue
            if not unit and "$" not in raw and (v.is_integer() and (abs(v) <= 12 or 1900 <= v <= 2100)):
                continue
            found.append((v, raw + (unit if unit else "")))
    return found


def data_numbers(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            data_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            data_numbers(v, out)
    elif isinstance(obj, str):
        for m in re.finditer(r"(?<![\w.])-?\d+(?:\.\d+)?", obj):
            out.append(float(m.group()))
    return out


def supported(value, raw, pool):
    decimals = len(raw.split(".")[1].rstrip("%pxbnmilotrBNMT ")) if "." in raw else 0
    tol = 0.5 * 10 ** -decimals + 1e-9  # the precision the number is written at
    x = abs(value)
    for v in pool:
        for s in (1, 1e-3, 1e-6, 1e3, 100):
            if abs(abs(v) * s - x) <= tol:
                return True
    return False


def check_views(views, data):
    """Problems that stop the report, and numbers that are not in the data."""
    errors, unverified = [], []
    if not isinstance(views, dict):
        return ["The views file must hold a JSON object."], []
    have = {k for k, v in data["sections"].items() if isinstance(v, dict) and "error" not in v}
    pool = data_numbers(data["sections"])
    for seat in SEATS:
        s = views.get(seat)
        if not isinstance(s, dict) or not str(s.get("thesis", "")).strip():
            errors.append(f"'{seat}' needs a thesis.")
            continue
        pts = s.get("points") or []
        if not pts:
            errors.append(f"'{seat}' needs points.")
        for i, p in enumerate(pts):
            if not str(p.get("claim", "")).strip():
                errors.append(f"{seat} point {i + 1} has no claim.")
                continue
            if p.get("source") not in have:
                errors.append(f"{seat} point {i + 1}: source '{p.get('source')}' is not one of {sorted(have)}.")
            bad = [raw for v, raw in numbers_in(p["claim"]) if not supported(v, raw, pool)]
            if bad:
                unverified.append({"seat": seat, "point": i + 1, "numbers": bad})
    bull, bear = views.get("bull") or {}, views.get("bear") or {}
    nb, nbear = len(bull.get("points") or []), len(bear.get("points") or [])
    if nbear < MIN_BEAR_POINTS:
        errors.append(f"The bear case needs at least {MIN_BEAR_POINTS} points; it has {nbear}.")
    if nbear < nb - 1:
        errors.append(f"The bull case has {nb} points and the bear case {nbear}. Give the bear case as much work.")
    chair = views.get("chair")
    if not isinstance(chair, dict) or not str(chair.get("summary", "")).strip():
        errors.append("'chair' needs a summary.")
    elif chair.get("leans") not in LEANS:
        errors.append(f"chair.leans must be one of {list(LEANS)}.")
    elif not str(chair.get("would_change_mind", "")).strip():
        errors.append("chair.would_change_mind is required: what evidence would flip the lean.")
    return errors, unverified


# ---------- the HTML report ----------

E = html.escape


def g(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def fmt(v, unit="", nd=1):
    if v is None:
        return "n/a"
    if isinstance(v, (int, float)):
        return f"{v:,.{nd}f}{unit}"
    return E(str(v))


def chart_svg(chart, scen, currency):
    if len(chart) < 10:
        return ""
    W, H, L, R, T, B = 760, 300, 52, 92, 14, 28
    d0 = date.fromisoformat(chart[0][0])
    today = date.fromisoformat(chart[-1][0])
    cases = g(scen, "cases") or {}
    years = scen.get("years") if scen else None
    end = today + timedelta(days=365 * years) if years and cases else today
    vals = [p[1] for p in chart if p[1]] + [p[2] for p in chart if p[2]]
    vals += [c["price"] for c in cases.values() if c.get("price")]
    lo, hi = min(vals) * 0.95, max(vals) * 1.05
    span = (end - d0).days or 1

    def X(d):
        return L + (W - L - R) * (d - d0).days / span

    def Y(v):
        return T + (H - T - B) * (1 - (v - lo) / (hi - lo))

    pts = " ".join(f"{X(date.fromisoformat(a)):.1f},{Y(c):.1f}" for a, c, _ in chart if c)
    sma = " ".join(f"{X(date.fromisoformat(a)):.1f},{Y(s):.1f}" for a, _, s in chart if s)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Price history and scenario range">']
    step = 10 ** math.floor(math.log10((hi - lo) / 4))
    step *= next(m for m in (1, 2, 2.5, 5, 10) if (hi - lo) / (step * m) <= 6)
    v = math.ceil(lo / step) * step
    while v <= hi:
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                   f'<text class="ax" x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:,.0f}</text>')
        v += step
    for yr in range(d0.year + 1, end.year + 1):
        x = X(date(yr, 1, 1))
        out.append(f'<text class="ax" x="{x:.1f}" y="{H - 8}" text-anchor="middle">{yr}</text>')
    xt = X(today)
    last = chart[-1][1]
    if cases and years:
        xe = X(end)
        b, bu = cases.get("bear", {}).get("price"), cases.get("bull", {}).get("price")
        if b and bu:
            out.append(f'<polygon class="fan" points="{xt:.1f},{Y(last):.1f} {xe:.1f},{Y(bu):.1f} {xe:.1f},{Y(b):.1f}"/>')
        for k in ("bear", "base", "bull"):
            p = cases.get(k, {}).get("price")
            if p:
                out.append(f'<line class="case {k}" x1="{xt:.1f}" y1="{Y(last):.1f}" x2="{xe:.1f}" y2="{Y(p):.1f}"/>'
                           f'<text class="lab {k}" x="{xe + 6:.1f}" y="{Y(p) + 4:.1f}">{k} {p:,.0f}</text>')
    out.append(f'<line class="today" x1="{xt:.1f}" x2="{xt:.1f}" y1="{T}" y2="{H - B}"/>')
    if sma:
        out.append(f'<polyline class="sma" points="{sma}"/>')
    out.append(f'<polyline class="px" points="{pts}"/>')
    out.append(f'<circle class="dot" cx="{xt:.1f}" cy="{Y(last):.1f}" r="3.5"/></svg>')
    legend = (f'<p class="legend"><span class="k px"></span>Price ({E(currency)}, weekly) '
              f'<span class="k sma"></span>200-day average')
    if cases and years:
        legend += f' <span class="k fan"></span>Bear to bull range in {end.year}, from the scenarios skill'
    return "".join(out) + legend + "</p>"


def points_html(points, flags):
    rows = []
    for i, p in enumerate(points, 1):
        flag = flags.get(i)
        mark = (f'<span class="flag" title="not found in the gathered data">check: {E(", ".join(flag))}</span>'
                if flag else "")
        rows.append(f'<li>{E(p["claim"])} <span class="src">{E(p.get("source", ""))}</span>{mark}</li>')
    return "<ul>" + "".join(rows) + "</ul>"


def seat_html(seat, title, v, flags):
    extra = ""
    if v.get("would_be_wrong_if"):
        extra = f'<p class="wrong"><b>Wrong if:</b> {E(v["would_be_wrong_if"])}</p>'
    return (f'<section class="seat {seat}"><h3>{title}</h3><p class="thesis">{E(v["thesis"])}</p>'
            f'{points_html(v.get("points") or [], flags)}{extra}</section>')


def numbers_html(s):
    f, t, sc, ins, mk = (s.get(k) or {} for k in ("fundamentals", "technicals", "scenarios", "insiders", "market"))
    cells = [
        ("Revenue growth, 3y a year", fmt(g(f, "growth", "revenue_cagr_pct"), "%")),
        ("Operating margin", fmt(g(f, "profitability", "operating_margin_pct"), "%")),
        ("Free cash flow / net income", fmt(g(f, "cash_quality", "fcf_to_net_income"), "", 2)),
        ("Net debt / EBITDA", fmt(g(f, "balance_sheet", "net_debt_to_ebitda"), "", 2)),
        ("P/E, trailing", fmt(g(f, "valuation", "pe_ttm"))),
        ("Free cash flow yield", fmt(g(f, "valuation", "fcf_yield_pct"), "%", 2)),
        ("Growth the price assumes", fmt(g(sc, "growth_needed_pct", "to_hold_price"), "% a year")),
        ("Past revenue growth", " to ".join(fmt(x, "%") for x in (g(sc, "history", "revenue_growth_pct_range") or []))
         or "n/a"),
        ("Trend", fmt(g(t, "trend", "label"))),
        ("From 52-week high", fmt(g(t, "levels", "from_52w_high_pct"), "%")),
        ("Max drawdown, 1y", fmt(g(t, "volatility", "max_drawdown_1y_pct"), "%")),
        ("Insider open-market buys / sales, 6m",
         f'{fmt(g(ins, "open_market_buys", "value_usd"), "", 0)} / {fmt(g(ins, "open_market_sales", "value_usd"), "", 0)} USD'
         if ins else "n/a"),
        ("Market posture", fmt(mk.get("posture")) if mk else "n/a"),
        ("SEC cross-check", fmt(g(f, "verification", "matched")) + " matched" if g(f, "verification", "matched") else "n/a"),
    ]
    return '<dl class="nums">' + "".join(f"<div><dt>{E(a)}</dt><dd>{b}</dd></div>" for a, b in cells) + "</dl>"


def scenario_table(sc):
    cases = g(sc, "cases")
    if not cases:
        return ""
    method = sc.get("method", "P/E")
    rows = [("Revenue growth a year", "revenue_growth_pct", "%"), ("Net margin", "net_margin_pct", "%"),
            (method, "exit_pe" if method == "P/E" else "exit_ps", "")]
    head = "".join(f"<th>{k.title()}</th>" for k in ("bear", "base", "bull"))
    body = "".join(f"<tr><td>{E(lbl)}</td>" + "".join(
        f"<td>{fmt(g(cases, k, 'assumptions', key), u)}</td>" for k in ("bear", "base", "bull")) + "</tr>"
                   for lbl, key, u in rows)
    body += "<tr class='res'><td>Price in {}</td>".format(int(sc["price_date"][:4]) + sc["years"]) + "".join(
        f"<td>{fmt(g(cases, k, 'price'), '', 0)}</td>" for k in ("bear", "base", "bull")) + "</tr>"
    body += "<tr class='res'><td>Return a year</td>" + "".join(
        f"<td>{fmt(g(cases, k, 'annual_return_pct'), '%')}</td>" for k in ("bear", "base", "bull")) + "</tr>"
    return (f'<table class="scen"><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>'
            f'<p class="note">Built from {E(g(sc, "history", "source") or "the company history")}, '
            f'{E(str(g(sc, "history", "years") or ""))}. Bear and bull combine the low or high end of all three '
            f'assumptions at once. They are ranges, not forecasts.</p>')


CSS = """
:root{--bg:#fbfaf7;--card:#fff;--ink:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;--bear:#b3412f;--bull:#2f7d4f;
--base:#4f6d8f;--risk:#9a6a12;--fan:rgba(79,109,143,.12);--flag:#fff1cc}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;
--muted:#a3a198;--line:#34332f;--bear:#e0735f;--bull:#5fbf86;--base:#8fb0d6;--risk:#d9a54a;--fan:rgba(143,176,214,.14);
--flag:#4a3d14}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 48px}
h1{font-size:26px;margin:0}h2{font-size:17px;margin:30px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:15px;margin:0 0 6px}.sub{color:var(--muted);margin:4px 0 0}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 0}.chips span{border:1px solid var(--line);
border-radius:999px;padding:2px 10px;font-size:13px;color:var(--muted);background:var(--card)}
.chair{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-top:20px}
.lean{font-weight:600}.against{border-left:4px solid var(--bear);padding:8px 12px;margin:12px 0 0;
background:color-mix(in srgb,var(--bear) 7%,transparent)}
.seats{display:grid;grid-template-columns:1fr 1fr;gap:14px}.seat{background:var(--card);border:1px solid var(--line);
border-top:4px solid;border-radius:10px;padding:14px 16px}.seat.bear{border-top-color:var(--bear)}
.seat.bull{border-top-color:var(--bull)}.seat.risk{border-top-color:var(--risk);grid-column:1/-1}
.seat ul{padding-left:18px;margin:8px 0}.seat li{margin:5px 0}.thesis{margin:0;font-weight:500}
.src{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 5px;margin-left:4px}
.flag{font-size:11px;background:var(--flag);border-radius:4px;padding:0 5px;margin-left:4px}
.wrong{font-size:14px;color:var(--muted);margin:6px 0 0}
svg{width:100%;height:auto;display:block}.grid{stroke:var(--line)}.ax{fill:var(--muted);font-size:11px}
.px{fill:none;stroke:var(--ink);stroke-width:1.6}.sma{fill:none;stroke:var(--muted);stroke-width:1.2;stroke-dasharray:4 3}
.fan{fill:var(--fan)}.case{stroke-width:1.6;stroke-dasharray:5 3}.case.bear{stroke:var(--bear)}.case.base{stroke:var(--base)}
.case.bull{stroke:var(--bull)}.lab{font-size:12px;font-weight:600}.lab.bear{fill:var(--bear)}.lab.base{fill:var(--base)}
.lab.bull{fill:var(--bull)}.today{stroke:var(--line);stroke-dasharray:2 3}.dot{fill:var(--ink)}
.legend{font-size:12px;color:var(--muted)}.k{display:inline-block;width:14px;height:3px;margin:0 5px 3px 10px;
vertical-align:middle}.k.px{background:var(--ink)}.k.sma{background:var(--muted)}.k.fan{background:var(--fan);height:10px}
.nums{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px;margin:0}
.nums div{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.nums dt{font-size:12px;color:var(--muted)}.nums dd{margin:2px 0 0;font-weight:600}
table.scen{border-collapse:collapse;width:100%;background:var(--card)}.scen th,.scen td{border:1px solid var(--line);
padding:6px 10px;text-align:right}.scen td:first-child,.scen th:first-child{text-align:left}.scen .res td{font-weight:600}
.note,.foot{font-size:13px;color:var(--muted)}.news li{margin:4px 0}.news .d{color:var(--muted);font-size:13px}
ul.watch{padding-left:18px}a{color:var(--base)}
@media (max-width:720px){.seats{grid-template-columns:1fr}h1{font-size:22px}}
@media print{body{background:#fff}.seat,.chair,.nums div{break-inside:avoid}}
"""


def render(data, views, unverified):
    s = data["sections"]
    f, t, sc, st = (s.get(k) or {} for k in ("fundamentals", "technicals", "scenarios", "story"))
    name = f.get("name") or g(st, "profile", "name") or data["ticker"]
    cur = f.get("currency") or sc.get("currency") or "USD"
    price, pdate = t.get("close") or sc.get("price"), t.get("date") or sc.get("price_date")
    flags = {}
    for u in unverified:
        flags.setdefault(u["seat"], {})[u["point"]] = u["numbers"]
    chips = [f"{E(data['ticker'])} · {E(data['market'])}", f.get("sector"), f.get("industry"),
             f"trend: {g(t, 'trend', 'label')}" if g(t, "trend", "label") else None,
             f"market: {g(s, 'market', 'posture')}" if g(s, "market", "posture") else None]
    nxt = g(s, "calendar", "your_stocks_reporting") or g(s, "calendar", "your_stocks_next_earnings") or []
    for e in _rows(nxt):
        if (e.get("ticker") or "").upper() == data["ticker"]:
            chips.append(f"earnings {e.get('date') or e.get('next_earnings')}")
    if g(s, "calendar", "next_fed_decision", "date"):
        chips.append(f"next Fed decision {g(s, 'calendar', 'next_fed_decision', 'date')}")
    ch = views["chair"]
    bear = views["bear"]
    watch = "".join(f"<li>{E(w)}</li>" for w in ch.get("watch") or [])
    news = _rows(g(s, "news", "news", "items"))
    news_html = "".join(
        f'<li><span class="d">{E(n.get("date", ""))} · {E(n.get("source", ""))}</span> '
        f'<a href="{E(n.get("url", ""))}" rel="noopener">{E(n.get("title", ""))}</a></li>' for n in news[:8])
    missing = {k: v["error"] for k, v in s.items() if isinstance(v, dict) and "error" in v}
    gaps = "".join(f"<li>{E(k)}: {E(v)}</li>" for k, v in missing.items())
    n_unv = sum(len(u["numbers"]) for u in unverified)
    sources = ("Prices from Yahoo Finance via yfinance. Statements from Yahoo, checked against SEC XBRL filings. "
               "Scenarios from the company's own ten-year record. Headlines from Google News and Yahoo, filings from "
               "SEC EDGAR. Insider trades from Form 4 filings. Market posture from index prices, FRED and Cboe data.")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(data['ticker'])} committee report</title><style>{CSS}</style></head><body><main>
<h1>{E(name)}</h1>
<p class="sub">Committee report, {E(str(pdate))}. Price {fmt(price, '', 2)} {E(cur)}. Data gathered {E(data['gathered'].replace('T', ' at '))}.</p>
<div class="chips">{''.join(f'<span>{E(str(c))}</span>' for c in chips if c)}</div>
<div class="chair"><p class="lean">{E(LEANS[ch['leans']])}</p><p>{E(ch['summary'])}</p>
<p><b>What would change this:</b> {E(ch['would_change_mind'])}</p>
<div class="against"><b>Strongest case against:</b> {E(bear['thesis'])}</div></div>
<h2>The cases</h2><div class="seats">
{seat_html('bear', 'Bear analyst', bear, flags.get('bear', {}))}
{seat_html('bull', 'Bull analyst', views['bull'], flags.get('bull', {}))}
{seat_html('risk', 'Risk analyst', views['risk'], flags.get('risk', {}))}
</div>
{f'<h2>What to watch</h2><ul class="watch">{watch}</ul>' if watch else ''}
<h2>Price and scenarios</h2>{chart_svg(data.get('chart') or [], sc, cur)}{scenario_table(sc)}
<h2>Key numbers</h2>{numbers_html(s)}
{f'<h2>Recent headlines</h2><ul class="news">{news_html}</ul>' if news_html else ''}
<h2>About this report</h2>
<p class="foot">Three analysts argued from the same data: one for, one against, one on what could go wrong either way.
Every point names the data it came from. {sources}</p>
{f'<p class="foot">{n_unv} number(s) in the cases were not found in the gathered data and are marked "check".</p>' if n_unv else ''}
{f'<p class="foot">Missing from this report:</p><ul class="foot">{gaps}</ul>' if gaps else ''}
<p class="foot">Written with Claude from free public data. It is research, not investment advice, and it does not
recommend buying or selling anything.</p>
</main></body></html>"""


def report(arg, views_file=None, out=None, open_it=False):
    data_path = find_data(arg)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    vp = Path(views_file) if views_file else views_path(data_path)
    if not vp.exists():
        raise DeskError(f"No views file at {vp}. Write the analysts' cases there first (see SKILL.md).")
    try:
        views = json.loads(vp.read_text(encoding="utf-8"))
    except ValueError as e:
        raise DeskError(f"The views file is not valid JSON: {e}")
    errors, unverified = check_views(views, data)
    if errors:
        return {"built": False, "errors": errors, "unverified_numbers": unverified}
    path = Path(out) if out else data_path.with_suffix(".html")
    path.write_text(render(data, views, unverified), encoding="utf-8")
    if open_it:
        webbrowser.open(path.as_uri())
    return {"built": True, "report": str(path), "unverified_numbers": unverified}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("gather")
    p.add_argument("ticker")
    p.add_argument("--market", default=config.load().get("default_market", "US"), help="US or BIST")
    p = sub.add_parser("report")
    p.add_argument("ticker", help="a ticker (uses its latest gathered data) or a data file path")
    p.add_argument("--views", help="views file; default: next to the data file")
    p.add_argument("--out", help="where to write the HTML; default: next to the data file")
    p.add_argument("--open", action="store_true", help="open the report in the browser")
    a = ap.parse_args()
    if a.cmd == "gather":
        return run(lambda: gather(a.ticker, a.market))
    return run(lambda: report(a.ticker, a.views, a.out, a.open))


if __name__ == "__main__":
    sys.exit(main())
