"""Minimal, rate-limited client for the arXiv API (https://info.arxiv.org/help/api/)."""
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API = "https://export.arxiv.org/api/query"
USER_AGENT = "openai-math-citation-study/0.1 (academic research)"
DELAY = 3.0  # arXiv asks for no more than one request every three seconds
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
      "os": "http://a9.com/-/spec/opensearch/1.1/"}
_last = 0.0


def get(url, retries=6):
    global _last
    for attempt in range(retries):
        wait = _last + DELAY - time.time()
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # network hiccups, 429s and 503s: back off and retry
            print(f"  retry {attempt + 1} for {url[:100]}: {e}")
            time.sleep(60 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


def query(**params):
    """Return (total_results, [entry dicts]) for one API page."""
    root = ET.fromstring(get(API + "?" + urllib.parse.urlencode(params)))
    total = int(root.findtext("os:totalResults", "0", NS))
    out = []
    for e in root.findall("a:entry", NS):
        abs_id = e.findtext("a:id", "", NS)
        if "/abs/" not in abs_id:
            continue  # error entries
        vid = abs_id.split("/abs/")[1]
        prim = e.find("arxiv:primary_category", NS)
        out.append({
            "id": vid.rsplit("v", 1)[0] if "v" in vid.split("/")[-1] else vid,
            "version": vid,
            "title": " ".join(e.findtext("a:title", "", NS).split()),
            "published": e.findtext("a:published", "", NS)[:10],
            "updated": e.findtext("a:updated", "", NS)[:10],
            "primary_category": prim.get("term") if prim is not None else "",
            "categories": " ".join(c.get("term") for c in e.findall("a:category", NS)),
            "n_authors": len(e.findall("a:author", NS)),
        })
    return total, out
