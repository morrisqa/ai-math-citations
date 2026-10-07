#!/usr/bin/env python3
"""Extract bibliographic references from every preprint in the openai/math repo.

Usage: python3 scripts/extract_citations.py data/raw/openai-math data/openai_math_citations.csv

Each preprint stores its references either in one or more .bib files or in an
inline \\begin{thebibliography} ... \\bibitem list. Both are handled; the
`source_format` column says which one a row came from.
"""
import csv
import os
import re
import sys

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
FOLDER_RE = re.compile(rf"^(.*)-({MONTHS})-(\d{{1,2}})-(\d{{4}})$")
CITE_RE = re.compile(r"\\(?:[a-zA-Z]*cite[a-zA-Z]*|nocite)\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")

ACCENTS = {
    '"': {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü", "e": "ë", "i": "ï"},
    r"'": {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú", "y": "ý", "c": "ć", "n": "ń", "s": "ś", "z": "ź",
           "E": "É", "A": "Á", "O": "Ó", "S": "Ś"},
    r"`": {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù", "E": "È"},
    r"^": {"a": "â", "e": "ê", "i": "î", "o": "ô", "u": "û"},
    r"~": {"a": "ã", "n": "ñ", "o": "õ", "N": "Ñ"},
    r"c": {"c": "ç", "C": "Ç", "s": "ş", "S": "Ş"},
    r"v": {"c": "č", "s": "š", "z": "ž", "r": "ř", "e": "ě", "C": "Č", "S": "Š", "Z": "Ž", "n": "ň"},
    r"H": {"o": "ő", "u": "ű", "O": "Ő"},
    r"u": {"a": "ă", "g": "ğ"},
    r"k": {"a": "ą", "e": "ę"},
    r"=": {"a": "ā", "o": "ō", "u": "ū"},
}
SYMBOLS = {r"\o": "ø", r"\O": "Ø", r"\l": "ł", r"\L": "Ł", r"\ss": "ß", r"\ae": "æ", r"\aa": "å",
           r"\AA": "Å", r"\i": "ı", r"\&": "&", r"\_": "_", r"\%": "%"}


def clean(s):
    """Light LaTeX -> plain text: accents, braces, ties, whitespace. Math is left as-is."""
    if not s:
        return ""
    for cmd, table in ACCENTS.items():
        esc = re.escape(cmd)
        s = re.sub(r"\\" + esc + r"\s*\{\s*\\?([A-Za-z])\s*\}", lambda m: table.get(m.group(1), m.group(1)), s)
        if not cmd.isalpha():
            s = re.sub(r"\\" + esc + r"\\?([A-Za-z])", lambda m: table.get(m.group(1), m.group(1)), s)
        else:
            s = re.sub(r"\\" + esc + r" ([A-Za-z])", lambda m: table.get(m.group(1), m.group(1)), s)
    for k, v in sorted(SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(re.escape(k) + r"(?![A-Za-z])\s*(\{\})?", v, s)
    s = re.sub(r"\\(?:emph|textit|textbf|textsc|textrm|mathrm|text|url|nolinkurl)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"(?<!\\)[{}]", "", s)
    s = s.replace("\\ ", " ").replace("\\,", " ").replace("~", " ").replace("--", "–")
    return re.sub(r"\s+", " ", s).strip()


def match_brace(s, i):
    """s[i] is '{' or '('; return index of the matching closer."""
    open_c = s[i]
    close_c = "}" if open_c == "{" else ")"
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(s) - 1


def parse_bib(text):
    entries, strings = [], {}
    for m in re.finditer(r"@\s*(\w+)\s*([{(])", text):
        etype = m.group(1).lower()
        start = m.end() - 1
        end = match_brace(text, start)
        body = text[start + 1:end]
        if etype in ("comment", "preamble"):
            continue
        if etype == "string":
            sm = re.match(r"\s*(\w+)\s*=\s*[{\"](.*)[}\"]\s*$", body, re.S)
            if sm:
                strings[sm.group(1).lower()] = sm.group(2)
            continue
        key, _, rest = body.partition(",")
        fields = {}
        i = 0
        while i < len(rest):
            fm = re.compile(r"\s*([\w:.-]+)\s*=\s*").match(rest, i)
            if not fm:
                i += 1
                continue
            name = fm.group(1).lower()
            i = fm.end()
            parts = []
            while i < len(rest):
                c = rest[i]
                if c == "{":
                    j = match_brace(rest, i)
                    parts.append(rest[i + 1:j])
                    i = j + 1
                elif c == '"':
                    j = i + 1
                    depth = 0
                    while j < len(rest) and not (rest[j] == '"' and depth == 0 and rest[j - 1] != "\\"):
                        depth += rest[j] == "{"
                        depth -= rest[j] == "}"
                        j += 1
                    parts.append(rest[i + 1:j])
                    i = j + 1
                else:
                    wm = re.compile(r"[\w.-]+").match(rest, i)
                    if wm:
                        w = wm.group(0)
                        parts.append(strings.get(w.lower(), w))
                        i = wm.end()
                    else:
                        i += 1
                        continue
                sm = re.compile(r"\s*#\s*").match(rest, i)
                if sm:
                    i = sm.end()
                    continue
                break
            fields[name] = "".join(parts)
            cm = re.compile(r"\s*,?").match(rest, i)
            i = cm.end()
        entries.append((etype, key.strip(), fields))
    return entries


def find_arxiv(*texts):
    for t in texts:
        if not t:
            continue
        m = re.search(r"arxiv(?:\.org/(?:abs|pdf)/|[:\s]\s*)((?:\d{4}\.\d{4,5})|(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}))", t, re.I)
        if m:
            return re.sub(r"v\d+$", "", m.group(1))
    return ""


def find_doi(*texts):
    for t in texts:
        if not t:
            continue
        m = re.search(r"(10\.\d{4,9}/[^\s},]+)", t)
        if m:
            return m.group(1).rstrip(".;)").replace("\\_", "_")
    return ""


def norm_id(doi, arxiv, title):
    if doi:
        return "doi:" + doi.lower()
    if arxiv:
        return "arxiv:" + arxiv.lower()
    t = re.sub(r"[^a-z0-9]+", " ", clean(title).lower()).strip()
    return "title:" + t if t else ""


def parse_bibitems(text):
    """Split a thebibliography block into (key, raw_text) pairs."""
    m = re.search(r"\\begin\{thebibliography\}(.*?)(\\end\{thebibliography\}|$)", text, re.S)
    if not m:
        return []
    block = m.group(1)
    items = []
    for part in re.split(r"\\bibitem(?![A-Za-z@])", block)[1:]:
        part = part.strip()
        label = ""
        if part.startswith("["):
            depth, close = 0, len(part)
            for idx, ch in enumerate(part):
                depth += ch == "{"
                depth -= ch == "}"
                if ch == "]" and depth == 0:
                    close = idx
                    break
            label, part = part[1:close], part[close + 1:].lstrip()
        key = ""
        if part.startswith("{"):
            j = match_brace(part, 0)
            key, part = part[1:j], part[j + 1:]
        part = re.sub(r"(?m)^\s*%.*$", "", part)
        if not key:
            continue
        items.append((key.strip(), label, re.sub(r"\s+", " ", part).strip()))
    return items


def fields_from_bibitem(raw):
    f = {}
    em = re.search(r"\\(?:emph|textit|textsl)\{", raw)
    if em:
        j = match_brace(raw, em.end() - 1)
        f["title"] = raw[em.end():j]
        f["author"] = raw[:em.start()].strip().rstrip(",:.").strip()
        after = raw[j + 1:]
    else:
        # Fall back: authors up to first ``...'' or the first sentence break.
        qm = re.search(r"``(.*?)''", raw)
        if qm:
            f["author"], f["title"], after = raw[:qm.start()].strip(" ,"), qm.group(1), raw[qm.end():]
        else:
            after = raw
    years = re.findall(r"\b(1[89]\d\d|20\d\d)\b", re.sub(r"\\href\{[^}]*\}", "", after))
    if years:
        f["year"] = years[0]
    vm = re.search(r"\\textbf\{([^}]*)\}", after)
    if vm:
        f["volume"] = vm.group(1)
    pm = re.search(r"(\d+)\s*(?:--|–|-)\s*(\d+)", re.sub(r"\\href\{[^}]*\}|\(\d{4}\)", "", after))
    if pm:
        f["pages"] = f"{pm.group(1)}--{pm.group(2)}"
    venue = re.split(r"\\textbf|\(\d{4}\)|\\href|,\s*(?:19|20)\d\d", after.lstrip(" ,."), maxsplit=1)[0]
    venue = venue.strip(" ,.;")
    if venue and len(venue) < 200:
        f["venue"] = venue
    urls = re.findall(r"\\(?:href|url)\{([^}]*)\}", raw)
    if urls:
        f["url"] = urls[0]
    return f


def expand_inputs(text, dirs, depth=0):
    """Inline \\input{...}/\\include{...} so bibliographies split across files are seen whole."""
    if depth > 5:
        return text

    def sub(m):
        name = m.group(1).strip()
        for d in dirs:
            for cand in (name, name + ".tex"):
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    return expand_inputs(read(p), dirs, depth + 1)
        return m.group(0)
    return re.sub(r"\\(?:input|include)\{([^}]*)\}", sub, text)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def cited_keys(tex_texts):
    """All keys referenced by \\cite-family or \\nocite commands, ignoring commented-out lines."""
    cited = set()
    for t in tex_texts:
        t = re.sub(r"(?<!\\)%.*", "", t)
        for grp in CITE_RE.findall(t):
            cited.update(k.strip() for k in grp.split(",") if k.strip())
    return cited


def bib_row(etype, key, f):
    """Reference columns for one parsed BibTeX entry."""
    doi = find_doi(f.get("doi", "")) or find_doi(f.get("url", ""))
    arxiv = ""
    if f.get("archiveprefix", "").lower() == "arxiv" or re.match(r"^\d{4}\.\d{4,5}|^[a-z-]+/\d{7}", f.get("eprint", "")):
        arxiv = re.sub(r"^arxiv:|v\d+$", "", f.get("eprint", ""), flags=re.I)
    arxiv = arxiv or find_arxiv(f.get("url", ""), f.get("note", ""), f.get("howpublished", ""), f.get("journal", ""))
    url = f.get("url", "") or next(iter(re.findall(r"\\(?:url|href)\{([^}]*)\}", f.get("howpublished", "") + f.get("note", ""))), "")
    return {"source_format": "bibtex", "cite_key": key, "entry_type": etype, "author": clean(f.get("author", "")),
            "title": clean(f.get("title", "")), "year": clean(f.get("year", "") or f.get("date", "")[:4]),
            "journal_or_venue": clean(f.get("journal", "") or f.get("journaltitle", "") or f.get("howpublished", "")
                                      or f.get("school", "") or f.get("institution", "")),
            "booktitle": clean(f.get("booktitle", "")), "publisher": clean(f.get("publisher", "")),
            "volume": clean(f.get("volume", "")), "number": clean(f.get("number", "")),
            "pages": clean(f.get("pages", "")).replace("–", "-"), "doi": doi, "arxiv_id": arxiv,
            "url": url, "note": clean(f.get("note", "")),
            "normalized_id": norm_id(doi, arxiv, f.get("title", "")), "raw_reference": ""}


def bibitem_row(key, raw):
    """Reference columns for one free-text \\bibitem, parsed best-effort."""
    f = fields_from_bibitem(raw)
    doi = find_doi(raw)
    arxiv = find_arxiv(raw)
    return {"source_format": "bibitem", "cite_key": key, "entry_type": "", "author": clean(f.get("author", "")),
            "title": clean(f.get("title", "")), "year": f.get("year", ""),
            "journal_or_venue": clean(f.get("venue", "")), "booktitle": "", "publisher": "",
            "volume": clean(f.get("volume", "")), "number": "", "pages": f.get("pages", ""),
            "doi": doi, "arxiv_id": arxiv, "url": f.get("url", ""), "note": "",
            "normalized_id": norm_id(doi, arxiv, f.get("title", "")), "raw_reference": clean(raw)}


COLUMNS = ["preprint_folder", "preprint_title", "preprint_date", "source_format", "source_file",
           "cite_key", "cited_in_text", "entry_type", "author", "title", "year", "journal_or_venue",
           "booktitle", "publisher", "volume", "number", "pages", "doi", "arxiv_id", "url", "note",
           "normalized_id", "raw_reference"]


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else "math"
    out = sys.argv[2] if len(sys.argv) > 2 else "openai_math_citations.csv"
    pre_dir = os.path.join(repo, "preprints")
    rows, problems = [], []
    for folder in sorted(os.listdir(pre_dir)):
        pdir = os.path.join(pre_dir, folder)
        if not os.path.isdir(pdir):
            continue
        title, date = folder, ""
        fm = FOLDER_RE.match(folder)
        if fm:
            title = fm.group(1).replace("-", " ")
            date = f"{fm.group(4)}-{MONTHS.split('|').index(fm.group(2)) + 1:02d}-{int(fm.group(3)):02d}"
        readme = os.path.join(pdir, "README.md")
        if os.path.exists(readme):
            tm = re.search(r"^#\s*\[(.*)\]\(", read(readme), re.M)
            if tm:
                title = tm.group(1)

        bibs, texs = [], []
        for r, _, fs in os.walk(os.path.join(pdir, "build")):
            for x in sorted(fs):
                p = os.path.join(r, x)
                if x.endswith(".bib"):
                    bibs.append(p)
                elif x.endswith(".tex"):
                    texs.append(p)
        tex_text = {p: read(p) for p in texs}
        cited = cited_keys(tex_text.values())

        base = {"preprint_folder": folder, "preprint_title": title, "preprint_date": date}
        seen = set()
        for b in sorted(bibs):
            for etype, key, f in parse_bib(read(b)):
                if key in seen:
                    continue
                seen.add(key)
                rows.append({**base, "source_file": os.path.relpath(b, pdir),
                             "cited_in_text": "yes" if key in cited else "no", **bib_row(etype, key, f)})

        if not bibs:
            build = os.path.join(pdir, "build")
            for p, t in tex_text.items():
                if "thebibliography" in t:
                    t = expand_inputs(t, [os.path.dirname(p), build])
                for key, label, raw in parse_bibitems(t):
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({**base, "source_file": os.path.relpath(p, pdir),
                                 "cited_in_text": "yes" if key in cited else "no", **bibitem_row(key, raw)})
        if not seen:
            problems.append(folder)

    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} references from {len({r['preprint_folder'] for r in rows})} preprints -> {out}")
    if problems:
        print(f"No references found in {len(problems)} preprints:", *problems, sep="\n  ")


if __name__ == "__main__":
    main()
