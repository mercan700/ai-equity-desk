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


def filings(ticker, forms=("10-K", "10-Q", "8-K"), limit=10):
    cik, name = cik_for(ticker)
    data = cache.get_json("filings", cik)
    if data is None:
        data = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
        data = {"recent": data.get("filings", {}).get("recent", {}),
                "sic": data.get("sicDescription"), "fiscal_year_end": data.get("fiscalYearEnd")}
        cache.put_json("filings", cik, data)
    rec = data["recent"]
    want = {f.upper() for f in forms} if forms else None
    out = []
    for i, form in enumerate(rec.get("form", [])):
        if want and form.upper() not in want:
            continue
        acc = rec["accessionNumber"][i]
        doc = rec["primaryDocument"][i]
        out.append({
            "form": form,
            "filed": rec["filingDate"][i],
            "period": rec.get("reportDate", [""] * (i + 1))[i],
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}",
        })
        if len(out) >= limit:
            break
    return {"company": name, "cik": cik, "industry": data.get("sic"),
            "fiscal_year_end": data.get("fiscal_year_end"), "filings": out}
