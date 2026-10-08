#!/usr/bin/env python3
"""One-off repair of data/human_sample_log.csv (2026-10-08).

During the 2:1 download, a git rebase with --autostash replaced the log file on
disk while the downloader held it open, so the downloader's later rows went to
an unlinked file. The downloads themselves are intact in data/raw/arxiv_sources/.

Because the downloader walks each stratum strictly in rank order, the lost rows
can be reconstructed:
  - a candidate with a source directory gets its status re-derived from the
    source (`included` or `no_bibliography`, as the downloader would decide);
  - a candidate ranked below the highest examined rank in its stratum but with
    no source directory was attempted and failed (PDF-only or download error);
    it is logged as `failed_unrecorded`. Such candidates are unusable either way,
    so final selection is unaffected.

Usage: python3 scripts/recover_sample_log.py
"""
import collections
import csv
import os

from extract_arxiv_citations import references_for_source

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
SOURCES = os.path.join(ROOT, "raw", "arxiv_sources")
LOG = os.path.join(ROOT, "human_sample_log.csv")


def main():
    log = list(csv.DictReader(open(LOG, encoding="utf-8")))
    logged = {r["id"] for r in log}
    cands = list(csv.DictReader(open(os.path.join(ROOT, "human_candidates.csv"), encoding="utf-8")))
    on_disk = set(os.listdir(SOURCES))

    by_stratum = collections.defaultdict(list)
    for c in cands:
        by_stratum[c["stratum"]].append(c)

    added = collections.Counter()
    new_rows = []
    for stratum, rows in by_stratum.items():
        rows.sort(key=lambda c: int(c["rank"]))
        examined = [c for c in rows if c["id"] in logged or c["id"].replace("/", "_") in on_disk]
        if not examined:
            continue
        last = max(int(c["rank"]) for c in examined)
        for c in rows:
            if int(c["rank"]) > last:
                break
            if c["id"] in logged:
                continue
            d = c["id"].replace("/", "_")
            if d in on_disk and os.listdir(os.path.join(SOURCES, d)):
                n = len(references_for_source(os.path.join(SOURCES, d)))
                status = "included" if n else "no_bibliography"
            else:
                n, status = 0, "failed_unrecorded"
            new_rows.append({"stratum": stratum, "rank": c["rank"], "id": c["id"], "status": status,
                             "n_references": n})
            added[status] += 1

    with open(LOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["stratum", "rank", "id", "status", "n_references"])
        w.writerows(new_rows)
    print(f"recovered {len(new_rows)} log rows: {dict(added)}")


if __name__ == "__main__":
    main()
