"""Company background from Wikipedia: the lead section and the history section.

Uses the public MediaWiki API, no key. Wikipedia asks automated clients to send
a descriptive User-Agent and to keep request rates low; a lookup takes two to
four requests, spaced a second apart, and the result is cached for 30 days.
"""
import re
import time
from urllib.parse import unquote

import requests

from . import DeskError, cache

UA = {"User-Agent": "stock-trader-skills/0.6 (personal stock research tool)"}
HISTORY_HEADINGS = re.compile(r"^(history|corporate history|company history|tarihçe|tarihçesi|tarih)$", re.I)

# Legal-form words that make a search miss ("Türk Hava Yollari Anonim Ortakligi").
SUFFIXES = re.compile(
    r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|sa|ag|nv|se|"
    r"holdings? inc|anonim (ş|s)irketi|anonim ortakl[ıi]g[ıi]|a\.?\s?(ş|s)\.?|t\.?\s?a\.?\s?(ş|s)\.?)\.?$",
    re.I)

# Words that show a search hit is about a business, not a fruit or a drink.
COMPANY_WORDS = re.compile(
    r"\b(company|corporation|conglomerate|multinational|manufacturer|retailer|airline|carrier|bank|"
    r"holding|group|firm|enterprise|producer|operator|provider|şirket\w*|firma\w*|holding\w*|"
    r"kuruluş\w*|üretici\w*|perakende\w*|banka\w*)\b", re.I)

_last_call = [0.0]


def clean_name(name):
    n = (name or "").strip()
    for _ in range(3):
        n2 = SUFFIXES.sub("", n).strip(" ,.")
        if n2 == n:
            break
        n = n2
    return n


def _api(lang, **params):
    """One MediaWiki API call, at most one per second, retried once after a 429."""
    for attempt in (1, 2):
        wait = 1.0 - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php",
                         params={"format": "json", "formatversion": 2, **params}, headers=UA, timeout=20)
        if r.status_code == 429 and attempt == 1:
            time.sleep(min(float(r.headers.get("Retry-After", 5) or 5), 30))
            continue
        if r.status_code == 429:
            raise DeskError("Wikipedia is rate-limiting this computer. Try again in a minute.")
        r.raise_for_status()
        return r.json()


def split_sections(text):
    """Plain-text extract -> [(heading, level, body)], the lead section first with level 1."""
    parts = re.split(r"\n(={2,6}) (.+?) \1\n", "\n" + text)
    out = [("", 1, parts[0].strip())]
    for i in range(1, len(parts) - 1, 3):
        out.append((parts[i + 1].strip(), len(parts[i]), parts[i + 2].strip()))
    return out


def history_text(sections, limit):
    """Body of the history section including its subsections, cut at `limit` characters."""
    chunks, inside, level = [], False, 0
    for head, lvl, body in sections[1:]:
        if inside and lvl <= level:
            break
        if not inside and HISTORY_HEADINGS.match(head):
            inside, level = True, lvl
            chunks.append(body)
            continue
        if inside:
            chunks.append(f"[{head}] {body}")
    text = "\n".join(c for c in chunks if c).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " ..."
    return text


TR_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")


def norm(text):
    """Lowercase ASCII words, so 'Yolları' in an article matches 'Yollari' from Yahoo."""
    return re.findall(r"[a-z0-9]+", text.translate(TR_ASCII).lower())


def pick(results, short_name):
    """The search hit that shares the most words with the company name and reads like a
    company article. Turkish Airlines' snippet contains 'Türk Hava Yolları', so it beats
    an article that only shares the word 'Türk'."""
    words = {w for w in norm(short_name) if len(w) > 2}
    need = min(2, len(words)) or 1
    first = next((w for w in norm(short_name) if len(w) > 2), None)
    best, best_score = None, 0
    for r in results:
        title, snippet = r["title"], re.sub(r"<[^>]+>", "", r.get("snippet", ""))
        if title.lower().startswith("list of"):
            continue
        if not (COMPANY_WORDS.search(snippet) or COMPANY_WORDS.search(title)):
            continue
        found = set(norm(title + " " + snippet))
        overlap = len(words & found)
        in_title = bool(first and first in norm(title))
        # The name's first word in the title, or most of the name in the snippet. Two shared
        # generic words ('sanayi', 'ticaret') are not enough: they put Aselsan on Is Bankasi.
        if not (in_title or overlap >= max(need, min(3, len(words)))):
            continue
        score = overlap + (1 if in_title else 0)
        if overlap >= need and score > best_score:
            best, best_score = title, score
    return best


EXCHANGES = {"US": ("new york stock exchange", "nasdaq", "nyse american"), "BIST": ("borsa istanbul",)}
SPARQL = """SELECT ?exLabel ?en ?tr WHERE {
 ?item p:P414 ?st . ?st pq:P249 "%s" ; ps:P414 ?ex .
 OPTIONAL { ?en schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }
 OPTIONAL { ?tr schema:about ?item ; schema:isPartOf <https://tr.wikipedia.org/> . }
 SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } } LIMIT 10"""


def titles_by_ticker(ticker, market):
    """{lang: article title} from Wikidata's ticker-symbol records (P249 on a P414 listing).
    Exact where it exists; many smaller companies have no ticker recorded, so the caller
    falls back to search."""
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", ticker or ""):
        return {}
    try:
        r = requests.get("https://query.wikidata.org/sparql", headers=UA, timeout=30,
                         params={"query": SPARQL % ticker, "format": "json"})
        r.raise_for_status()
        rows = r.json()["results"]["bindings"]
    except (requests.RequestException, ValueError, KeyError):
        return {}
    allowed = EXCHANGES.get(market, ())
    for row in rows:
        if row["exLabel"]["value"].lower() in allowed:
            return {lang: unquote(row[lang]["value"].rsplit("/wiki/", 1)[1]).replace("_", " ")
                    for lang in ("en", "tr") if lang in row}
    return {}


def find_title(name, lang):
    short = clean_name(name)
    tried = []
    first = short.split()[0] if short else ""
    for q in (name, f"{short} company", short, first, f"{first} company"):
        if not q or q in tried:
            continue
        tried.append(q)
        hits = _api(lang, action="query", list="search", srsearch=q, srlimit=5)["query"]["search"]
        title = pick(hits, short)
        if title:
            return title
    return None


def _article(lang, title, lead_chars, history_chars):
    page = _api(lang, action="query", prop="extracts", explaintext=1, titles=title,
                exsectionformat="wiki", redirects=1)["query"]["pages"][0]
    if page.get("missing"):
        return None
    sections = split_sections(page.get("extract", ""))
    lead = sections[0][2]
    real = page.get("title", title)
    return {
        "title": real,
        "url": f"https://{lang}.wikipedia.org/wiki/{real.replace(' ', '_')}",
        "language": lang,
        "lead": lead[:lead_chars].rsplit(" ", 1)[0] + (" ..." if len(lead) > lead_chars else ""),
        "history": history_text(sections, history_chars),
        "sections": [h for h, lvl, _ in sections[1:] if lvl == 2][:15],
    }


def company(name, langs=("en",), lead_chars=1200, history_chars=3500, title=None, ticker=None, market=None):
    """The company's article: `title` if given, else Wikidata's ticker record, else a name search.
    When the first language's article has no history section, the next language's history is
    added (Turkish articles often have a Tarihçe section the English one lacks)."""
    query = clean_name(name)
    if not query and not title and not ticker:
        raise DeskError("No company name to look up.")
    key = f"{title or ticker or name}:{market}:{','.join(langs)}"
    hit = cache.get_json("story", key)
    if hit is not None:
        return hit
    known = {langs[0]: title} if title else (titles_by_ticker(ticker, market) if ticker else {})
    out = None
    for lang in langs:
        t = known.get(lang) or (None if title else find_title(name, lang) if query else None)
        art = _article(lang, t, lead_chars, history_chars) if t else None
        if not art:
            continue
        art["matched_by"] = "given title" if title else "ticker (Wikidata)" if lang in known else "name search"
        if out is None:
            out = art
            if out["history"]:
                break
        elif art["history"]:
            out["history"] = art["history"]
            out["history_source"] = art["url"]
            break
    if out is None:
        raise DeskError(f"No Wikipedia article found for '{query or ticker}'.")
    return cache.put_json("story", key, out)
