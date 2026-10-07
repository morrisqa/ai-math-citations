#!/usr/bin/env python3
"""Compute paper-level citation metrics for both corpora and compare them.

Unit of analysis: the paper. Every metric is computed per paper, then summarised
per corpus, so that papers with long reference lists do not dominate. Corpus
differences are reported as difference in means with a 95% bootstrap confidence
interval (resampling papers, 2,000 replicates, fixed seed).

The comparison uses only OpenAI preprints with a subject label (the strata the
human sample was matched to). AI-only statistics use all 722 preprints.

Usage: python3 scripts/analyze.py
Reads  data/openai_math_citations.csv, data/ai_intext_citations.csv,
       data/ai_preprint_subjects.csv, data/ai_cross_citations.csv, data/doi_check_ai.csv,
       and, when present, data/human_arxiv_citations.csv, data/human_intext_citations.csv,
       data/human_candidates.csv
Writes data/analysis/paper_metrics.csv, data/analysis/summary.json, data/analysis/summary.md,
       and copies of the first two in docs/data/ for the dashboard
"""
import collections
import csv
import json
import os
import random
import shutil
import statistics

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
OUT = os.path.join(ROOT, "analysis")
SPECIFIC = {"result", "location", "page", "numbered"}
SECTION_KINDS = ["abstract", "front", "intro", "prelim", "main", "discussion", "appendix"]
SEED = 20261007


def load(name):
    path = os.path.join(ROOT, name)
    if not os.path.exists(path):
        return None
    return list(csv.DictReader(open(path, encoding="utf-8")))


def share(num, den):
    return num / den if den else None


def year_of(s):
    try:
        y = int(str(s).strip()[:4])
    except ValueError:
        return None
    return y if 1600 <= y <= 2030 else None


def paper_metrics(corpus, pid, subject, citing_year, refs, cites):
    """Metrics for one paper. `refs`: its printed reference list; `cites`: its in-text rows."""
    m = {"corpus": corpus, "paper_id": pid, "subject": subject, "year": citing_year}
    m["n_references"] = len(refs)

    # Citation commands (one per \cite occurrence) and citation-key rows.
    commands = {}
    for c in cites:
        commands.setdefault(c["cite_index"], c)
    cmd = list(commands.values())
    m["n_cite_commands"] = len(cmd)
    m["citations_per_reference"] = share(len(cites), len(refs))
    if cmd:
        m["share_pinpoint_specific"] = share(sum(c["pinpoint_class"] in SPECIFIC for c in cmd), len(cmd))
        m["share_pinpoint_result"] = share(sum(c["pinpoint_class"] == "result" for c in cmd), len(cmd))
        m["share_pinpoint_any"] = share(sum(c["pinpoint_class"] in SPECIFIC or c["prose_pinpoint"] == "yes"
                                            for c in cmd), len(cmd))
        m["share_in_proof"] = share(sum(c["in_proof"] == "yes" for c in cmd), len(cmd))
        for k in SECTION_KINDS:
            m[f"share_section_{k}"] = share(sum(c["section_kind"] == k for c in cmd), len(cmd))
        m["share_intro_or_front"] = share(sum(c["section_kind"] in ("abstract", "front", "intro") for c in cmd), len(cmd))
        m["share_first_quarter"] = share(sum(float(c["position"]) < 0.25 for c in cmd), len(cmd))
        m["mean_group_size"] = statistics.mean(int(c["group_size"]) for c in cmd)
        m["share_group_3plus"] = share(sum(int(c["group_size"]) >= 3 for c in cmd), len(cmd))

    # How intensively each reference is used.
    counts = collections.Counter(c["key"] for c in cites)
    keys = [r["cite_key"] for r in refs if r["cite_key"]]
    used = [counts[k] for k in keys if counts[k] > 0]
    if used:
        m["share_refs_cited_once"] = share(sum(u == 1 for u in used), len(used))
        m["max_share_one_reference"] = max(used) / sum(used)

    # Age of cited works relative to the citing paper.
    ages = [citing_year - y for y in (year_of(r["year"]) for r in refs) if y is not None and y <= citing_year + 1]
    if ages:
        m["median_reference_age"] = statistics.median(ages)
        m["share_refs_recent_3y"] = share(sum(a <= 3 for a in ages), len(ages))
        m["share_refs_classic_30y"] = share(sum(a >= 30 for a in ages), len(ages))
        m["share_refs_with_year"] = share(len(ages), len(refs))
    m["share_refs_arxiv"] = share(sum(bool(r["arxiv_id"]) for r in refs), len(refs))
    m["share_refs_doi"] = share(sum(bool(r["doi"]) for r in refs), len(refs))
    return m, ages


def bootstrap_diff(a, b, reps=2000, seed=SEED):
    """95% CI for mean(a) - mean(b), resampling papers within each corpus."""
    rng = random.Random(seed)
    diffs = []
    for _ in range(reps):
        sa = [a[rng.randrange(len(a))] for _ in a]
        sb = [b[rng.randrange(len(b))] for _ in b]
        diffs.append(statistics.mean(sa) - statistics.mean(sb))
    diffs.sort()
    return diffs[int(0.025 * reps)], diffs[int(0.975 * reps) - 1]


METRICS = [
    ("n_references", "References per paper", "count"),
    ("n_cite_commands", "Citation commands per paper", "count"),
    ("citations_per_reference", "In-text citations per reference", "ratio"),
    ("share_pinpoint_specific", "Citations naming a specific result, section or page", "share"),
    ("share_pinpoint_result", "Citations naming a specific result (Theorem, Lemma, ...)", "share"),
    ("share_pinpoint_any", "Citations with any pinpoint (including in prose)", "share"),
    ("share_in_proof", "Citations inside proofs", "share"),
    ("share_intro_or_front", "Citations in abstract or introduction", "share"),
    ("share_first_quarter", "Citations in the first quarter of the text", "share"),
    ("mean_group_size", "Works per citation command", "ratio"),
    ("share_group_3plus", "Citation commands bundling 3+ works", "share"),
    ("share_refs_cited_once", "References cited only once", "share"),
    ("max_share_one_reference", "Share of citations going to the most-used reference", "share"),
    ("median_reference_age", "Median age of cited works (years)", "years"),
    ("share_refs_recent_3y", "Cited works at most 3 years old", "share"),
    ("share_refs_classic_30y", "Cited works at least 30 years old", "share"),
]


def build_ai(subjects):
    refs_all = load("openai_math_citations.csv")
    cites_all = load("ai_intext_citations.csv")
    refs = collections.defaultdict(list)
    for r in refs_all:
        # Printed reference list: BibTeX prints only cited entries; \bibitem lists print all.
        if r["source_format"] == "bibitem" or r["cited_in_text"] == "yes":
            refs[r["preprint_folder"]].append(r)
    cites = collections.defaultdict(list)
    for c in cites_all:
        cites[c["paper_id"]].append(c)
    papers = sorted({r["preprint_folder"] for r in refs_all})
    out, ages = [], {}
    for p in papers:
        m, a = paper_metrics("ai", p, subjects.get(p, ""), 2026, refs[p], cites[p])
        out.append(m)
        ages[p] = a
    return out, ages


def build_human():
    refs_all = load("human_arxiv_citations.csv")
    cites_all = load("human_intext_citations.csv")
    if not refs_all or not cites_all:
        return [], {}
    cand = {r["id"]: r for r in load("human_candidates.csv")}
    refs = collections.defaultdict(list)
    for r in refs_all:
        refs[r["preprint_folder"]].append(r)
    cites = collections.defaultdict(list)
    for c in cites_all:
        cites[c["paper_id"]].append(c)
    out, ages = [], {}
    for p in sorted(refs):
        m, a = paper_metrics("human", p, cand[p]["stratum"], int(cand[p]["published"][:4]), refs[p], cites[p])
        out.append(m)
        ages[p] = a
    return out, ages


def summarise(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return {"n": len(vals), "mean": statistics.mean(vals), "median": statistics.median(vals)}


def fmt(v, kind):
    if v is None:
        return "–"
    if kind == "share":
        return f"{100 * v:.1f}%"
    if kind == "count":
        return f"{v:.1f}"
    return f"{v:.2f}"


def main():
    os.makedirs(OUT, exist_ok=True)
    subjects = {r["preprint_folder"]: r["subject"] for r in load("ai_preprint_subjects.csv")}
    ai, ai_ages = build_ai(subjects)
    human, human_ages = build_human()
    ai_matched = [m for m in ai if m["subject"]]

    fields = ["corpus", "paper_id", "subject", "year"] + [k for k, _, _ in METRICS] + \
             [f"share_section_{k}" for k in SECTION_KINDS] + ["share_refs_with_year", "share_refs_arxiv", "share_refs_doi"]
    with open(os.path.join(OUT, "paper_metrics.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for m in ai + human:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()})

    summary = {"n_papers": {"ai_all": len(ai), "ai_matched": len(ai_matched), "human": len(human)},
               "metrics": []}
    for key, label, kind in METRICS:
        entry = {"key": key, "label": label, "kind": kind,
                 "ai_all": summarise(ai, key), "ai": summarise(ai_matched, key), "human": summarise(human, key)}
        a = [m[key] for m in ai_matched if m.get(key) is not None]
        h = [m[key] for m in human if m.get(key) is not None]
        if a and h:
            entry["diff_mean"] = statistics.mean(a) - statistics.mean(h)
            entry["diff_ci95"] = bootstrap_diff(a, h)
        summary["metrics"].append(entry)

    # Distributions for charts (pooled, so long papers weigh more; paper-level values are in the CSV).
    def pooled_ages(ages, ids):
        c = collections.Counter(min(a, 100) for p in ids for a in ages[p] if a >= 0)
        return [[k, c[k]] for k in sorted(c)]
    summary["reference_age_hist"] = {"ai": pooled_ages(ai_ages, [m["paper_id"] for m in ai_matched]),
                                     "human": pooled_ages(human_ages, [m["paper_id"] for m in human])}

    def pinpoint_mix(name, ids):
        rows = load(name) or []
        ids = set(ids)
        cmds = {}
        for c in rows:
            if c["paper_id"] in ids:
                cmds.setdefault((c["paper_id"], c["cite_index"]), c["pinpoint_class"])
        return dict(collections.Counter(cmds.values()))
    summary["pinpoint_mix"] = {"ai": pinpoint_mix("ai_intext_citations.csv", [m["paper_id"] for m in ai_matched]),
                               "human": pinpoint_mix("human_intext_citations.csv", [m["paper_id"] for m in human])}

    def position_hist(name, ids):
        rows = load(name) or []
        ids = set(ids)
        cmds = {}
        for c in rows:
            if c["paper_id"] in ids:
                cmds.setdefault((c["paper_id"], c["cite_index"]), float(c["position"]))
        hist = collections.Counter(min(int(p * 20), 19) for p in cmds.values())
        return [hist[i] for i in range(20)]
    summary["position_hist"] = {"ai": position_hist("ai_intext_citations.csv", [m["paper_id"] for m in ai_matched]),
                                "human": position_hist("human_intext_citations.csv", [m["paper_id"] for m in human])}

    # Per-subject means for strata present in both corpora.
    by_subject = []
    subj_ai = collections.defaultdict(list)
    subj_h = collections.defaultdict(list)
    for m in ai_matched:
        subj_ai[m["subject"]].append(m)
    for m in human:
        subj_h[m["subject"]].append(m)
    for s in sorted(subj_ai, key=lambda s: -len(subj_ai[s])):
        row = {"subject": s, "n_ai": len(subj_ai[s]), "n_human": len(subj_h.get(s, []))}
        for key in ("share_pinpoint_specific", "share_in_proof", "share_intro_or_front", "median_reference_age",
                    "n_references"):
            for name, group in (("ai", subj_ai[s]), ("human", subj_h.get(s, []))):
                vals = [m[key] for m in group if m.get(key) is not None]
                row[f"{key}_{name}"] = statistics.mean(vals) if vals else None
        by_subject.append(row)
    summary["by_subject"] = by_subject

    # AI-only findings.
    cross = [r for r in load("ai_cross_citations.csv") if r["match_method"] in ("repo_link", "title")]
    summary["ai_internal_citations"] = {
        "references": len(cross),
        "citing_papers": len({r["citing_folder"] for r in cross}),
        "cited_papers": len({r["cited_folder"] for r in cross}),
        "cites_later_release": sum(r["cited_date"] > r["citing_date"] for r in cross),
        "self_citations": sum(r["self_citation"] == "yes" for r in cross),
    }
    doi = load("doi_check_ai.csv")
    if doi:
        summary["ai_doi_check"] = dict(collections.Counter(r["status"] for r in doi))

    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1, default=lambda x: round(x, 4) if isinstance(x, float) else x)

    # Human-readable table.
    lines = ["# Summary of paper-level citation metrics", "",
             f"OpenAI preprints: {len(ai)} (matched comparison: {len(ai_matched)}); human arXiv papers: {len(human)}.",
             "Values are means across papers. Δ is AI minus human with a 95% bootstrap CI.", "",
             "| Metric | AI (all) | AI (matched) | Human | Δ (95% CI) |", "|---|---|---|---|---|"]
    for e in summary["metrics"]:
        k = e["kind"]
        get = lambda s: fmt(s["mean"], k) if s else "–"
        d = "–"
        if "diff_mean" in e:
            lo, hi = e["diff_ci95"]
            scale = 100 if k == "share" else 1
            unit = " pp" if k == "share" else ""
            d = f"{scale * e['diff_mean']:+.1f}{unit} ({scale * lo:+.1f}, {scale * hi:+.1f})"
        lines.append(f"| {e['label']} | {get(e['ai_all'])} | {get(e['ai'])} | {get(e['human'])} | {d} |")
    with open(os.path.join(OUT, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    # The dashboard (docs/, served by GitHub Pages) reads copies of the summary files.
    docs = os.path.join(ROOT, "..", "docs", "data")
    os.makedirs(docs, exist_ok=True)
    for name in ("summary.json", "paper_metrics.csv"):
        shutil.copyfile(os.path.join(OUT, name), os.path.join(docs, name))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
