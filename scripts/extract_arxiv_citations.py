#!/usr/bin/env python3
"""Extract the printed reference list of each human-written arXiv paper in the sample.

The goal is the list of references that actually appears in the paper. Sources
are tried in this order:
  1. a compiled .bbl file (BibTeX-style \\bibitem lists, biblatex \\entry records, or
     amsrefs \\bib records);
  2. an inline \\begin{thebibliography} or amsrefs \\begin{biblist} in the .tex files;
  3. .bib files, restricted to keys cited in the text (\\cite-family or \\nocite).
For 1 and 2, when a .bib entry with the same key is available its structured
fields are used instead of parsing the formatted text.

Usage: python3 scripts/extract_arxiv_citations.py [--ratio 1|2]
Reads  data/human_candidates.csv, data/human_sample_log.csv, data/raw/arxiv_sources/
Writes data/human_sample.csv (final selection, one row per candidate examined)
       data/human_arxiv_citations.csv
"""
import collections
import csv
import os
import re
import sys

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


AMSREFS_FIELDS = {"journal": "journal", "title": "title", "booktitle": "booktitle", "volume": "volume",
                  "number": "number", "pages": "pages", "publisher": "publisher", "doi": "doi", "url": "url",
                  "eprint": "eprint", "arxiv": "eprint", "note": "note", "series": "series", "address": "address",
                  "school": "school", "organization": "institution", "edition": "edition"}


def parse_amsrefs(text):
    """Turn amsrefs \\bib{key}{type}{field={...}, ...} records into (type, key, bibtex-style fields)."""
    out = []
    for m in re.finditer(r"\\bib\*?\s*\{([^}]*)\}\s*\{([^}]*)\}\s*\{", text):
        start = m.end() - 1
        body = text[start + 1:match_brace(text, start)]
        f, names = {}, collections.defaultdict(list)
        for fm in re.finditer(r"(\w+)\s*=\s*\{", body):
            j = match_brace(body, fm.end() - 1)
            name, val = fm.group(1).lower(), body[fm.end():j]
            if name in ("author", "editor", "translator"):
                names[name].append(val)
            elif name == "date":
                f.setdefault("year", val[:4])
            elif name in AMSREFS_FIELDS:
                f.setdefault(AMSREFS_FIELDS[name], val)
        for k, v in names.items():
            f[k] = " and ".join(v)
        if "pages" in f:
            f["pages"] = f["pages"].replace("\\ndash", "--")
        if re.match(r"^(arxiv:)?\d{4}\.\d{4,5}|^[a-z-]+/\d{7}", f.get("eprint", ""), re.I):
            f["archiveprefix"] = "arXiv"
            f["eprint"] = re.sub(r"^arxiv:", "", f["eprint"], flags=re.I)
        out.append((m.group(2).lower(), m.group(1).strip(), f))
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
        row["raw_reference"] = clean(re.sub(r"\\Bibitem\w+|\\bib\w+\s*", "", raw), keep_urls=True)
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
        row["raw_reference"] = clean(raw.replace("\\newblock", ""), keep_urls=True)
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
        if "\\bib{" in t or "\\begin{biblist}" in t:
            for etype, key, f in parse_amsrefs(t):
                add(p, key, lambda: {**bib_row(etype, key, f), "source_format": "amsrefs"})
        elif "\\entry{" in t:
            for etype, key, f in parse_biblatex_bbl(t):
                add(p, key, lambda: {**bib_row(etype, key, f), "source_format": "biblatex_bbl"})
        else:
            for key, _, raw in parse_bibitems(t):
                add(p, key, lambda: {**bbl_bibitem_row(key, raw), "source_format": "bbl"})
    if not rows:
        for p, t in sorted(texs.items()):
            if "\\begin{biblist}" in t:
                for etype, key, f in parse_amsrefs(t):
                    add(p, key, lambda: {**bib_row(etype, key, f), "source_format": "amsrefs"})
            elif "thebibliography" in t:
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
    """Select the final sample and write its references.

    The downloader walks each stratum in random-rank order. Because inclusion is
    re-checked here with the current parser, a candidate it rejected may now be
    usable; the final sample is therefore re-derived as the first RATIO x n_ai
    usable candidates by rank in each stratum (`--ratio 1` gives the balanced 1:1
    sample that is available once the downloader's first pass has finished).
    """
    ratio = int(sys.argv[sys.argv.index("--ratio") + 1]) if "--ratio" in sys.argv else 2
    cands = {r["id"]: r for r in csv.DictReader(open(os.path.join(ROOT, "human_candidates.csv"), encoding="utf-8"))}
    log = list(csv.DictReader(open(os.path.join(ROOT, "human_sample_log.csv"), encoding="utf-8")))
    by_stratum = collections.defaultdict(list)
    for r in log:
        by_stratum[r["stratum"]].append(r)

    out, sample = [], []
    for stratum, rows in sorted(by_stratum.items()):
        rows.sort(key=lambda r: int(r["rank"]))
        target = ratio * int(cands[rows[0]["id"]]["n_ai_in_stratum"])
        n_selected = 0
        for r in rows:
            src = os.path.join(SOURCES, r["id"].replace("/", "_"))
            refs = references_for_source(src) if r["status"] in ("included", "no_bibliography") else []
            status = r["status"] if r["status"] not in ("included", "no_bibliography") else (
                "usable" if refs else "no_bibliography")
            selected = status == "usable" and n_selected < target
            n_selected += selected
            sample.append({"stratum": stratum, "rank": r["rank"], "id": r["id"], "status": status,
                           "selected": "yes" if selected else "no", "n_references": len(refs)})
            if selected:
                m = cands[r["id"]]
                base = {"preprint_folder": r["id"], "preprint_title": m["title"], "preprint_date": m["published"],
                        "primary_category": m["primary_category"], "n_authors": m["n_authors"]}
                out.extend({**base, **ref} for ref in refs)
        if n_selected < target:
            print(f"  {stratum}: only {n_selected}/{target} usable papers so far")

    with open(os.path.join(ROOT, "human_sample.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(sample[0]))
        w.writeheader()
        w.writerows(sample)
    path = os.path.join(ROOT, "human_arxiv_citations.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HUMAN_COLUMNS)
        w.writeheader()
        w.writerows(out)
    n = sum(s["selected"] == "yes" for s in sample)
    print(f"ratio {ratio}: {n} papers selected, {len(out)} references -> {path}")

if __name__ == "__main__":
    main()
