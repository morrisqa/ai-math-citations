#!/usr/bin/env python3
"""Find citations between OpenAI preprints (the "internal" citation network).

A reference is linked to an OpenAI preprint when (1) it contains a
github.com/openai/math/.../preprints/<folder> link or an OAI:<folder> identifier,
or (2) it names OpenAI as author and its normalized title equals a preprint's
title. (A matching title alone is not enough: at least one human paper has the
same title as an OpenAI preprint.) Remaining references that name OpenAI as
author are kept as "openai_other" (e.g. preprints not in the repo).

Usage: python3 scripts/ai_cross_citations.py
Reads  data/openai_math_citations.csv, data/raw/openai-math/preprints/
Writes data/ai_cross_citations.csv
"""
import csv
import os
import re

from check_dois import norm_text

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
LINK = re.compile(r"github\.com/openai/math/(?:blob|tree)/[^/\s]+/preprints/([^/\s}{]+)"
                  r"|\bOAI:([A-Za-z0-9-]+-20\d\d)\b")


def main():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "openai_math_citations.csv"), encoding="utf-8")))
    meta = {}
    for r in rows:
        meta[r["preprint_folder"]] = (r["preprint_title"], r["preprint_date"])
    folders = set(os.listdir(os.path.join(ROOT, "raw", "openai-math", "preprints"))) | set(meta)
    by_title = {norm_text(t): f for f, (t, _) in meta.items()}

    out = []
    for r in rows:
        blob = " ".join(r[k] for k in ("url", "journal_or_venue", "note", "raw_reference", "booktitle"))
        target, method = "", ""
        by_openai = re.search(r"\bopenai\b", r["author"] + " " + r["raw_reference"][:60], re.I)
        m = LINK.search(blob)
        linked = m and (m.group(1) or m.group(2))
        if linked and linked in folders:
            target, method = linked, "repo_link"
        elif linked:
            target, method = linked, "repo_link_unknown_folder"
        elif by_openai and norm_text(r["title"]) in by_title:  # same title alone is not enough
            target, method = by_title[norm_text(r["title"])], "title"
        elif by_openai:
            method = "openai_other"
        if not method:
            continue
        cited_title, cited_date = meta.get(target, ("", ""))
        out.append({"citing_folder": r["preprint_folder"], "citing_date": r["preprint_date"],
                    "cite_key": r["cite_key"], "cited_in_text": r["cited_in_text"],
                    "cited_folder": target, "cited_date": cited_date, "match_method": method,
                    "self_citation": "yes" if target == r["preprint_folder"] else "no",
                    "cited_title": cited_title or r["title"], "note": r["note"]})
    path = os.path.join(ROOT, "ai_cross_citations.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} references to OpenAI works -> {path}")


if __name__ == "__main__":
    main()
