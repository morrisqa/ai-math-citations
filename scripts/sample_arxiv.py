#!/usr/bin/env python3
"""Build a ranked list of candidate human-written arXiv papers, stratified by subject.

For every subject (primary arXiv category) assigned to an OpenAI preprint, list
all arXiv papers whose *primary* category is that subject and whose first
version (v1) was submitted between 2020-01-01 and 2022-12-31. Each subject's
list is shuffled with a fixed seed; download_arxiv.py then walks the list in
rank order until it has RATIO usable papers per OpenAI preprint in the subject.

Usage: python3 scripts/sample_arxiv.py
Reads  data/ai_preprint_subjects.csv
Writes data/raw/arxiv_listings/<category>.csv (full listings, cached)
       data/human_candidates.csv
"""
import collections
import csv
import os
import random

from arxiv_api import query

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
LISTINGS = os.path.join(ROOT, "raw", "arxiv_listings")
SEED = 20261007
START, END = "2020-01-01", "2022-12-31"
PAGE = 1000
FIELDS = ["id", "version", "title", "published", "updated", "primary_category", "categories", "n_authors"]


def listing(cat):
    """All papers with primary category `cat` and v1 in [START, END] (cached on disk)."""
    path = os.path.join(LISTINGS, cat + ".csv")
    if os.path.exists(path):
        return list(csv.DictReader(open(path, encoding="utf-8")))
    papers = {}
    # Query one quarter at a time to stay well under the API's result-window limit.
    for year in (2020, 2021, 2022):
        for q0, q1 in (("0101", "0331"), ("0401", "0630"), ("0701", "0930"), ("1001", "1231")):
            search = f"cat:{cat} AND submittedDate:[{year}{q0}0000 TO {year}{q1}2359]"
            start = 0
            while True:
                # The API occasionally returns an empty page mid-listing; retry before giving up.
                for _ in range(3):
                    total, entries = query(search_query=search, start=start, max_results=PAGE,
                                           sortBy="submittedDate", sortOrder="ascending")
                    if entries or start >= total:
                        break
                for e in entries:
                    # Old-style labels like "cond-mat" have no subject class; accept any subclass.
                    prim = e["primary_category"]
                    if (prim == cat or prim.startswith(cat + ".")) and START <= e["published"] <= END:
                        papers[e["id"]] = e
                start += PAGE
                if start >= total or not entries:
                    break
            print(f"  {cat} {year}-{q0[:2]}: {len(papers)} so far")
    os.makedirs(LISTINGS, exist_ok=True)
    rows = sorted(papers.values(), key=lambda e: e["id"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


def main():
    subjects = list(csv.DictReader(open(os.path.join(ROOT, "ai_preprint_subjects.csv"), encoding="utf-8")))
    counts = collections.Counter(s["subject"] for s in subjects if s["subject"])
    out = []
    for cat, n_ai in sorted(counts.items(), key=lambda kv: -kv[1]):
        rows = listing(cat)
        rng = random.Random(f"{SEED}-{cat}")
        rng.shuffle(rows)
        print(f"{cat}: {n_ai} OpenAI preprints, {len(rows)} arXiv candidates")
        for rank, r in enumerate(rows):
            out.append({"stratum": cat, "rank": rank, "n_ai_in_stratum": n_ai, **r})
    with open(os.path.join(ROOT, "human_candidates.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["stratum", "rank", "n_ai_in_stratum"] + FIELDS)
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
