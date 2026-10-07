"""Minimal, rate-limited client for the arXiv API (https://info.arxiv.org/help/api/)."""
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API = "https://export.arxiv.org/api/query"
USER_AGENT = "openai-math-citation-study/0.1 (academic research)"
DELAY = 5.0  # arXiv asks for at most one request every 3 s; we stay well under that
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
      "os": "http://a9.com/-/spec/opensearch/1.1/"}
_last = 0.0


def get(url, retries=12):
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
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"not found: {url}")
            # 429/503: honour Retry-After if given, else back off (capped at 10 minutes).
            retry_after = e.headers.get("Retry-After", "")
            pause = int(retry_after) if retry_after.isdigit() else min(60 * 2 ** attempt, 600)
            print(f"  HTTP {e.code}; waiting {pause}s (attempt {attempt + 1}) for {url[:90]}", flush=True)
            time.sleep(pause)
        except Exception as e:  # timeouts, truncated reads
            print(f"  retry {attempt + 1} for {url[:90]}: {e}", flush=True)
            time.sleep(30 * (attempt + 1))
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
