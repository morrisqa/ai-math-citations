# Citation practices in AI-generated mathematics

Does AI-generated mathematical research cite different sources, or use its sources differently, than human-written research?

This project compares the reference lists of the 722 preprints OpenAI released in [openai/math](https://github.com/openai/math) (September–October 2026) with a subject-matched sample of human-written arXiv papers from 2020–2022, before LLM-assisted writing was common.

**Status:** first-pass results on the full 2:1 subject-matched sample (687 OpenAI preprints vs 1,374 human papers). See the [dashboard](https://morrisqa.github.io/ai-math-citations/) or [`data/analysis/summary.md`](data/analysis/summary.md).

## Dashboard

An interactive summary lives in [`docs/index.html`](docs/index.html) and is published with GitHub Pages (**Settings → Pages → Deploy from a branch → `main`, folder `/docs`**). It reads `docs/data/`, which `scripts/analyze.py` refreshes. Each table on the page links to [Datasette Lite](https://lite.datasette.io/), so readers can query the full CSVs with SQL in the browser.

To preview locally: `cd docs && python3 -m http.server`, then open http://localhost:8000.

## Data

| File | Contents |
|---|---|
| `data/openai_math_citations.csv` | 17,957 references extracted from the 722 OpenAI preprints, one row per reference per preprint |
| `data/ai_preprint_subjects.csv` | Inferred arXiv subject category for each OpenAI preprint |
| `data/arxiv_categories_of_cited_works.csv` | Primary arXiv category of every arXiv paper the OpenAI preprints cite |
| `data/ai_cross_citations.csv` | References from OpenAI preprints to other OpenAI preprints |
| `data/doi_check_ai.csv` | Registry check of every DOI cited by the OpenAI preprints *(in progress)* |
| `data/doi_check_ai_flags_for_review.csv` | Distinct flagged DOIs, for manual adjudication |
| `data/human_candidates.csv` | Shuffled, stratified candidate list for the human sample |
| `data/human_sample_log.csv` | Downloader outcome for every human candidate examined |
| `data/human_sample.csv` | Final selection: first N usable candidates per subject in random-rank order |
| `data/human_arxiv_citations.csv` | References extracted from the selected human papers |
| `data/ai_intext_citations.csv`, `data/human_intext_citations.csv` | Every in-text citation with its pinpoint, section and proof context |
| `data/analysis/` | Paper-level metrics, corpus comparison (`summary.md`) and dashboard data (`summary.json`) |

Column definitions, sampling design, extraction rules and known limitations are in **[METHODOLOGY.md](METHODOLOGY.md)**.

## Reproducing

The scripts in `scripts/` use only the Python 3 standard library. See [METHODOLOGY.md §7](METHODOLOGY.md#7-reproducing-the-data) for the full pipeline. Raw downloads (the OpenAI repository and arXiv LaTeX sources) are kept in `data/raw/` and not committed.

## Author

Quinn Morris, Department of Mathematical Sciences, Appalachian State University
[ORCID 0000-0002-6892-1848](https://orcid.org/0000-0002-6892-1848) · [Profile and contact](https://mathsci.appstate.edu/people/quinn-morris)

To cite this work, use the "Cite this repository" button on GitHub, which reads [CITATION.cff](CITATION.cff).

## License

- **Code** (`scripts/`): [MIT](LICENSE).
- **Data and documentation** (`data/`, `README.md`, `METHODOLOGY.md`, and any analysis write-ups): [CC BY 4.0](LICENSE-DATA). Please credit "Quinn Morris, *Citation practices in AI-generated mathematics*" and link to this repository.

The CSVs contain bibliographic metadata extracted from third-party works: the OpenAI preprints ([openai/math](https://github.com/openai/math), Apache 2.0) and arXiv papers, which remain under their authors' licences. CC BY 4.0 applies to this project's own contributions (selection, extraction, cleaning and derived fields). It does not grant any rights in those underlying works.
