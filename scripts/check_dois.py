#!/usr/bin/env python3
"""Check that cited DOIs exist and that their registered metadata matches the citation.

For each distinct DOI, the registration record is fetched from Crossref (in
batches of 50 via the `filter=doi:` query), then DataCite (arXiv and Zenodo
DOIs), then the doi.org handle service (which only confirms existence). Each reference is then compared with the record: title
similarity, year, first author's family name, and venue.

Usage: python3 scripts/check_dois.py data/openai_math_citations.csv data/doi_check_ai.csv
Cache: data/raw/doi_cache.jsonl (one JSON record per DOI; reruns are incremental)
"""
import csv
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
CACHE = os.path.join(ROOT, "raw", "doi_cache.jsonl")
USER_AGENT = "openai-math-citation-study/0.1 (academic research)"
CROSSREF_DELAY = 0.25  # Crossref public pool: 5 requests/s, one connection
BATCH = 50             # DOIs per Crossref filter query
SELECT = ("DOI,type,title,subtitle,author,editor,issued,published-print,published-online,published,"
          "container-title,volume,page")  # only the fields we compare; full records are large


def http_json(url):
    """GET a JSON document. Returns (status, data); data is None unless status is 200."""
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                return 200, json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return e.code, None
            time.sleep(5 * (attempt + 1) if e.code != 429 else 30 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    return 0, None


def normalize_doi(doi):
    doi = doi.strip().replace("\\%", "%").replace("\\_", "_")
    doi = urllib.parse.unquote(doi)
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I).rstrip(".,;")
    return re.sub(r"\.pdf$", "", doi, flags=re.I)  # DOIs lifted from PDF URLs


def crossref_record(doi, m):
    years = set()
    for k in ("issued", "published-print", "published-online", "published"):
        parts = (m.get(k) or {}).get("date-parts") or [[None]]
        if parts[0] and parts[0][0]:
            years.add(parts[0][0])
    authors = m.get("author") or m.get("editor") or []
    return {"doi": doi, "registry": "crossref", "type": m.get("type", ""),
            "title": " ".join(m.get("title") or []) + (": " + " ".join(m["subtitle"]) if m.get("subtitle") else ""),
            "years": sorted(years), "first_author": (authors[0].get("family") or authors[0].get("name", "")) if authors else "",
            "venue": " ".join(m.get("container-title") or []), "volume": m.get("volume", ""),
            "page": m.get("page", "")}


def crossref_batch(dois):
    """Look up to BATCH DOIs in one Crossref request. Returns {lowercased doi: record}."""
    flt = ",".join("doi:" + d for d in dois)
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"filter": flt, "rows": len(dois),
                                                                      "select": SELECT})
    status, data = http_json(url)
    time.sleep(CROSSREF_DELAY)
    if status != 200:
        return None
    by_lower = {d.lower(): d for d in dois}
    return {m["DOI"].lower(): crossref_record(by_lower.get(m["DOI"].lower(), m["DOI"]), m)
            for m in data["message"]["items"]}


def lookup(doi):
    """Look up one DOI: Crossref, then DataCite, then the doi.org handle service."""
    q = urllib.parse.quote(doi, safe="/")
    status, data = http_json(f"https://api.crossref.org/works/{q}")
    time.sleep(CROSSREF_DELAY)
    if status == 200:
        return crossref_record(doi, data["message"])
    if status == 0:
        return {"doi": doi, "registry": "error"}
    return lookup_elsewhere(doi)


def lookup_elsewhere(doi):
    """DataCite (arXiv, Zenodo DOIs), then doi.org to confirm existence at any other agency."""
    q = urllib.parse.quote(doi, safe="/")
    status, data = http_json(f"https://api.datacite.org/dois/{q}")
    if status == 200:
        a = data["data"]["attributes"]
        creators = a.get("creators") or []
        return {"doi": doi, "registry": "datacite", "type": (a.get("types") or {}).get("resourceTypeGeneral", ""),
                "title": " ".join(t.get("title", "") for t in (a.get("titles") or [])[:1]),
                "years": [a["publicationYear"]] if a.get("publicationYear") else [],
                "first_author": (creators[0].get("familyName") or creators[0].get("name", "")) if creators else "",
                "venue": a.get("publisher", "") if isinstance(a.get("publisher"), str) else "", "volume": "", "page": ""}
    status, data = http_json(f"https://doi.org/api/handles/{q}")
    if status == 200 and data.get("responseCode") == 1:
        return {"doi": doi, "registry": "other"}  # exists (e.g. mEDRA, JaLC) but no metadata fetched
    return {"doi": doi, "registry": "not_found" if status in (404, 200) else "error"}


def norm_text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")                    # MathML / HTML tags in Crossref titles
    s = re.sub(r"\\[a-zA-Z]+", " ", s)                      # LaTeX commands
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def title_similarity(a, b):
    a, b = norm_text(a), norm_text(b)
    if not a or not b:
        return None
    if a == b or (min(len(a), len(b)) >= 20 and (a.startswith(b) or b.startswith(a))):
        return 1.0  # identical, or one adds a subtitle
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


def first_family(author):
    first = re.split(r"\s+and\s+|;", author or "")[0].strip()
    if "," in first:
        fam = first.split(",")[0]
    else:
        toks = first.split()
        fam = toks[-1] if toks else ""
    return norm_text(fam)


def raw_coverage(raw, title):
    """Share of the registered title's words that appear in the full reference text."""
    want = norm_text(title).split()
    have = set(norm_text(raw).split())
    if len(want) < 2 or not have:
        return None
    return round(sum(w in have for w in want) / len(want), 3)


def classify(ref, rec):
    """Return (status, title_similarity, method). For free-text references the parsed title
    can be wrong (e.g. the journal name), so the registered title is also sought in the raw text."""
    if rec["registry"] in ("not_found", "error"):
        return rec["registry"], None, ""
    if rec["registry"] == "other":
        return "exists_no_metadata", None, ""
    sim = title_similarity(ref["title"], rec["title"])
    if (sim is None or sim < 0.9) and ref.get("raw_reference"):
        cov = raw_coverage(ref["raw_reference"], rec["title"])
        if cov is not None and cov >= 0.9:
            return "title_match", cov, "raw_text"
    if sim is None:
        return "exists_no_title_to_compare", sim, ""
    if sim >= 0.9:
        return "title_match", sim, "parsed_title"
    if sim >= 0.6:
        return "title_partial", sim, "parsed_title"
    return "title_mismatch", sim, "parsed_title"


def main():
    src, out = sys.argv[1], sys.argv[2]
    refs = [r for r in csv.DictReader(open(src, encoding="utf-8")) if r["doi"]]
    cache = {}
    if os.path.exists(CACHE):
        for line in open(CACHE, encoding="utf-8"):
            rec = json.loads(line)
            if rec["registry"] != "error":
                cache[rec["doi"].lower()] = rec
    dois = sorted({normalize_doi(r["doi"]) for r in refs}, key=str.lower)
    todo = [d for d in dois if d.lower() not in cache]
    print(f"{len(refs)} references, {len(dois)} distinct DOIs, {len(todo)} to look up", flush=True)
    with open(CACHE, "a", encoding="utf-8") as fh:
        def store(rec):
            cache[rec["doi"].lower()] = rec
            fh.write(json.dumps(rec) + "\n")
            fh.flush()

        # Crossref in batches; commas break the filter syntax, so those DOIs go one at a time.
        batchable = [d for d in todo if "," not in d]
        singles = [d for d in todo if "," in d]
        for k in range(0, len(batchable), BATCH):
            chunk = batchable[k:k + BATCH]
            found = crossref_batch(chunk)
            if found is None:
                singles.extend(chunk)
                continue
            for d in chunk:
                if d.lower() in found:
                    store(found[d.lower()])
                else:
                    singles.append(("elsewhere", d))
            if (k // BATCH) % 20 == 0:
                print(f"  crossref batches: {k + len(chunk)}/{len(batchable)}", flush=True)
        print(f"  {len(singles)} DOIs need individual lookups", flush=True)
        for item in singles:
            store(lookup_elsewhere(item[1]) if isinstance(item, tuple) else lookup(item))

    fields = ["preprint_folder", "cite_key", "cited_in_text", "doi", "status", "title_similarity", "title_check_method",
              "year_cited", "years_registered", "year_match", "first_author_cited", "first_author_registered",
              "first_author_match", "title_cited", "title_registered", "venue_cited", "venue_registered",
              "registry", "registered_type"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in refs:
            rec = cache[normalize_doi(r["doi"]).lower()]
            status, sim, method = classify(r, rec)
            years = rec.get("years") or []
            fa_c, fa_r = first_family(r["author"]), norm_text(rec.get("first_author", ""))
            w.writerow({
                "preprint_folder": r["preprint_folder"], "cite_key": r["cite_key"],
                "cited_in_text": r["cited_in_text"], "doi": r["doi"], "status": status,
                "title_similarity": "" if sim is None else sim, "title_check_method": method,
                "year_cited": r["year"], "years_registered": " ".join(map(str, years)),
                "year_match": "" if not (years and r["year"].isdigit()) else ("yes" if int(r["year"]) in years else "no"),
                "first_author_cited": fa_c, "first_author_registered": fa_r,
                "first_author_match": "" if not (fa_c and fa_r) else ("yes" if fa_c == fa_r or fa_c in fa_r.split() or fa_r in fa_c.split() else "no"),
                "title_cited": r["title"], "title_registered": rec.get("title", ""),
                "venue_cited": r["journal_or_venue"] or r["booktitle"], "venue_registered": rec.get("venue", ""),
                "registry": rec["registry"], "registered_type": rec.get("type", ""),
            })
    print(f"wrote {out}")

    # One row per distinct flagged DOI, for manual adjudication.
    review = out.replace(".csv", "_flags_for_review.csv")
    flagged = {}
    for r in csv.DictReader(open(out, encoding="utf-8")):
        if r["status"] in ("title_mismatch", "title_partial", "not_found"):
            k = normalize_doi(r["doi"]).lower()
            if k not in flagged:
                flagged[k] = {**{f: r[f] for f in ("doi", "status", "title_similarity", "title_cited",
                                                   "title_registered", "first_author_cited",
                                                   "first_author_registered", "year_cited", "years_registered")},
                              "n_citing_refs": 0, "example_preprint": r["preprint_folder"], "verdict": ""}
            flagged[k]["n_citing_refs"] += 1
    with open(review, "w", newline="", encoding="utf-8") as fh:
        rows = sorted(flagged.values(), key=lambda r: (r["status"], r["doi"].lower()))
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {review} ({len(rows)} distinct DOIs to adjudicate)")


if __name__ == "__main__":
    main()
