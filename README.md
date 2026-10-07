# Citation practices in AI-generated mathematics

Does AI-generated mathematical research cite different sources, or use its sources differently, than human-written research?

This project compares the reference lists of the 722 preprints OpenAI released in [openai/math](https://github.com/openai/math) (September–October 2026) with a subject-matched sample of human-written arXiv papers from 2020–2022, before LLM-assisted writing was common.

**Status:** work in progress. The AI corpus is complete; the human comparison sample is being collected.

## Data

| File | Contents |
|---|---|
| `data/openai_math_citations.csv` | 17,957 references extracted from the 722 OpenAI preprints, one row per reference per preprint |
| `data/ai_preprint_subjects.csv` | Inferred arXiv subject category for each OpenAI preprint |
| `data/arxiv_categories_of_cited_works.csv` | Primary arXiv category of every arXiv paper the OpenAI preprints cite |
| `data/human_candidates.csv` | Shuffled, stratified candidate list for the human sample *(in progress)* |
| `data/human_sample_log.csv` | Outcome for every human candidate examined *(in progress)* |
| `data/human_arxiv_citations.csv` | References extracted from the human sample *(in progress)* |

Column definitions, sampling design, extraction rules and known limitations are in **[METHODOLOGY.md](METHODOLOGY.md)**.

## Reproducing

The scripts in `scripts/` use only the Python 3 standard library. See [METHODOLOGY.md §5](METHODOLOGY.md#5-reproducing-the-data) for the full pipeline. Raw downloads (the OpenAI repository and arXiv LaTeX sources) are kept in `data/raw/` and not committed.

## License

- **Code** (`scripts/`): [MIT](LICENSE).
- **Data and documentation** (`data/`, `README.md`, `METHODOLOGY.md`, and any analysis write-ups): [CC BY 4.0](LICENSE-DATA). Please credit "Quinn Morris, *Citation practices in AI-generated mathematics*" and link to this repository.

The CSVs contain bibliographic metadata extracted from third-party works: the OpenAI preprints ([openai/math](https://github.com/openai/math), Apache 2.0) and arXiv papers, which remain under their authors' licences. CC BY 4.0 applies to this project's own contributions (selection, extraction, cleaning and derived fields). It does not grant any rights in those underlying works.
