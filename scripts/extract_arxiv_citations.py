#!/usr/bin/env python3
"""Extract the printed reference list of each human-written arXiv paper in the sample.

The goal is the list of references that actually appears in the paper. Sources
are tried in this order:
  1. a compiled .bbl file (BibTeX-style \\bibitem lists or biblatex \\entry records);
  2. an inline \\begin{thebibliography} in the .tex files;
  3. .bib files, restricted to keys cited in the text (\\cite-family or \\nocite).
For 1 and 2, when a .bib entry with the same key is available its structured
fields are used instead of parsing the formatted text.

Usage: python3 scripts/extract_arxiv_citations.py
Reads  data/human_candidates.csv, data/human_sample_log.csv, data/raw/arxiv_sources/
Writes data/human_arxiv_citations.csv
"""
import csv
import os
import re

from extract_citations import (COLUMNS, bib_row, bibitem_row, cited_keys, clean, expand_inputs,
                               match_brace, norm_id, parse_bib, parse_bibitems, read)

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
SOURCES = os.path.join(ROOT, "raw", "arxiv_sources")
HUMAN_COLUMNS = COLUMNS[:3] + ["primary_category", "n_authors"] + COLUMNS[3:]


def brace_arg(s, i):
    """Return (content, end) for the {...} group starting at or after s[i]."""
    j = s.index("{", i)
    k = match_brace(s, j)
    return s[j + 1:k], k + 1


def parse_biblatex_bbl(text):
    """Turn biblatex \\entry ... \\endentry records into (type, key, bibtex-style fields)."""
    out = []
    for m in re.finditer(r"\\entry\{([^}]*)\}\{([^}]*)\}(.*?)\\endentry", text, re.S):
        key, etype, body = m.group(1), m.group(2).lower(), m.group(3)
        f = {}
        for fm in re.finditer(r"\\field\{(\w+)\}", body):
            try:
                f[fm.group(1).lower()], _ = brace_arg(body, fm.end())
            except ValueError:
                pass
        for vm in re.finditer(r"\\verb\{(\w+)\}\s*\\verb (.*?)\s*\\endverb", body, re.S):
            f[vm.group(1).lower()] = vm.group(2).strip()
        for lm in re.finditer(r"\\list\{(\w+)\}\{\d+\}", body):
            try:
                val, _ = brace_arg(body, lm.end())
                f[lm.group(1).lower()] = " and ".join(x for x in re.findall(r"\{([^{}]*)\}", val)) or val
            except ValueError:
                pass
        for nm in re.finditer(r"\\name\{(\w+)\}\{\d+\}\{[^}]*\}", body):
            try:
                val, _ = brace_arg(body, nm.end())
            except ValueError:
                continue
            people = []
            for person in re.split(r"\}\}%?\s*\{\{", val):
                fam = re.search(r"family=\{((?:[^{}]|\{[^{}]*\})*)\}", person)
                giv = re.search(r"given=\{((?:[^{}]|\{[^{}]*\})*)\}", person)
                if fam:
                    people.append(fam.group(1) + (", " + giv.group(1) if giv else ""))
            f[nm.group(1).lower()] = " and ".join(people)
        if "year" not in f and "date" in f:
            f["year"] = f["date"][:4]
        if f.get("eprinttype", "").lower() == "arxiv":
            f["archiveprefix"] = "arXiv"
        out.append((etype, key, f))
    return out


def bbl_bibitem_row(key, raw):
    """Like bibitem_row, but uses BibTeX's \\newblock structure (authors / title / venue) when present."""
    row = bibitem_row(key, raw)
    if "\\bibinfo" in raw:  # REVTeX/APS styles tag every field: \bibinfo{title}{...}
        info = {}
        for m in re.finditer(r"\\bibinfo\s*\{(\w+)\}\s*", raw):
            try:
                val, _ = brace_arg(raw, m.end())
            except ValueError:
                continue
            info.setdefault(m.group(1), []).append(val)
        names = [re.sub(r"\\bib[fn]?namefont\s*", "", a) for a in info.get("author", [])]
        row["author"] = clean(" and ".join(names))
        row["title"] = clean((info.get("title") or info.get("booktitle") or [""])[0])
        row["journal_or_venue"] = clean((info.get("journal") or info.get("booktitle") or info.get("howpublished") or [""])[0])
        row["volume"] = clean((info.get("volume") or [""])[0])
        row["year"] = clean((info.get("year") or [row["year"]])[0])
        row["pages"] = clean((info.get("pages") or [row["pages"]])[0]).replace("–", "--")
        row["publisher"] = clean((info.get("publisher") or [""])[0])
        row["raw_reference"] = clean(re.sub(r"\\Bibitem\w+|\\bib\w+\s*", "", raw))
        row["normalized_id"] = norm_id(row["doi"], row["arxiv_id"], row["title"])
        return row
    if "\\newblock" in raw:
        parts = [p.strip(" .,") for p in raw.split("\\newblock")]
        if not row["title"] or len(parts) >= 3:
            row["author"] = clean(parts[0])
            row["title"] = clean(re.sub(r"\\(?:em|it)\b", "", parts[1])) if len(parts) > 1 else ""
            if len(parts) > 2:
                venue = re.split(r",\s*\d|\\textbf|\(\d{4}\)", parts[2])[0]
                row["journal_or_venue"] = clean(re.sub(r"\\(?:em|it)\b", "", venue))
        row["raw_reference"] = clean(raw.replace("\\newblock", ""))
        row["normalized_id"] = norm_id(row["doi"], row["arxiv_id"], row["title"])
    return row


def references_for_source(src):
    """Return reference rows (without citing-paper metadata) for one unpacked arXiv source."""
    files = [os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs]
    texs = {p: read(p) for p in files if p.lower().endswith(".tex")}
    bbls = [p for p in files if p.lower().endswith(".bbl")]
    bibs = [p for p in files if p.lower().endswith(".bib")]
    cited = cited_keys(texs.values())

    bib_entries = {}
    for b in sorted(bibs):
        try:
            for etype, key, f in parse_bib(read(b)):
                bib_entries.setdefault(key, (etype, f))
        except Exception:
            pass

    rows, seen = [], set()

    def add(path, key, row_fn):
        if key in seen:
            return
        seen.add(key)
        if key in bib_entries:
            etype, f = bib_entries[key]
            row = bib_row(etype, key, f)
        else:
            row = row_fn()
        rows.append({**row, "source_file": os.path.relpath(path, src),
                     "cited_in_text": "yes" if key in cited else "no"})

    for p in sorted(bbls):
        t = read(p)
        if "\\entry{" in t:
            for etype, key, f in parse_biblatex_bbl(t):
                add(p, key, lambda: {**bib_row(etype, key, f), "source_format": "biblatex_bbl"})
        else:
            for key, _, raw in parse_bibitems(t):
                add(p, key, lambda: {**bbl_bibitem_row(key, raw), "source_format": "bbl"})
    if not rows:
        for p, t in sorted(texs.items()):
            if "thebibliography" in t:
                t = expand_inputs(t, [os.path.dirname(p), src])
                for key, _, raw in parse_bibitems(t):
                    add(p, key, lambda: bbl_bibitem_row(key, raw))
    if not rows and bib_entries:
        for key in sorted(cited):
            if key in bib_entries:
                etype, f = bib_entries[key]
                add(next(b for b in bibs), key, lambda: bib_row(etype, key, f))
    return rows


def main():
    meta = {r["id"]: r for r in csv.DictReader(open(os.path.join(ROOT, "human_candidates.csv"), encoding="utf-8"))}
    log = [r for r in csv.DictReader(open(os.path.join(ROOT, "human_sample_log.csv"), encoding="utf-8"))
           if r["status"] == "included"]
    out = []
    for r in log:
        m = meta[r["id"]]
        base = {"preprint_folder": r["id"], "preprint_title": m["title"], "preprint_date": m["published"],
                "primary_category": m["primary_category"], "n_authors": m["n_authors"]}
        for ref in references_for_source(os.path.join(SOURCES, r["id"].replace("/", "_"))):
            out.append({**base, **ref})
    path = os.path.join(ROOT, "human_arxiv_citations.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HUMAN_COLUMNS)
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} references from {len(log)} papers -> {path}")


if __name__ == "__main__":
    main()
