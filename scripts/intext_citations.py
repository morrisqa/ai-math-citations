#!/usr/bin/env python3
"""Extract every in-text citation, with its context, from the LaTeX of both corpora.

For each paper the main .tex file (the one with \\begin{document} and the largest
body after expanding \\input/\\include/\\subfile) is read from \\begin{document} to
the bibliography. Every citation command except \\nocite is recorded, one row per
cited key, with:

  postnote          the pinpoint text: \\cite[Theorem 2]{x} (natbib's second optional
                    argument when two are given) or amsrefs-style \\cite{x}*{Theorem 2}
  pinpoint_class    first match, in this order, anywhere in the postnote:
                    result   (Theorem, Lemma, Proposition, Corollary, Definition,
                              Remark, Example, Conjecture, Equation, Claim, ...)
                    location (Section, Chapter, Appendix, Part, Paragraph, §, Stacks Project tag)
                    page     (p., pp., page)
                    numbered (a bare number such as "4.2" or "II.2.1")
                    other    (any other non-empty postnote)
                    none
  prose_pinpoint    a result or location named next to the citation in running text,
                    e.g. "Theorem 2.3 of \\cite{x}" or "\\cite{x}, Lemma 4"
  section_kind      abstract / front (before the first section) / intro / prelim /
                    main / discussion / appendix, from the enclosing \\section title
  in_proof          inside a proof environment
  position          character offset of the citation divided by the body length
  group_size        number of keys in the same citation command

Citations inside macro definitions (\\def, \\newcommand, \\csname ...) are skipped:
some preprints build tables of cross-reference macros that would otherwise count
as citations.

Usage: python3 scripts/intext_citations.py ai|human
Writes data/ai_intext_citations.csv or data/human_intext_citations.csv
"""
import csv
import os
import re
import sys

from extract_citations import read

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")

RESULT = (r"theorems?|thms?\.?|lemmas?|lemmata|lems?\.?|propositions?|props?\.?|corollar(?:y|ies)|cors?\.?"
          r"|definitions?|defs?\.?|remarks?|rems?\.?|examples?|exs?\.?|conjectures?|conjs?\.?|claims?|facts?"
          r"|equations?|eqs?\.?|formulas?|identit(?:y|ies)|estimates?|inequalit(?:y|ies)|hypothes[ie]s|assumptions?"
          r"|conditions?|algorithms?|problems?|questions?|exercises?|properties|property|tables?|figures?|steps?"
          r"|cases?|observations?|principles?|axioms?|construction|statement|item|scholium|addendum|proof"
          r"|th[ée]or[èe]me|lemme|satz|\(\d")
LOCATION = r"sections?|secs?\.?|subsections?|chapters?|chaps?\.?|ch\.|appendix|appendices|parts?|paragraphs?|§|\\S(?![a-zA-Z])|lectures?|exposés?|expos[eé]|tags?\b|introduction"
PAGE = r"p\.|pp\.|pages?|pg\.|\d+\s*(?:--|–|-)\s*\d+$"
RESULT_RE = re.compile(rf"(?:^|\W)(?:{RESULT})", re.I)
LOCATION_RE = re.compile(rf"(?:^|\W)(?:{LOCATION})", re.I)
PAGE_RE = re.compile(rf"(?:^|\W)(?:{PAGE})", re.I)
NUMBERED_RE = re.compile(r"^[\s(]*[IVXLC]*[\dA-Z]*\.?\d[\w.()]*")  # bare numbers such as "4.2" or "II.2.1"
NAMED = rf"(?:{RESULT}|{LOCATION})"
PROSE_BEFORE = re.compile(rf"(?:{NAMED})[~\s]*\(?[\w.:\-]*\d[\w.:\-]*\)?[~\s]+(?:of|in|from|de|aus|von)[~\s]*$", re.I)
PROSE_AFTER = re.compile(rf"^[~\s]*[,;]?[~\s]*(?:{NAMED})[~\s]*\(?[\w.:\-]*\d", re.I)

CITE = re.compile(r"\\([a-zA-Z]*cite[a-zA-Z]*)\*?\s*"
                  r"(?:\[((?:[^\[\]]|\[[^\]]*\])*)\])?\s*(?:\[((?:[^\[\]]|\[[^\]]*\])*)\])?\s*"
                  r"\{([^{}]*)\}(?:\*\{((?:[^{}]|\{[^{}]*\})*)\})?")
TOKEN = re.compile(r"\\(?P<sec>section|chapter)\*?\s*(?:\[[^\]]*\])?\s*\{(?P<title>(?:[^{}]|\{[^{}]*\})*)\}"
                   r"|\\(?P<appendix>appendix)\b"
                   r"|\\(?P<be>begin|end)\s*\{(?P<env>proof|abstract)\*?\}"
                   r"|(?P<cite>\\[a-zA-Z]*cite[a-zA-Z]*\b)")
DEFINITION_LINE = re.compile(r"\\(?:def|gdef|edef|xdef|newcommand|renewcommand|providecommand|csname|DeclareRobustCommand)\b")


def section_kind(title, n_sections, in_appendix):
    t = title.lower()
    if in_appendix:
        return "appendix"
    if n_sections == 0:
        return "front"
    if re.search(r"intro|overview|motivation|main results?|statement of results|summary of results", t):
        return "intro"
    if re.search(r"prelim|background|notation|set-?up|convention|recollection|review|known results|definitions"
                 r"|terminology|framework|basic", t):
        return "prelim"
    if re.search(r"conclu|open (?:problem|question)|further|discussion|outlook|final remarks|future", t):
        return "discussion"
    return "main"


def classify_postnote(note):
    note = (note or "").strip()
    if not note:
        return "none"
    if RESULT_RE.search(note):
        return "result"
    if LOCATION_RE.search(note):
        return "location"
    if PAGE_RE.search(note) or re.fullmatch(r"\d+", note):
        return "page"
    if NUMBERED_RE.match(note):
        return "numbered"
    return "other"


def expand(text, dirs, depth=0):
    if depth > 6:
        return text

    def sub(m):
        name = m.group(1).strip()
        for d in dirs:
            for cand in (name, name + ".tex"):
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    return expand(read(p), dirs, depth + 1)
        return ""
    return re.sub(r"\\(?:input|include|subfile)\s*\{([^}]*)\}", sub, text)


def strip_comments(t):
    return re.sub(r"(?<!\\)%[^\n]*", "", t)


def document_body(src_dir):
    """Expanded body of the main document, from \\begin{document} to the bibliography."""
    best = ""
    for r, _, fs in os.walk(src_dir):
        for f in fs:
            if not f.lower().endswith(".tex"):
                continue
            p = os.path.join(r, f)
            t = strip_comments(read(p))
            if "\\begin{document}" not in t:
                continue
            t = strip_comments(expand(t, [r, src_dir]))
            body = t.split("\\begin{document}", 1)[1].split("\\end{document}", 1)[0]
            body = re.split(r"\\begin\{thebibliography\}|\\bibliography\s*\{|\\printbibliography", body)[0]
            if len(body) > len(best):
                best = body
    return "\n".join(line for line in best.split("\n") if not DEFINITION_LINE.search(line))


def citations(paper_id, body):
    rows = []
    n_sections, in_appendix, proof_depth, in_abstract = 0, False, 0, False
    title, kind = "", "front"
    length = max(len(body), 1)
    idx = 0
    for m in TOKEN.finditer(body):
        if m.group("sec"):
            n_sections += 1
            title = re.sub(r"\s+", " ", m.group("title")).strip()
            kind = section_kind(title, n_sections, in_appendix)
        elif m.group("appendix"):
            in_appendix = True
            kind = "appendix"
        elif m.group("env"):
            delta = 1 if m.group("be") == "begin" else -1
            if m.group("env") == "proof":
                proof_depth = max(proof_depth + delta, 0)
            else:
                in_abstract = delta == 1
        elif m.group("cite"):
            cm = CITE.match(body, m.start())
            if not cm or cm.group(1) == "nocite":
                continue
            opt1, opt2, keys, star = cm.group(2), cm.group(3), cm.group(4), cm.group(5)
            postnote = star if star is not None else (opt2 if opt2 is not None else opt1)
            pre = body[max(0, m.start() - 80):m.start()]
            post = body[cm.end():cm.end() + 60]
            prose = bool(PROSE_BEFORE.search(pre) or PROSE_AFTER.search(post))
            keylist = [k.strip() for k in keys.split(",") if k.strip()]
            idx += 1
            for k in keylist:
                rows.append({"paper_id": paper_id, "cite_index": idx, "command": cm.group(1), "key": k,
                             "group_size": len(keylist), "postnote": re.sub(r"\s+", " ", postnote or "").strip(),
                             "pinpoint_class": classify_postnote(postnote), "prose_pinpoint": "yes" if prose else "no",
                             "section_number": n_sections, "section_title": title[:120],
                             "section_kind": "abstract" if in_abstract else kind,
                             "in_proof": "yes" if proof_depth else "no", "position": round(m.start() / length, 4)})
    return rows


FIELDS = ["paper_id", "cite_index", "command", "key", "group_size", "postnote", "pinpoint_class",
          "prose_pinpoint", "section_number", "section_title", "section_kind", "in_proof", "position"]


def main():
    corpus = sys.argv[1]
    if corpus == "ai":
        base = os.path.join(ROOT, "raw", "openai-math", "preprints")
        papers = [(f, os.path.join(base, f, "build")) for f in sorted(os.listdir(base))
                  if os.path.isdir(os.path.join(base, f))]
    else:
        sample = csv.DictReader(open(os.path.join(ROOT, "human_sample.csv"), encoding="utf-8"))
        papers = [(r["id"], os.path.join(ROOT, "raw", "arxiv_sources", r["id"].replace("/", "_")))
                  for r in sample if r["selected"] == "yes"]
    out, empty = [], []
    for pid, d in papers:
        rows = citations(pid, document_body(d))
        if not rows:
            empty.append(pid)
        out.extend(rows)
    path = os.path.join(ROOT, f"{corpus}_intext_citations.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} citation-key rows from {len(papers) - len(empty)} of {len(papers)} papers -> {path}")
    if empty:
        print(f"no in-text citations found in {len(empty)} papers, e.g. {empty[:3]}")


if __name__ == "__main__":
    main()
