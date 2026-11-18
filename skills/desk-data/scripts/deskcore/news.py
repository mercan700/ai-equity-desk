"""Recent headlines about one company, from Yahoo Finance and Google News RSS.

Both are free and keyless. Yahoo's feed for a ticker often carries general market
stories (THYAO's feed returned a GE article), and Google matches loosely, so every
item must mention the ticker or the company's name to be kept. Headlines are tagged
by topic with English and Turkish keywords; reading what they mean is left to Claude.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from . import cache
from .prices import _yf
from .wiki import clean_name, norm

UA = {"User-Agent": "Mozilla/5.0 (compatible; stock-trader-skills/0.6)"}

# Topic -> keywords. Matching is on ASCII-folded lowercase text (see wiki.norm), so the
# Turkish words are written without Turkish letters: 'bilanco' matches 'bilanço'.
TOPICS = {
    "earnings": r"earnings|results|quarter|revenue|profit|eps|beat|miss|bilanco|kar\b|kari\b|net kar|ciro|"
                r"ceyrek|gelir|zarar",
    "guidance": r"guidance|outlook|forecast|expects|raises|cuts|beklenti|hedef|tahmin",
    "deal": r"acquir|acquisition|merger|takeover|buyout|stake|divest|spin.?off|satin al|birlesme|devral|"
            r"hisse satis|pay devri",
    "legal_regulatory": r"lawsuit|sued|probe|investigation|antitrust|fine|settle|sec\b|regulator|ban\b|"
                        r"dava|sorusturma|ceza|rekabet kurumu|spk|bddk",
    "management": r"\bceo\b|\bcfo\b|chief executive|resign|appoint|steps down|board|genel mudur|"
                  r"yonetim kurulu|atama|istifa",
    "capital": r"dividend|buyback|repurchase|share offering|secondary|rights issue|bond|debt|"
               r"temettu|geri al|bedelsiz|bedelli|sermaye artirim|tahvil|borclanma",
    "rating": r"upgrade|downgrade|price target|rating|overweight|underweight|outperform|"
              r"hedef fiyat|tavsiye|endeksin uzerinde|endeksin altinda",
    "product_operations": r"launch|contract|order|deal with|partnership|plant|factory|recall|outage|strike|"
                          r"siparis|sozlesme|ihale|anlasma|fabrika|yatirim karari|grev|teslimat|yolcu",
    "ownership": r"stake in|raises stake|holding in|13d|13g|payi|paylarinda net|pay orani|ortaklik yapisi",
    "trading_flow": r"yuklu alim|yuklu satis|blok islem|para girisi|para cikisi|ozel emir|araci kurum|"
                    r"en cok (alan|satan)|takas|tavan|taban|unusual options|short interest",
    "macro": r"tariff|interest rate|fed\b|inflation|currency|lira|recession|faiz|enflasyon|kur\b|doviz|tcmb",
}
TOPIC_RE = {k: re.compile(r"\b(?:" + v + ")", re.I) for k, v in TOPICS.items()}


def fold(text):
    return " ".join(norm(text or ""))


def topics(text):
    t = fold(text)
    return [k for k, rx in TOPIC_RE.items() if rx.search(t)]


def strip_source(title, source):
    """Google News titles end in ' - Publisher'."""
    if source and title.endswith(" - " + source):
        return title[: -len(source) - 3]
    return title


def dedupe_key(title):
    return " ".join(fold(title).split()[:8])


# First words too common to identify a company alone ('Turk' Hava Yollari, 'General' Electric).
GENERIC_FIRST = {"turk", "turkiye", "turkish", "american", "united", "general", "first", "national",
                 "international", "bank", "global", "new"}


OTHER_LISTING = re.compile(r"\((?:NYSE|NASDAQ|NYSEAMERICAN|AMEX|OTC|BIST)\s*:\s*([A-Z.\-]+)\)", re.I)


def about_another(title, ticker):
    """MarketBeat-style headlines tag the subject: 'Energizer (NYSE:ENR) Gets Price Target from
    JPMorgan'. If the tagged ticker is not ours, the story is about someone else."""
    tagged = {m.upper() for m in OTHER_LISTING.findall(title)}
    return bool(tagged) and ticker.upper() not in tagged


def relevant(text, ticker, name_words):
    words = set(fold(text).split())
    if ticker.lower() in words:
        return True
    if not name_words:
        return False
    need = name_words[:2] if name_words[0] in GENERIC_FIRST else name_words[:1]
    return all(w in words for w in need)


def name_words(name):
    """Distinctive words of the company name, first word first ('turk', 'hava', 'yollari')."""
    return [w for w in norm(clean_name(name)) if len(w) > 2 and w not in {"the", "and", "ve"}]


def google(query, lang):
    params = {"q": query, "hl": "tr", "gl": "TR", "ceid": "TR:tr"} if lang == "tr" else \
             {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    r = requests.get("https://news.google.com/rss/search", params=params, headers=UA, timeout=20)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        src_el = it.find("source")
        source = src_el.text if src_el is not None else ""
        try:
            when = parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        out.append({"title": strip_source(it.findtext("title") or "", source), "source": source,
                    "published": when, "url": it.findtext("link"), "feed": "google"})
    return out


def yahoo(sym):
    out = []
    for n in _yf().Ticker(sym).news or []:
        c = n.get("content") or {}
        try:
            when = datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"title": c.get("title") or "", "summary": c.get("summary") or "",
                    "source": (c.get("provider") or {}).get("displayName", ""),
                    "published": when, "url": (c.get("canonicalUrl") or {}).get("url"), "feed": "yahoo"})
    return out


def collect(ticker, sym, name, market, days=30, limit=25):
    key = f"{sym}:{days}:{limit}"
    hit = cache.get_json("news", key)
    if hit is not None:
        return hit
    words = name_words(name)
    short = clean_name(name)
    if market == "BIST":
        queries = [(f'"{ticker}" when:{days}d', "tr"),
                   (f'"{short}" (hisse OR borsa OR bilanço OR KAP) when:{days}d', "tr")]
    else:
        queries = [(f'"{ticker}" stock when:{days}d', "en"), (f'"{short}" when:{days}d', "en")]

    raw, errors = [], []
    for q, lang in queries:
        try:
            raw += google(q, lang)
        except (requests.RequestException, ET.ParseError) as e:
            errors.append(f"Google News: {type(e).__name__}")
    try:
        raw += yahoo(sym)
    except Exception as e:  # noqa: BLE001  (yfinance raises many kinds)
        errors.append(f"Yahoo: {type(e).__name__}")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    seen, items, off_topic = set(), [], 0
    for it in sorted(raw, key=lambda x: x["published"], reverse=True):
        if it["published"] < since:
            continue
        k = dedupe_key(it["title"])
        if not k or k in seen:
            continue
        seen.add(k)
        if about_another(it["title"], ticker) or                 not relevant(it["title"] + " " + it.get("summary", ""), ticker, words):
            off_topic += 1
            continue
        row = {"date": it["published"].strftime("%Y-%m-%d"), "title": it["title"], "source": it["source"],
               "topics": topics(it["title"] + " " + it.get("summary", "")), "url": it["url"]}
        if it.get("summary"):
            row["summary"] = it["summary"][:300]
        items.append(row)

    counts = {}
    for it in items:
        for t in it["topics"] or ["other"]:
            counts[t] = counts.get(t, 0) + 1
    out = {"days": days, "found": len(items), "dropped_off_topic": off_topic,
           "topic_counts": dict(sorted(counts.items(), key=lambda x: -x[1])),
           "items": items[:limit]}
    if errors:
        out["source_errors"] = errors
    return cache.put_json("news", key, out)
