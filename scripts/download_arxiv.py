#!/usr/bin/env python3
"""Download v1 LaTeX sources for the human comparison sample.

Walks each stratum of data/human_candidates.csv in rank order, downloading the
v1 source of each paper, until RATIO usable papers per OpenAI preprint have been
collected. A paper is usable if its source is LaTeX (not PDF-only) and a
reference list with at least one entry can be extracted from it. Every
candidate examined is logged with its outcome, so exclusions are auditable.

Usage: python3 scripts/download_arxiv.py
Reads  data/human_candidates.csv
Writes data/raw/arxiv_sources/<id>/   (extracted source files)
       data/human_sample_log.csv       (one row per candidate examined)
"""
import collections
import csv
import gzip
import io
import os
import tarfile

from arxiv_api import get
from extract_arxiv_citations import references_for_source

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
SOURCES = os.path.join(ROOT, "raw", "arxiv_sources")
LOG = os.path.join(ROOT, "human_sample_log.csv")
RATIO = 2
EPRINT = "https://export.arxiv.org/e-print/{}v1"


def safe(arxiv_id):
    return arxiv_id.replace("/", "_")


def fetch(arxiv_id):
    """Download and unpack one v1 source. Returns a status string."""
    dest = os.path.join(SOURCES, safe(arxiv_id))
    if os.path.isdir(dest) and os.listdir(dest):
        return "ok"
    blob = get(EPRINT.format(arxiv_id))
    if blob[:4] == b"%PDF":
        return "pdf_only"
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    os.makedirs(dest, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
            members = [m for m in tf.getmembers()
                       if m.isfile() and not os.path.isabs(m.name) and ".." not in m.name.split("/")]
            tf.extractall(dest, members=members)
        return "ok"
    except tarfile.TarError:
        pass
    if blob[:4] == b"%PDF":
        return "pdf_only"
    if b"\\documentclass" in blob[:20000] or b"\\begin{document}" in blob or b"\\input" in blob[:20000]:
        with open(os.path.join(dest, "main.tex"), "wb") as fh:
            fh.write(blob)
        return "ok"
    return "not_latex"


def main():
    cands = list(csv.DictReader(open(os.path.join(ROOT, "human_candidates.csv"), encoding="utf-8")))
    done = {}
    if os.path.exists(LOG):
        done = {r["id"]: r for r in csv.DictReader(open(LOG, encoding="utf-8"))}
    by_stratum = collections.defaultdict(list)
    for c in cands:
        by_stratum[c["stratum"]].append(c)

    fields = ["stratum", "rank", "id", "status", "n_references"]
    new_log = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if new_log:
            w.writeheader()
        for stratum, rows in sorted(by_stratum.items(), key=lambda kv: -int(kv[1][0]["n_ai_in_stratum"])):
            target = RATIO * int(rows[0]["n_ai_in_stratum"])
            rows.sort(key=lambda r: int(r["rank"]))
            have = sum(1 for r in rows if done.get(r["id"], {}).get("status") == "included")
            for r in rows:
                if have >= target:
                    break
                if r["id"] in done:
                    continue
                try:
                    status = fetch(r["id"])
                except RuntimeError:
                    status = "download_failed"
                n = 0
                if status == "ok":
                    n = len(references_for_source(os.path.join(SOURCES, safe(r["id"]))))
                    status = "included" if n else "no_bibliography"
                    have += status == "included"
                w.writerow({"stratum": stratum, "rank": r["rank"], "id": r["id"], "status": status, "n_references": n})
                fh.flush()
                done[r["id"]] = {"status": status}
            print(f"{stratum}: {have}/{target}")


if __name__ == "__main__":
    main()
