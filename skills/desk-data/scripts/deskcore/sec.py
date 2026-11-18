"""SEC EDGAR: official US filings, free. SEC requires a User-Agent with contact info
and allows at most 10 requests per second."""
import time

import requests

from . import DeskError, cache, config

_last_call = [0.0]


def _get(url):
    ua = config.load().get("sec_user_agent")
    if not ua:
        raise DeskError("SEC needs a contact User-Agent. Run desk-setup with "
                        "--sec-user-agent \"Your Name your@email\".")
    wait = 0.12 - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()
    r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=20)
    if r.status_code == 403:
        raise DeskError("SEC refused the request (403). Check that your User-Agent has a real contact email.")
    r.raise_for_status()
    return r


def cik_for(ticker):
    m = cache.get_json("sec_map", "tickers")
    if m is None:
        raw = _get("https://www.sec.gov/files/company_tickers.json").json()
        m = {v["ticker"].upper(): [str(v["cik_str"]).zfill(10), v["title"]] for v in raw.values()}
        cache.put_json("sec_map", "tickers", m)
    t = ticker.upper().replace(".", "-")
    if t not in m:
        raise DeskError(f"'{ticker}' is not in SEC's ticker list (SEC covers US-listed companies only).")
    return m[t]


# 8-K item numbers and what they mean (SEC Form 8-K general instructions).
EIGHT_K_ITEMS = {
    "1.01": "material agreement signed", "1.02": "material agreement ended",
    "1.03": "bankruptcy or receivership", "1.05": "cybersecurity incident",
    "2.01": "acquisition or disposal completed", "2.02": "results of operations",
    "2.03": "new debt or obligation", "2.05": "exit or restructuring costs",
    "2.06": "material impairment", "3.01": "delisting notice",
    "3.02": "unregistered share sale", "3.03": "change to shareholder rights",
    "4.01": "auditor changed", "4.02": "past financials no longer reliable",
    "5.01": "change in control", "5.02": "director or officer change",
    "5.03": "bylaws or fiscal year changed", "5.07": "shareholder vote results",
    "7.01": "Regulation FD disclosure", "8.01": "other events",
}


def submissions(ticker):
    """Company metadata and recent filings from SEC's submissions API, cached for a day."""
    cik, name = cik_for(ticker)
    data = cache.get_json("filings", cik)
    if data is None:
        raw = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
        older = raw.get("filings", {}).get("files", [])
        data = {
            "recent": raw.get("filings", {}).get("recent", {}),
            "sic": raw.get("sicDescription"),
            "fiscal_year_end": raw.get("fiscalYearEnd"),
            "state_of_incorporation": raw.get("stateOfIncorporation"),
            "former_names": [{"name": f["name"], "from": f["from"][:10], "to": f["to"][:10]}
                             for f in raw.get("formerNames", [])],
        }
        dates = [f["filingFrom"] for f in older if f.get("filingFrom")] + data["recent"].get("filingDate", [])
        data["first_filing"] = min(dates) if dates else None
        cache.put_json("filings", cik, data)
    data["cik"], data["company"] = cik, name
    return data


def filings(ticker, forms=("10-K", "10-Q", "8-K"), limit=10, since=None):
    data = submissions(ticker)
    cik, rec = data["cik"], data["recent"]
    want = {f.upper() for f in forms} if forms else None
    out = []
    for i, form in enumerate(rec.get("form", [])):
        if want and form.upper() not in want:
            continue
        if since and rec["filingDate"][i] < since:
            break  # newest first
        acc = rec["accessionNumber"][i]
        doc = rec["primaryDocument"][i]
        row = {
            "form": form,
            "filed": rec["filingDate"][i],
            "period": rec.get("reportDate", [""] * (i + 1))[i],
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}",
        }
        items = (rec.get("items") or [""] * (i + 1))[i]
        if form.startswith("8-K") and items:
            row["items"] = [EIGHT_K_ITEMS.get(x.strip(), x.strip()) for x in items.split(",")
                            if x.strip() != "9.01"]  # 9.01 is just "exhibits attached"
        out.append(row)
        if len(out) >= limit:
            break
    return {"company": data["company"], "cik": cik, "industry": data.get("sic"),
            "fiscal_year_end": data.get("fiscal_year_end"), "filings": out}
