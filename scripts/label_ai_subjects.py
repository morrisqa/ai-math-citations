#!/usr/bin/env python3
"""Assign each OpenAI preprint a primary arXiv category.

The preprints have no arXiv categories of their own, so each is labelled with
the most common primary category among the arXiv papers it cites (looked up
through the arXiv API). Ties are broken by the category's overall frequency
across the corpus.

Usage: python3 scripts/label_ai_subjects.py
Reads  data/openai_math_citations.csv
Writes data/arxiv_categories_of_cited_works.csv, data/ai_preprint_subjects.csv
"""
import collections
import csv
import os

from arxiv_api import query

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
CACHE = os.path.join(ROOT, "arxiv_categories_of_cited_works.csv")


def save_cache(cats):
    with open(CACHE, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["arxiv_id", "primary_category"])
        w.writerows(sorted(cats.items()))


def main():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "openai_math_citations.csv"), encoding="utf-8")))
    ids = sorted({r["arxiv_id"] for r in rows if r["arxiv_id"]})

    cats = {}
    if os.path.exists(CACHE):
        cats = {r["arxiv_id"]: r["primary_category"] for r in csv.DictReader(open(CACHE))}
    todo = [i for i in ids if i not in cats]
    print(f"{len(ids)} cited arXiv ids, {len(todo)} to look up")
    for k in range(0, len(todo), 100):
        batch = todo[k:k + 100]
        _, entries = query(id_list=",".join(batch), max_results=len(batch))
        found = {e["id"]: e["primary_category"] for e in entries}
        for i in batch:
            cats[i] = found.get(i, "")
        save_cache(cats)
        print(f"  {k + len(batch)}/{len(todo)}")

    overall = collections.Counter(c for c in cats.values() if c)
    by_paper = collections.defaultdict(collections.Counter)
    papers = {}
    for r in rows:
        papers[r["preprint_folder"]] = r["preprint_title"]
        c = cats.get(r["arxiv_id"], "")
        if c:
            by_paper[r["preprint_folder"]][c] += 1
    with open(os.path.join(ROOT, "ai_preprint_subjects.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["preprint_folder", "preprint_title", "subject", "n_arxiv_refs_with_category", "subject_share"])
        for folder, title in sorted(papers.items()):
            c = by_paper[folder]
            n = sum(c.values())
            if n:
                best = max(c, key=lambda k: (c[k], overall[k]))
                w.writerow([folder, title, best, n, f"{c[best] / n:.2f}"])
            else:
                w.writerow([folder, title, "", 0, ""])


if __name__ == "__main__":
    main()
