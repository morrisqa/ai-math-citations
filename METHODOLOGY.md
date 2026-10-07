# Methodology

**Research question.** Does AI-generated mathematical research cite different sources, or use its sources differently, than human-written research?

This document records how each dataset was built, the decisions behind it, and their known limitations. It is updated as the project progresses; see the [decision log](#decision-log) at the end.

---

## 1. AI corpus: OpenAI math preprints

**Source.** [github.com/openai/math](https://github.com/openai/math) (Apache 2.0), cloned on 2026-10-07 at commit `adc7f1241b42e322a6451854ab7e4b4c146bf78a` (committed 2026-10-06). Each of the 722 folders in `preprints/` holds one paper, with LaTeX sources under `build/`.

**Where references are stored.** The preprints use two formats:

| Format | Preprints | How it is parsed |
|---|---|---|
| One or more `.bib` files | 495 | Full BibTeX parse (nested braces, quoted values, `@string` macros, `#` concatenation). |
| Inline `\begin{thebibliography}` with `\bibitem` entries | 227 | Each `\bibitem` is split out; author, title, year, venue, volume, pages, DOI, arXiv ID and URL are extracted heuristically, and the full text is kept in `raw_reference`. `\input`/`\include` are expanded first because 9 preprints keep the list in a separate file. |

**Rules.**
- Entries are de-duplicated by citation key within a preprint, since a few preprints have more than one `.bib` file.
- `cited_in_text` is `yes` when the key appears in any `\cite`-family command (`\cite`, `\citep`, `\citet`, `\cite[Theorem 2]{…}`, `\nocite`, …) in any `.tex` file of that preprint, ignoring commented-out lines.
- Text fields are lightly converted from LaTeX to plain text: accents (`\"a` → ä), special letters (`\o` → ø), braces and ties are removed. Mathematics is left as LaTeX.
- `normalized_id` is a cross-paper identifier for the cited work: `doi:<lowercased DOI>`, else `arxiv:<id without version>`, else `title:<lowercased alphanumeric title>`.

**Validation.** Per-preprint row counts were compared with an independent count of `@entry` records (or `\bibitem` keys). All 722 preprints matched.

**Output.** `data/openai_math_citations.csv`: 17,957 rows, one per reference per preprint.

**Note on comparability.** BibTeX prints only entries that are cited, so the reference list a reader sees in a `.bib`-based preprint corresponds to rows with `cited_in_text = yes`. About 650 `.bib` entries in the AI corpus are never cited. They are kept because "uncited entries in the bibliography database" may itself be a variable of interest, but they should be excluded when comparing printed reference lists.

---

## 2. Subject labels for the AI preprints

The OpenAI preprints have no arXiv subject categories. To build a subject-matched human sample, each preprint is labelled with the most common **primary arXiv category among the arXiv papers it cites**:

1. All 4,189 distinct arXiv IDs cited anywhere in the AI corpus were looked up through the arXiv API to get their primary category (`data/arxiv_categories_of_cited_works.csv`).
2. For each preprint, the category with the most cited papers wins. Ties go to the category that is more frequent across the whole corpus.

**Result.** 687 of 722 preprints received a label (`data/ai_preprint_subjects.csv`). The median preprint has 80% of its categorised arXiv citations in the winning category. The 35 unlabelled preprints cite no arXiv papers. They remain in the AI corpus but do not contribute to the sampling targets.

The largest strata are math.AG (101), math.PR (95), math.CO (50), math.DG (43), math.NT (41), math.AP (30), cs.DS (29) and math-ph (28). There are 42 strata in total.

**Limitation.** This is a proxy. A paper's subject is inferred from what it cites, not from its content. 106 labels rest on only one or two categorised citations.

---

## 3. Human comparison corpus: arXiv papers, 2020–2022

**Why before 2023.** ChatGPT was released on 2022-11-30. Restricting to papers whose **first version** was submitted before 2023 makes substantial LLM involvement in the writing very unlikely.

**Sampling frame.** For each subject stratum, all arXiv papers whose
- *primary* category equals the stratum (cross-listings excluded; an archive-level label such as `cond-mat` matches any of its subclasses), and
- v1 submission date falls in 2020-01-01 – 2022-12-31,

were listed through the arXiv API, one calendar quarter at a time (`data/raw/arxiv_listings/`).

**Sample.** Each stratum's list is shuffled with a fixed seed (`20261007-<category>`), giving a ranked candidate list (`data/human_candidates.csv`). Candidates are taken in rank order until the stratum has **2 usable human papers per AI preprint** (a target of 1,374 papers).

**Version.** The **v1** source is downloaded (`https://export.arxiv.org/e-print/<id>v1`), not the latest version, because later revisions may postdate 2022.

**Inclusion criteria.** A candidate is included if its v1 source is LaTeX (not PDF-only) and a reference list with at least one entry can be extracted from it. Every candidate examined is logged with its outcome in `data/human_sample_log.csv`: `included`, `pdf_only`, `not_latex`, `no_bibliography` or `download_failed`.

**Access etiquette.** All arXiv requests go through `scripts/arxiv_api.py`, which waits at least 3 seconds between requests (arXiv's published limit) and backs off for 1–6 minutes on errors, including HTTP 429.

### Reference extraction for the human corpus

The aim is the **printed reference list**. Sources are tried in this order:

1. **Compiled `.bbl` file.** arXiv requires one for BibTeX users, so it is usually present. Three styles are handled:
   - standard BibTeX output (`\bibitem … \newblock …`);
   - REVTeX/APS output (`\bibinfo{title}{…}`);
   - biblatex output (`\entry … \field{title}{…} … \endentry`).
2. **Inline `\begin{thebibliography}`** in the `.tex` files, with `\input` expanded.
3. **`.bib` files**, restricted to keys cited in the text.

For 1 and 2, if a `.bib` file in the source contains the same key, its structured fields are used instead of parsing formatted text. `source_format` records which path produced each row.

**Output.** `data/human_arxiv_citations.csv`, with the same columns as the AI corpus plus `primary_category` and `n_authors`.

---

## 4. Known threats to validity

- **Time gap.** Human papers date from 2020–2022 and AI papers from 2026, so the human papers cannot cite anything from the last four years. Citation-age measures should therefore be computed relative to each citing paper's date.
- **Asymmetric parse quality.** Most AI references come from clean BibTeX, while human references come from many different `.bbl` styles. Differences in parsed fields such as venue or title can reflect parsing rather than behaviour. **Planned mitigation:** resolve references in both corpora against the same external database (OpenAlex/Crossref), by DOI, then arXiv ID, then title, and take year, venue, type and citation count from there.
- **Authorship structure.** Human papers have 1–n authors who can cite their own prior work. The AI papers are attributed to "OpenAI" and have no self-citation history, except possibly to each other.
- **Subject labelling is a proxy** (see §2).
- **Leftover files.** arXiv sources sometimes contain stale `.bbl`/`.tex` files from earlier drafts. De-duplication by key limits the damage, but a few reference lists may be slightly inflated.
- **Selection by availability.** PDF-only submissions and papers without an extractable bibliography are excluded, which may skew the sample toward particular authoring workflows.

---

## 5. Reproducing the data

```bash
git clone https://github.com/openai/math data/raw/openai-math   # then: git -C data/raw/openai-math checkout adc7f12
python3 scripts/extract_citations.py data/raw/openai-math data/openai_math_citations.csv
cd scripts
python3 label_ai_subjects.py      # arXiv API lookups (~1 min per 100 IDs)
python3 sample_arxiv.py           # arXiv listings (slow; cached in data/raw/arxiv_listings)
python3 download_arxiv.py         # v1 sources (~3 s per paper; resumable)
python3 extract_arxiv_citations.py
```

The scripts use only the Python 3 standard library. Raw downloads under `data/raw/` are not committed: the OpenAI repo is ~3 GB, and arXiv source files remain under their authors' licences. Only derived bibliographic metadata is published.

---

## Decision log

| Date | Decision |
|---|---|
| 2026-10-07 | Extract all references from the OpenAI repo; include `\bibitem`-only preprints instead of dropping them. |
| 2026-10-07 | Human baseline: arXiv papers with v1 in 2020–2022, stratified by primary category matched to the AI corpus, 2 human papers per AI paper, v1 sources only. |
| 2026-10-07 | Subject labels for AI preprints inferred from the primary categories of cited arXiv papers. |
| 2026-10-07 | Define the unit of comparison as the *printed reference list*; keep uncited `.bib` entries flagged rather than dropped. |
| 2026-10-07 | Plan to normalise reference metadata for both corpora through a common external database before comparing fields. |
