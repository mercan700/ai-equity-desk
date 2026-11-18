#!/usr/bin/env python3
"""What well-known investors, company insiders and members of Congress have been buying,
from the filings they are legally required to make. All sources are free and official.

  smartmoney.py funds                        the investors this skill knows by name
  smartmoney.py fund berkshire               latest 13F: holdings and what changed
  smartmoney.py fund 1067983                 any 13F filer by SEC CIK number
  smartmoney.py consensus                    what the stock-picking funds own and bought, together
  smartmoney.py insiders NVDA --days 180     Form 4: open-market buys and sells by executives
  smartmoney.py congress --days 60           House members' stock trades (periodic transaction reports)
  smartmoney.py congress --ticker NVDA

13F holdings are as of the quarter end and filed up to 45 days later. Form 4 is filed
within two business days. House reports are due within 45 days of a trade.
"""
import argparse
import io
import json
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "desk-data", "scripts"))

from deskcore import DeskError, cache, config, sec, universe  # noqa: E402
from deskcore.cli import run  # noqa: E402
from deskcore.prices import _num  # noqa: E402

# Stock pickers, whose 13F says something about conviction. "quant" filers hold thousands of
# positions for models or hedging; they can be looked up but are left out of the consensus.
FUNDS = {
    "berkshire": (1067983, "Berkshire Hathaway", "picker"),
    "pershing": (1336528, "Pershing Square (Bill Ackman)", "picker"),
    "appaloosa": (1656456, "Appaloosa (David Tepper)", "picker"),
    "baupost": (1061768, "Baupost Group (Seth Klarman)", "picker"),
    "duquesne": (1536411, "Duquesne Family Office (Stanley Druckenmiller)", "picker"),
    "thirdpoint": (1040273, "Third Point (Dan Loeb)", "picker"),
    "tiger": (1167483, "Tiger Global", "picker"),
    "coatue": (1135730, "Coatue Management", "picker"),
    "lonepine": (1061165, "Lone Pine Capital", "picker"),
    "viking": (1103804, "Viking Global", "picker"),
    "himalaya": (1709323, "Himalaya Capital (Li Lu)", "picker"),
    "icahn": (921669, "Carl Icahn", "picker"),
    "valueact": (1418814, "ValueAct", "picker"),
    "akre": (1112520, "Akre Capital", "picker"),
    "gates": (1166559, "Gates Foundation Trust", "picker"),
    "soros": (1029160, "Soros Fund Management", "picker"),
    "elliott": (1791786, "Elliott Investment Management", "picker"),
    "trian": (1345471, "Trian (Nelson Peltz)", "picker"),
    "altimeter": (1541617, "Altimeter (Brad Gerstner)", "picker"),
    "fundsmith": (1569205, "Fundsmith (Terry Smith)", "picker"),
    "dodge": (200217, "Dodge & Cox", "picker"),
    "markel": (1096343, "Markel Group", "picker"),
    "pabrai": (1549575, "Dalal Street (Mohnish Pabrai)", "picker"),
    "altarock": (1631014, "AltaRock Partners", "picker"),
    "polen": (1034524, "Polen Capital", "picker"),
    "ruane": (1720792, "Ruane, Cunniff & Goldfarb (Sequoia)", "picker"),
    "ark": (1697748, "ARK Investment (Cathie Wood)", "picker"),
    "bridgewater": (1350694, "Bridgewater Associates", "quant"),
    "renaissance": (1037389, "Renaissance Technologies", "quant"),
    "citadel": (1423053, "Citadel Advisors", "quant"),
    "millennium": (1273087, "Millennium Management", "quant"),
}
STALE_DAYS = 150  # a 13F older than this is skipped in the consensus (fund closed or stopped filing)


# ---------- 13F ----------

def filer(cik):
    key = f"13f:{cik}"
    data = cache.get_json("filings", key)
    if data is None:
        raw = sec.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json").json()
        rec = raw.get("filings", {}).get("recent", {})
        rows = [{"form": f, "filed": rec["filingDate"][i], "period": rec["reportDate"][i],
                 "accession": rec["accessionNumber"][i]}
                for i, f in enumerate(rec.get("form", [])) if f in ("13F-HR", "13F-HR/A")]
        data = {"name": raw.get("name"), "filings": rows}
        cache.put_json("filings", key, data)
    return data


def info_table(cik, accession, filed):
    """Holdings of one 13F, summed by CUSIP (options kept apart). Values in dollars."""
    key = f"13f:{cik}:{accession}"
    rows = cache.get_json("filed", key)
    if rows is not None:
        return rows
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    names = [f["name"] for f in sec.get(f"{base}/index.json").json()["directory"]["item"]]
    xmls = [n for n in names if n.lower().endswith(".xml") and n.lower() != "primary_doc.xml"]
    if not xmls:
        raise DeskError(f"No holdings table in filing {accession}.")
    root = ET.fromstring(sec.get(f"{base}/{xmls[0]}").content)
    scale = 1 if filed >= "2023-01-03" else 1000  # values were in thousands before 2023
    agg = {}
    for it in root.iter():
        if not it.tag.endswith("infoTable"):
            continue
        get = {c.tag.split("}")[-1]: c for c in it.iter()}

        def text(k):
            return (get[k].text or "").strip() if k in get and get[k].text else ""

        cusip = text("cusip").upper()
        put_call = text("putCall").lower()
        k = f"{cusip}:{put_call}"
        row = agg.setdefault(k, {"cusip": cusip, "issuer": text("nameOfIssuer"), "class": text("titleOfClass"),
                                 "option": put_call or None, "value": 0.0, "shares": 0.0})
        row["value"] += float(text("value") or 0) * scale
        if text("sshPrnamtType") == "SH":
            row["shares"] += float(text("sshPrnamt") or 0)
    rows = list(agg.values())
    cache.put_json("filed", key, rows)
    return rows


def resolve_fund(name):
    k = name.lower().replace(" ", "").replace("-", "")
    if k in FUNDS:
        return FUNDS[k][0], FUNDS[k][1]
    if k.isdigit():
        return int(k), None
    hits = [v for kk, v in FUNDS.items() if k in kk or k in v[1].lower().replace(" ", "")]
    if len(hits) == 1:
        return hits[0][0], hits[0][1]
    raise DeskError(f"Unknown fund '{name}'. Run 'smartmoney.py funds', or give the filer's SEC CIK number.")


def quarters(cik):
    """Latest two original 13F-HR filings for different quarters, newest first."""
    seen, out = set(), []
    for f in filer(cik)["filings"]:
        if f["form"] != "13F-HR" or f["period"] in seen:
            continue
        seen.add(f["period"])
        out.append(f)
        if len(out) == 2:
            break
    return out


CUSIP_FILE = "cusip_tickers.json"


def tickers_for(cusips):
    """CUSIP to ticker through OpenFIGI (free, 25 requests a minute without a key). Results are
    kept in the data folder, so each CUSIP is looked up once."""
    p = config.HOME / CUSIP_FILE
    known = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    todo = [c for c in dict.fromkeys(cusips) if c and c not in known]
    for i in range(0, len(todo), 10):
        batch = todo[i:i + 10]
        if i:
            time.sleep(2.5)
        try:
            r = requests.post("https://api.openfigi.com/v3/mapping", timeout=30,
                              json=[{"idType": "ID_CUSIP", "idValue": c} for c in batch])
            if r.status_code == 429:
                time.sleep(60)
                r = requests.post("https://api.openfigi.com/v3/mapping", timeout=30,
                                  json=[{"idType": "ID_CUSIP", "idValue": c} for c in batch])
            r.raise_for_status()
        except requests.RequestException:
            break  # tickers are a convenience; issuer names still identify the holding
        for c, res in zip(batch, r.json()):
            data = res.get("data") or []
            us = [d for d in data if d.get("exchCode") == "US"] or data
            known[c] = us[0]["ticker"].replace("/", "-") if us and us[0].get("ticker") else None
    if todo:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(known), encoding="utf-8")
    return {c: known.get(c) for c in cusips}


def fund(name, top=20):
    cik, label = resolve_fund(name)
    qs = quarters(cik)
    if not qs:
        raise DeskError(f"CIK {cik} has no 13F-HR filings in SEC's recent list.")
    cur = info_table(cik, qs[0]["accession"], qs[0]["filed"])
    prev = info_table(cik, qs[1]["accession"], qs[1]["filed"]) if len(qs) > 1 else None
    stocks = [r for r in cur if not r["option"]]
    total = sum(r["value"] for r in stocks)
    if not total:
        raise DeskError("The latest 13F has no stock holdings with values.")
    before = {r["cusip"]: r for r in prev if not r["option"]} if prev is not None else {}
    stocks.sort(key=lambda r: -r["value"])

    def change(r):
        b = before.get(r["cusip"])
        if prev is None:
            return None
        if not b or not b["shares"]:
            return "new"
        x = (r["shares"] / b["shares"] - 1) * 100
        return "unchanged" if abs(x) < 1 else f"{'added' if x > 0 else 'trimmed'} {abs(x):.0f}%"

    gone = [b for c, b in before.items() if c not in {r["cusip"] for r in stocks}]
    gone.sort(key=lambda b: -b["value"])
    new = [r for r in stocks if change(r) == "new"]
    moved = [(r, (r["shares"] / before[r["cusip"]]["shares"] - 1) * 100) for r in stocks
             if r["cusip"] in before and before[r["cusip"]]["shares"]]
    adds = sorted([m for m in moved if m[1] >= 10], key=lambda m: -m[0]["value"])[:8]
    trims = sorted([m for m in moved if m[1] <= -10], key=lambda m: -before[m[0]["cusip"]]["value"])[:8]
    want = [r["cusip"] for r in stocks[:top]] + [r["cusip"] for r in new[:10]] + [b["cusip"] for b in gone[:10]] + \
           [m[0]["cusip"] for m in adds + trims]
    tick = tickers_for(want)

    def row(r, extra=None):
        out = {"ticker": tick.get(r["cusip"]), "issuer": r["issuer"].title(),
               "weight_pct": _num(r["value"] / total * 100, 1), "value_mn": _num(r["value"] / 1e6, 0)}
        if extra:
            out.update(extra)
        return out

    period = qs[0]["period"]
    lag = (date.today() - date.fromisoformat(period)).days
    options = [r for r in cur if r["option"]]
    out = {
        "fund": label or filer(cik)["name"], "cik": cik, "quarter_end": period, "filed": qs[0]["filed"],
        "days_since_quarter_end": lag, "compared_with": qs[1]["period"] if len(qs) > 1 else None,
        "positions": len(stocks), "value_bn": _num(total / 1e9, 2),
        "top10_pct": _num(sum(r["value"] for r in stocks[:10]) / total * 100, 1),
        "holdings": [row(r, {"change": change(r)}) for r in stocks[:top]],
        "new_positions": [row(r) for r in new[:10]],
        "sold_out": [{"ticker": tick.get(b["cusip"]), "issuer": b["issuer"].title(),
                      "value_last_quarter_mn": _num(b["value"] / 1e6, 0)} for b in gone[:10]],
        "biggest_adds": [row(r, {"shares_change_pct": _num(x, 0)}) for r, x in adds],
        "biggest_trims": [row(r, {"shares_change_pct": _num(x, 0)}) for r, x in trims],
        "notes": ["A 13F shows US-listed long positions at the quarter end. It leaves out shorts, cash, bonds and "
                  "non-US stocks, so it is not the whole portfolio.",
                  f"These holdings are {lag} days old. The fund may have sold since."],
    }
    if options:
        out["options_positions"] = len(options)
        out["notes"].append(f"{len(options)} option positions (puts or calls) are left out of the weights; "
                            "13F values them at the underlying stock, not the premium.")
    if lag > STALE_DAYS:
        out["notes"].append("The latest filing is old. The fund may have stopped filing 13Fs.")
    if any(f["form"] == "13F-HR/A" and f["period"] == period for f in filer(cik)["filings"]):
        out["notes"].append("There is an amendment for this quarter; it can add holdings the original left out.")
    return out


def consensus(top=15):
    holders, new_by, funds_used, skipped = {}, {}, [], []
    names = {}
    for key, (cik, label, style) in FUNDS.items():
        if style != "picker":
            continue
        try:
            qs = quarters(cik)
            if not qs or (date.today() - date.fromisoformat(qs[0]["period"])).days > STALE_DAYS:
                skipped.append(label)
                continue
            cur = [r for r in info_table(cik, qs[0]["accession"], qs[0]["filed"]) if not r["option"]]
            prev = ({r["cusip"] for r in info_table(cik, qs[1]["accession"], qs[1]["filed"]) if not r["option"]}
                    if len(qs) > 1 else None)
        except (DeskError, requests.RequestException, ET.ParseError) as e:
            skipped.append(f"{label} ({e})")
            continue
        total = sum(r["value"] for r in cur) or 1
        funds_used.append({"fund": label, "quarter_end": qs[0]["period"]})
        for r in cur:
            names[r["cusip"]] = r["issuer"]
            holders.setdefault(r["cusip"], []).append((label, r["value"] / total * 100))
            if prev is not None and r["cusip"] not in prev:
                new_by.setdefault(r["cusip"], []).append((label, r["value"] / total * 100))
    most = sorted(holders.items(), key=lambda kv: (-len(kv[1]), -sum(w for _, w in kv[1])))[:top]
    newest = sorted(new_by.items(), key=lambda kv: (-len(kv[1]), -sum(w for _, w in kv[1])))[:top]
    tick = tickers_for([c for c, _ in most + newest])

    def rows(items):
        return [{"ticker": tick.get(c), "issuer": names[c].title(), "funds": len(v),
                 "average_weight_pct": _num(sum(w for _, w in v) / len(v), 1),
                 "who": [f"{n} {w:.1f}%" for n, w in sorted(v, key=lambda x: -x[1])][:6]} for c, v in items]

    return {"funds_counted": len(funds_used), "quarter_end": max((f["quarter_end"] for f in funds_used), default=None),
            "most_held": rows(most), "most_new_positions": rows(newest),
            **({"skipped": skipped} if skipped else {}),
            "notes": ["Counts the stock-picking funds in 'funds' only. Owning the same stock as famous investors "
                      "says nothing about the price you would pay today.",
                      "13F data is 45 to 135 days old by the time anyone reads it."]}


def funds_list():
    return [{"key": k, "name": v[1], "cik": v[0], "in_consensus": v[2] == "picker"} for k, v in FUNDS.items()]


# ---------- Form 4 ----------

CODES = {"P": "open-market buy", "S": "open-market sale", "A": "grant or award", "M": "option exercise",
         "F": "shares withheld for tax", "G": "gift", "D": "returned to company", "C": "conversion",
         "X": "option exercise", "J": "other"}


def parse_form4(xml_bytes):
    root = ET.fromstring(xml_bytes)

    def t(node, path):
        el = node.find(path)
        return (el.text or "").strip() if el is not None and el.text else ""

    owners = []
    for o in root.findall("reportingOwner"):
        rel = o.find("reportingOwnerRelationship")
        role = []
        if rel is not None:
            if t(rel, "officerTitle"):
                role.append(t(rel, "officerTitle"))
            elif t(rel, "isOfficer") in ("1", "true"):
                role.append("officer")
            if t(rel, "isDirector") in ("1", "true"):
                role.append("director")
            if t(rel, "isTenPercentOwner") in ("1", "true"):
                role.append("10% owner")
        owners.append({"name": t(o, "reportingOwnerId/rptOwnerName").title(), "role": ", ".join(role) or "other"})
    notes = " ".join((f.text or "") for f in root.iter("footnote"))
    plan = t(root, "aff10b5One") in ("1", "true") or "10b5-1" in notes
    trades = []
    for tr in root.iter("nonDerivativeTransaction"):
        code = t(tr, "transactionCoding/transactionCode")
        sh = float(t(tr, "transactionAmounts/transactionShares/value") or 0)
        px = float(t(tr, "transactionAmounts/transactionPricePerShare/value") or 0)
        after = t(tr, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
        trades.append({"date": t(tr, "transactionDate/value")[:10], "code": code, "shares": sh, "price": px,
                       "owned_after": float(after) if after else None})
    issuer = t(root, "issuer/issuerCik")
    return {"issuer_cik": int(issuer) if issuer.isdigit() else None, "owners": owners, "plan": plan,
            "trades": trades}


def insiders(ticker, days=180, max_filings=80):
    since = (date.today() - timedelta(days=days)).isoformat()
    data = sec.submissions(ticker)
    rec, cik = data["recent"], data["cik"]
    picks = [i for i, f in enumerate(rec.get("form", [])) if f == "4" and rec["filingDate"][i] >= since]
    truncated = len(picks) > max_filings
    rows = []
    as_owner = 0
    for i in picks[:max_filings]:
        acc = rec["accessionNumber"][i]
        key = f"f4v2:{acc}"
        parsed = cache.get_json("filed", key)
        if parsed is None:
            doc = rec["primaryDocument"][i].split("/")[-1]
            try:
                parsed = parse_form4(sec.get(
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}").content)
            except (ET.ParseError, requests.RequestException):
                continue
            cache.put_json("filed", key, parsed)
        if parsed.get("issuer_cik") not in (None, int(cik)):
            # The company itself filed as an owner of another stock (Berkshire buying OXY, say).
            as_owner += 1
            continue
        who = parsed["owners"][0] if parsed["owners"] else {"name": "?", "role": "?"}
        for tr in parsed["trades"]:
            rows.append({**tr, "insider": who["name"], "role": who["role"], "plan": parsed["plan"],
                         "filed": rec["filingDate"][i]})
    buys = [r for r in rows if r["code"] == "P"]
    sells = [r for r in rows if r["code"] == "S"]
    other = {}
    for r in rows:
        if r["code"] not in ("P", "S"):
            other[CODES.get(r["code"], r["code"])] = other.get(CODES.get(r["code"], r["code"]), 0) + 1

    def value(rs):
        return sum(r["shares"] * r["price"] for r in rs)

    def show(r):
        sold_share = None
        if r["code"] == "S" and r["owned_after"] is not None and r["shares"]:
            sold_share = r["shares"] / (r["shares"] + r["owned_after"]) * 100
        return {"date": r["date"], "insider": r["insider"], "role": r["role"], "type": CODES.get(r["code"]),
                "shares": _num(r["shares"], 0), "price": _num(r["price"]), "value_usd": _num(r["shares"] * r["price"], 0),
                **({"pct_of_holding_sold": _num(sold_share, 0)} if sold_share is not None else {}),
                **({"under_10b5_1_plan": True} if r["plan"] else {})}

    # A cluster: three or more different insiders buying in the open market within 30 days.
    cluster = None
    bs = sorted(buys, key=lambda r: r["date"])
    for j, r in enumerate(bs):
        end = (date.fromisoformat(r["date"]) + timedelta(days=30)).isoformat()
        names = {x["insider"] for x in bs[j:] if x["date"] <= end}
        if len(names) >= 3:
            cluster = {"from": r["date"], "insiders": sorted(names)}
            break
    planned = [r for r in sells if r["plan"]]
    return {
        "company": data["company"], "ticker": ticker.upper(), "since": since, "form4_filings": len(picks) - as_owner,
        **({"filed_as_owner_of_other_stocks": as_owner} if as_owner else {}),
        "open_market_buys": {"count": len(buys), "insiders": len({r["insider"] for r in buys}),
                             "value_usd": _num(value(buys), 0)},
        "open_market_sales": {"count": len(sells), "insiders": len({r["insider"] for r in sells}),
                              "value_usd": _num(value(sells), 0),
                              "share_under_10b5_1_plan_pct": _num(len(planned) / len(sells) * 100, 0) if sells else None},
        "cluster_buy": cluster,
        "largest_buys": [show(r) for r in sorted(buys, key=lambda r: -r["shares"] * r["price"])[:10]],
        "largest_sales": [show(r) for r in sorted(sells, key=lambda r: -r["shares"] * r["price"])[:10]],
        "other_transactions": other,
        "notes": ["Grants, option exercises and shares withheld for tax are routine pay, not trading decisions.",
                  "Sales under a 10b5-1 plan were scheduled months in advance. Open-market buys are rarer and "
                  "say more, because insiders sell for many reasons but buy for one."]
        + ([f"Only the newest {max_filings} of {len(picks)} filings were read. Shorten --days for the full picture."]
           if truncated else []),
    }


# ---------- Congress (House) ----------

HOUSE = "https://disclosures-clerk.house.gov/public_disc"
HOUSE_UA = {"User-Agent": "Mozilla/5.0 (compatible; stock-trader-skills/0.7)"}
TX = {"P": "purchase", "S": "sale", "S (partial)": "partial sale", "E": "exchange"}
ROW = re.compile(
    r"\(([A-Z][A-Z0-9.\-/]{0,7})\)\s*\[([A-Z]{2})\]\s*(P|S \(partial\)|S|E)\s+(\d{2}/\d{2}/\d{4})\s+"
    r"(\d{2}/\d{2}/\d{4})\s+(\$[\d,]+\s*-\s*\$[\d,]+|Over \$[\d,]+|\$[\d,]+\s*\+?)")


def house_index(year):
    key = f"house:{year}"
    rows = cache.get_json("listing", key)
    if rows is None:
        r = requests.get(f"{HOUSE}/financial-pdfs/{year}FD.zip", headers=HOUSE_UA, timeout=60)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".xml"))))
        rows = []
        for m in root:
            d = {c.tag: (c.text or "").strip() for c in m}
            if d.get("FilingType") != "P":
                continue
            try:
                filed = datetime.strptime(d["FilingDate"], "%m/%d/%Y").date().isoformat()
            except (KeyError, ValueError):
                continue
            rows.append({"member": " ".join(x for x in (d.get("First"), d.get("Last")) if x),
                         "district": d.get("StateDst"), "filed": filed, "doc": d.get("DocID"), "year": year})
        cache.put_json("listing", key, rows)
    return rows


def amount_range(text):
    nums = [int(x.replace(",", "")) for x in re.findall(r"\$([\d,]+)", text)]
    if not nums:
        return None, None
    return nums[0], nums[1] if len(nums) > 1 else None


def parse_ptr(text):
    flat = re.sub(r"\s+", " ", text)
    out = []
    for m in ROW.finditer(flat):
        before = flat[max(0, m.start() - 120):m.start()]
        owner = re.search(r"\b(SP|DC|JT)\s+[^()]*$", before)
        lo, hi = amount_range(m.group(6))
        out.append({"ticker": m.group(1).replace("/", "-").replace(".", "-"), "asset_type": m.group(2),
                    "type": TX[m.group(3)], "traded": datetime.strptime(m.group(4), "%m/%d/%Y").date().isoformat(),
                    "notified": datetime.strptime(m.group(5), "%m/%d/%Y").date().isoformat(),
                    "amount_low": lo, "amount_high": hi,
                    "owner": {"SP": "spouse", "DC": "dependent child", "JT": "joint"}.get(owner.group(1)) if owner
                    else "member"})
    return out


def ptr_trades(row):
    key = f"ptr:{row['year']}:{row['doc']}"
    cached = cache.get_json("filed", key)
    if cached is not None:
        return cached
    from pypdf import PdfReader  # only this command needs it
    r = requests.get(f"{HOUSE}/ptr-pdfs/{row['year']}/{row['doc']}.pdf", headers=HOUSE_UA, timeout=60)
    if r.status_code != 200:
        return {"readable": False, "trades": []}
    try:
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
    except Exception:  # noqa: BLE001 - a damaged PDF is skipped, not fatal
        text = ""
    out = {"readable": bool(text.strip()), "trades": parse_ptr(text)}
    cache.put_json("filed", key, out)
    time.sleep(0.2)
    return out


def congress(days=60, ticker=None, member=None, max_reports=200):
    try:
        import pypdf  # noqa: F401
    except ImportError:
        raise DeskError("The congress command needs pypdf. Install it with: pip install pypdf")
    since = date.today() - timedelta(days=days)
    reports = []
    for y in sorted({since.year, date.today().year}):
        reports += [r for r in house_index(y) if r["filed"] >= since.isoformat()]
    if member:
        reports = [r for r in reports if member.lower() in r["member"].lower()]
    reports.sort(key=lambda r: r["filed"], reverse=True)
    truncated = len(reports) > max_reports
    trades, unreadable = [], 0
    for r in reports[:max_reports]:
        res = ptr_trades(r)
        if not res["readable"]:
            unreadable += 1
        for t in res["trades"]:
            trades.append({**t, "member": r["member"], "district": r["district"], "filed": r["filed"]})
    stocks = [t for t in trades if t["asset_type"] in ("ST", "OP")]
    if ticker:
        tk = ticker.upper().replace(".", "-")
        hits = sorted([t for t in stocks if t["ticker"] == tk], key=lambda t: t["traded"], reverse=True)
        return {"ticker": tk, "since": since.isoformat(), "reports_read": min(len(reports), max_reports),
                "trades": hits, "members": sorted({t["member"] for t in hits}),
                "notes": _congress_notes(unreadable, truncated)}

    def board(kind):
        agg = {}
        for t in stocks:
            if (kind == "buy") != (t["type"] == "purchase"):
                continue
            if t["type"] == "exchange":
                continue
            a = agg.setdefault(t["ticker"], {"ticker": t["ticker"], "members": set(), "trades": 0, "low": 0, "high": 0})
            a["members"].add(t["member"])
            a["trades"] += 1
            a["low"] += t["amount_low"] or 0
            a["high"] += t["amount_high"] or t["amount_low"] or 0
        rows = sorted(agg.values(), key=lambda a: (-len(a["members"]), -a["high"]))[:15]
        return [{"ticker": a["ticker"], "members": len(a["members"]), "trades": a["trades"],
                 "amount_range_usd": f"{a['low']:,}-{a['high']:,}", "who": sorted(a["members"])[:5]} for a in rows]

    lags = [(date.fromisoformat(t["filed"]) - date.fromisoformat(t["traded"])).days for t in stocks]
    lst = universe.listing() if stocks else {}
    out = {"since": since.isoformat(), "reports": len(reports), "reports_read": min(len(reports), max_reports),
           "stock_trades": len(stocks), "members_trading": len({t["member"] for t in stocks}),
           "most_bought": board("buy"), "most_sold": board("sell"),
           "median_days_trade_to_filing": sorted(lags)[len(lags) // 2] if lags else None,
           "notes": _congress_notes(unreadable, truncated)}
    for row in out["most_bought"] + out["most_sold"]:
        row["name"] = (lst.get(row["ticker"]) or {}).get("name", "")[:40] or None
    if member:
        out["trades"] = sorted(stocks, key=lambda t: t["traded"], reverse=True)[:40]
    return out


def _congress_notes(unreadable, truncated):
    notes = ["House members only. Senate reports sit behind a terms-of-use page and are not read.",
             "Amounts are the ranges the law requires, not exact figures. Trades include spouses' and children's "
             "accounts, and many are made by outside managers.",
             "A trade can be reported up to 45 days after it happened."]
    if unreadable:
        notes.append(f"{unreadable} reports were scanned paper forms with no readable text and were skipped.")
    if truncated:
        notes.append("Only the newest 200 reports were read. Shorten --days for the full picture.")
    return notes


def main():
    ap = argparse.ArgumentParser(description="13F funds, insider trades and Congress trades from official filings.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("funds")
    f = sub.add_parser("fund")
    f.add_argument("name", help="a key from 'funds' or an SEC CIK number")
    f.add_argument("--top", type=int, default=20)
    sub.add_parser("consensus")
    i = sub.add_parser("insiders")
    i.add_argument("ticker")
    i.add_argument("--days", type=int, default=180)
    c = sub.add_parser("congress")
    c.add_argument("--days", type=int, default=60)
    c.add_argument("--ticker")
    c.add_argument("--member")
    a = ap.parse_args()
    actions = {"funds": funds_list, "fund": lambda: fund(a.name, a.top), "consensus": consensus,
               "insiders": lambda: insiders(a.ticker, a.days),
               "congress": lambda: congress(a.days, a.ticker, a.member)}
    return run(actions[a.cmd])


if __name__ == "__main__":
    sys.exit(main())
