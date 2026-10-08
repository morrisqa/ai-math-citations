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

were listed through the arXiv API (`data/raw/arxiv_listings/`). Categories with at most 10,000 results (including cross-lists) were fetched in one query over the whole window. The 10 largest strata (math.AG through math.OA), plus quant-ph, gr-qc and cs.LG, were listed in full one calendar quarter at a time. Listing cs.LG alone took 75 minutes, so for the remaining large categories (> 10,000 results) the frame was instead built by **day sampling**: whole days in the window are drawn at random without replacement (seed `20261007-<category>-days`), and every primary-category paper submitted on a drawn day is added until at least 300 candidates are collected. Papers submitted on busy days are slightly less likely to be drawn than under simple random sampling. These strata contribute only 1–3 AI preprints each, so the effect on the pooled sample is negligible.

**Sample.** Each stratum's list is shuffled with a fixed seed (`20261007-<category>`), giving a ranked candidate list (`data/human_candidates.csv`). Candidates are taken in rank order until the stratum has **2 usable human papers per AI preprint** (a target of 1,374 papers). Collection runs in two passes, first to 1 paper per AI preprint in every stratum and then to 2, so the sample stays balanced if collection stops early.

**Version.** The **v1** source is downloaded (`https://export.arxiv.org/e-print/<id>v1`), not the latest version, because later revisions may postdate 2022.

**Inclusion criteria.** A candidate is usable if its v1 source is LaTeX (not PDF-only) and a reference list with at least one entry can be extracted from it. Every candidate the downloader examines is logged in `data/human_sample_log.csv` (`included`, `pdf_only`, `not_latex`, `no_bibliography` or `download_failed`).

**Final selection.** Usability is re-checked with the current parser when references are extracted (`scripts/extract_arxiv_citations.py`). In each stratum the final sample is the **first `ratio × n_AI` usable candidates in random-rank order** (`data/human_sample.csv`). This keeps the sample tied to the random ranking even when a parser improvement turns a previously rejected candidate into a usable one. For example, adding amsrefs support reduced `no_bibliography` exclusions from 50 to 22 among the first 896 candidates examined. The remaining exclusions mostly have no bibliography that can be linked to `\cite` commands, for example `\bibitem{}` entries cited via `\ref`, or plain `\item` lists. `--ratio 1` gives the balanced 1:1 sample available after the downloader's first pass.

**Final sample (2026-10-08).** 1,374 human papers, 2 per subject-labelled OpenAI preprint in all 42 strata, with 41,545 references. 1,452 candidates were examined: 1,378 usable, 64 without a linkable bibliography, 6 PDF-only, 1 not LaTeX, and 3 failed downloads (see below).

**Log recovery.** During the second download pass, a `git rebase --autostash` replaced `human_sample_log.csv` on disk while the downloader held it open. The downloader's subsequent 384 rows went to an unlinked file; the downloaded sources were unaffected. `scripts/recover_sample_log.py` rebuilt the missing rows from the sources on disk. Because the downloader works through each stratum strictly in rank order, a candidate ranked below the last one examined but with no source on disk must have failed; these 3 are logged as `failed_unrecorded`. They are unusable either way, so the selection is the same as if the log had been intact.

**cond-mat.** arXiv's `cat:` search does not match subclasses of an archive-level label, so the first listing of the 3-preprint `cond-mat` stratum came back empty. It was rebuilt by querying the nine `cond-mat.*` subclasses, with the same day-sampling rule and seed scheme. Regenerating the candidate file left every other stratum's ranking unchanged (all 170,556 rows identical).

**Access etiquette.** All arXiv requests go through `scripts/arxiv_api.py`, which waits at least 3 seconds between requests (arXiv's published limit) and backs off for 1–6 minutes on errors, including HTTP 429.

### Reference extraction for the human corpus

The aim is the **printed reference list**. Sources are tried in this order:

1. **Compiled `.bbl` file.** arXiv requires one for BibTeX users, so it is usually present. Four styles are handled:
   - standard BibTeX output (`\bibitem … \newblock …`);
   - REVTeX/APS output (`\bibinfo{title}{…}`);
   - biblatex output (`\entry … \field{title}{…} … \endentry`);
   - amsrefs (`\bib{key}{article}{author={…}, …}`), common in mathematics.
2. **Inline `\begin{thebibliography}`** or amsrefs `\begin{biblist}` in the `.tex` files, with `\input` expanded.
3. **`.bib` files**, restricted to keys cited in the text.

For 1 and 2, if a `.bib` file in the source contains the same key, its structured fields are used instead of parsing formatted text. `source_format` records which path produced each row.

**Output.** `data/human_arxiv_citations.csv`, with the same columns as the AI corpus plus `primary_category` and `n_authors`.

---

## 4. Analyses on the AI corpus alone

### 4.1 DOI existence and metadata accuracy (`scripts/check_dois.py`)

Each distinct DOI cited (8,139 in the AI corpus) is looked up in **Crossref**. If Crossref has no record, it is looked up in **DataCite**, which registers arXiv's `10.48550` DOIs and Zenodo DOIs. If DataCite has none either, the **doi.org handle service** is checked to confirm the DOI exists at another agency (mEDRA, JaLC, …).

Each reference is then compared with the registered record:
- **Title similarity:** `difflib` ratio on lowercased, accent-stripped alphanumeric text, with LaTeX commands and MathML/HTML tags removed. A score of 1.0 is also given when one title is the other plus a subtitle.
- **Free-text references:** for `\bibitem` references the parsed title can be wrong. In many styles the journal, not the title, is italicised, and the parser then takes the journal as the title. So a reference also counts as `title_match` when ≥ 90% of the registered title's words appear in its full text (`title_check_method = raw_text`). This rescued 1,098 references that were initially flagged.
- **Status:** `title_match` (≥ 0.9), `title_partial` (0.6–0.9), `title_mismatch` (< 0.6), `not_found`, or `exists_no_metadata`.
- **Year:** the cited year counts as correct if it equals any of Crossref's issued, print or online years, since online-first and print years often differ.
- **First author:** the cited first author's family name must match the registered one; a match on one word of a multi-word surname also counts.

**Rate and etiquette:** Crossref's public pool (5 requests/s, one connection), no contact email sent. Responses are cached in `data/raw/doi_cache.jsonl`.

**Output:** `data/doi_check_ai.csv`, one row per reference with a DOI.

**Caveat:** `title_partial` and `title_mismatch` include legitimate cases, for example a DOI for a chapter cited under the book's title, or a translated title. Every distinct flagged DOI (87 in the AI corpus) is listed in `data/doi_check_ai_flags_for_review.csv` with an empty `verdict` column for manual adjudication. Only adjudicated errors should be reported as citation errors.

### 4.2 Citations among OpenAI preprints (`scripts/ai_cross_citations.py`)

A reference is linked to another OpenAI preprint when it contains a `github.com/openai/math/…/preprints/<folder>` link or an `OAI:<folder>` identifier, or when it names OpenAI as author and its title matches a preprint title exactly. Title alone is not used: *Catalan's constant is irrational* cites a human arXiv paper (Sun, arXiv:2609.04176) with exactly the same title.

**Output:** `data/ai_cross_citations.csv` (603 references to OpenAI works; 599 resolved to a preprint in the repo).

---

## 5. In-text citations and paper-level metrics

### 5.1 In-text citation extraction (`scripts/intext_citations.py`)

The same code runs on both corpora:
1. For each paper, the main document (the `.tex` file with `\begin{document}` whose body is largest after expanding `\input`/`\include`/`\subfile`) is read from `\begin{document}` to the bibliography, with comments removed.
2. Every citation command except `\nocite` is recorded, one row per cited key, with its postnote, section, proof context, position in the text and the number of keys in the command.
3. Lines that define macros (`\def`, `\newcommand`, `\csname`, …) are skipped, because some OpenAI preprints contain tables of cross-reference macros with embedded `\cite` commands that are not citations in running text.

**Pinpoints.** The postnote is the optional argument of `\cite[…]{…}` (natbib's second optional argument when two are given) or amsrefs' `\cite{…}*{…}`. It is classed by the first match, anywhere in the note, as:
- `result`: Theorem, Lemma, Proposition, Corollary, Definition, Remark, Example, Conjecture, Equation, … including French and German forms;
- `location`: Section, Chapter, Appendix, Part, §, a Stacks Project tag, or "Introduction";
- `page`: p., pp., page;
- `numbered`: a bare number such as "II.2.1";
- otherwise `other`.

`prose_pinpoint` flags a result or location named immediately next to the citation in running text ("Theorem 2.3 of \cite{x}", "\cite{x}, Lemma 4").

**Sections.** `section_kind` is assigned from the enclosing `\section`/`\chapter` title by keyword: intro (introduction, overview, main results, …), prelim (preliminaries, background, notation, …), discussion (conclusion, open problems, …), appendix (after `\appendix`), main (everything else), front (before the first section) and abstract. `in_proof` marks citations inside a `proof` environment.

### 5.2 Metrics (`scripts/analyze.py`)

All metrics are computed **per paper** and then averaged, so papers with long reference lists do not dominate.
- **Reference list.** For the OpenAI preprints, the printed list is the `\bibitem` entries plus the `.bib` entries cited in the text. For the human papers, it is the extracted list.
- **Citation age** is the citing year minus the cited work's year. The OpenAI preprints count as 2026 and the human papers use their v1 year.
- **Comparisons** use the 687 subject-labelled OpenAI preprints against the human sample. Differences are mean(AI) − mean(human) with a 95% percentile bootstrap CI (2,000 replicates resampling papers within each corpus, seed `20261007`).
- **Per-subject means** are also reported, to check that pooled differences are not driven by subject mix.

**Outputs:**
- `data/analysis/paper_metrics.csv` (one row per paper);
- `data/analysis/summary.json` (for the dashboard);
- `data/analysis/summary.md` (table).

---

## 6. Known threats to validity

- **Time gap.** Human papers date from 2020–2022 and AI papers from 2026, so the human papers cannot cite anything from the last four years. Citation-age measures should therefore be computed relative to each citing paper's date.
- **Asymmetric parse quality.** Most AI references come from clean BibTeX, while human references come from many different `.bbl` styles. Differences in parsed fields such as venue or title can reflect parsing rather than behaviour. **Planned mitigation:** resolve references in both corpora against the same external database (OpenAlex/Crossref), by DOI, then arXiv ID, then title, and take year, venue, type and citation count from there.
- **Authorship structure.** Human papers have 1–n authors who can cite their own prior work. The AI papers are attributed to "OpenAI" and have no self-citation history, except possibly to each other.
- **Subject labelling is a proxy** (see §2).
- **Leftover files.** arXiv sources sometimes contain stale `.bbl`/`.tex` files from earlier drafts. De-duplication by key limits the damage, but a few reference lists may be slightly inflated.
- **Selection by availability.** PDF-only submissions and papers without an extractable bibliography are excluded, which may skew the sample toward particular authoring workflows.

---

## 7. Reproducing the data

```bash
git clone https://github.com/openai/math data/raw/openai-math   # then: git -C data/raw/openai-math checkout adc7f12
python3 scripts/extract_citations.py data/raw/openai-math data/openai_math_citations.csv
cd scripts
python3 label_ai_subjects.py      # arXiv API lookups (~1 min per 100 IDs)
python3 sample_arxiv.py           # arXiv listings (slow; cached in data/raw/arxiv_listings)
python3 download_arxiv.py         # v1 sources (~3 s per paper; resumable)
python3 extract_arxiv_citations.py            # add --ratio 1 for the balanced 1:1 sample
cd ..
python3 scripts/check_dois.py data/openai_math_citations.csv data/doi_check_ai.csv   # ~35 min
python3 scripts/ai_cross_citations.py
python3 scripts/intext_citations.py ai
python3 scripts/intext_citations.py human
python3 scripts/analyze.py
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
| 2026-10-07 | Sampler: one query over the whole window for categories with ≤ 10,000 results (quarters otherwise); downloads in two passes (1:1, then 2:1) so the sample stays balanced if stopped early. |
| 2026-10-07 | Large remaining categories (> 10,000 results) sampled by random days rather than listed in full, after cs.LG took 75 min to list. |
| 2026-10-07 | Add DOI accuracy check (Crossref → DataCite → doi.org) and the OpenAI internal citation network. |
| 2026-10-07 | Add amsrefs parsing. The final sample is re-derived as the first N usable candidates by random rank, so parser fixes cannot change sample membership other than by restoring rank order. |
| 2026-10-07 | Paper-level metrics with bootstrap CIs. First comparison run on the balanced 1:1 sample (684 human papers) while the 2:1 download continues. |
| 2026-10-08 | 2:1 sample completed (1,374 papers). Download log rebuilt after the rebase incident; cond-mat stratum filled. Results essentially unchanged from 1:1 (pinpointed citations 63.8% vs 22.5%; difference +41.3 points, 95% CI +39.3 to +43.3). |
| 2026-10-07 | Plan to normalise reference metadata for both corpora through a common external database before comparing fields. |
