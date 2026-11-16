# citereal-reference-check-dataset

English | [简体中文](./README.zh-CN.md)

`citereal-reference-check-dataset` is an open benchmark dataset of genuine and corrupted academic references paired with a zero-dependency Python verification script, built for researchers, graduate students, journal editors, peer reviewers, and developers evaluating citation-checking workflows. You can use it out of the box to screen plain-text or CSV bibliography lists—including conference papers, Chinese-language articles, and citations without DOIs—against Crossref and OpenAlex, or to benchmark citation verifiers across five common hallucination and metadata-corruption patterns. The official website of CiteReal is [citereal.ai](https://citereal.ai).

---

## Why DOI-Only Scripts Miss Broken References

Many lightweight verification scripts only extract `10.xxxx/...` strings and check whether `doi.org` returns HTTP 200. In practice, two failure modes slip past DOI-only checks:

1. **Legitimate references without DOIs**: Conference proceedings (such as NeurIPS or NAACL), Chinese journal articles, books, standards, and clinical commentaries frequently appear in reference lists without a DOI.
2. **Mismatched or hijacked DOIs**: AI writing assistants often attach a real, resolvable DOI from an unrelated paper to a fabricated or mismatched citation. Resolving the DOI without comparing **title, publication year, and first author** marks a false citation as valid.

This repository addresses both problems using only Python's standard library.

---

## Repository Contents

```text
.
├── data/
│   ├── references.csv                  # 40 labeled references (20 valid + 20 error samples)
│   └── README.md                       # Column schema & error taxonomy documentation
├── tools/
│   └── check_references.py             # Pure Python stdlib CLI checker (Crossref + OpenAlex + difflib)
├── results/
│   └── run-2026-11-16.md               # Benchmark run report, confusion matrix & error analysis
├── docs/
│   ├── how-to-verify-references.en.md  # 5-step manual verification checklist & script limitations
│   └── how-to-verify-references.md     # 人工核查五步清单与脚本局限说明（中文）
├── README.md
├── README.zh-CN.md
└── LICENSE                             # MIT License (code)
```

---

## Quick Start (No Third-Party Dependencies)

Requires **Python 3.9+** with internet access to `api.crossref.org` and `api.openalex.org`. No `pip install` or API keys are needed.

### 1. Check a Plain-Text Reference List

Put one formatted reference per line in a `.txt` file (APA, GB/T 7714, Vancouver, or IEEE) and run:

```bash
python3 tools/check_references.py path/to/my_references.txt
```

Export structured JSON or CSV reports if needed:

```bash
python3 tools/check_references.py path/to/my_references.txt \
  --output-csv check_report.csv \
  --output-json check_report.json
```

### 2. Run and Evaluate on the Included Benchmark Dataset

```bash
python3 tools/check_references.py data/references.csv --evaluate
```

### CLI Options

| Flag | Default | Description |
| --- | --- | --- |
| `--format {auto,csv,text}` | `auto` | Input format (auto-detected from `.csv` vs. other extensions). |
| `--interval SECONDS` | `1.05` | Delay between HTTP requests (enforced $\ge 1.0\text{s}$). |
| `--title-threshold FLOAT` | `0.85` | Minimum `difflib` normalized title similarity for `verified`. |
| `--year-tolerance INT` | `1` | Allowed year difference before reporting `mismatch (year)`. |
| `--output-csv PATH` | — | Save per-entry verdicts and matched records to CSV. |
| `--output-json PATH` | — | Save per-entry verdicts and matched records to JSON. |
| `--evaluate` | `false` | Compute accuracy and `error_type` breakdown when `label` is present in CSV. |

---

## How `tools/check_references.py` Works

1. **Field Extraction**: Parses the raw citation string to extract any DOI, normalized title, publication year, and first-author surname (or full Chinese name), supporting APA, GB/T 7714 (`[J]`, `[C]`, `[M]`), Vancouver, and IEEE styles.
2. **DOI Path (Crossref)**: When a DOI is present, queries `https://api.crossref.org/works/<DOI>` and compares the returned record's title (`difflib.SequenceMatcher`), publication year, and first author against the citation. If the DOI returns 404, falls back to OpenAlex title search to distinguish a broken DOI (`mismatch: doi`) from a non-existent work (`not_found`).
3. **DOI-Less Path (OpenAlex)**: When no DOI is present, queries `https://api.openalex.org/works?search=<title>`, ranks candidates by `difflib` title similarity, and verifies title similarity, year, and first-author surname.
4. **Output Verdicts**:
   - `verified`: Identifier or title search found a matching work and `title`, `year`, and `first_author` all agree.
   - `mismatch`: A corresponding record or DOI target was found, listing specifically which field(s) failed (`doi`, `title`, `year`, `first_author`).
   - `not_found`: Neither Crossref nor OpenAlex returned a candidate meeting the similarity floor (`0.60`).
   - `network_error`: Unrecoverable HTTP or socket error after retries.

All requests enforce $\ge 1\text{s}$ spacing and send `User-Agent: citereal-reference-check-dataset/0.1`.

---

## Benchmark Dataset & Measured Results

[`data/references.csv`](./data/references.csv) (documented in [`data/README.md`](./data/README.md)) contains **40 entries** across **APA (10)**, **GB/T 7714 (10)**, **Vancouver (10)**, and **IEEE (10)** in **English (28)** and **Chinese (12)**, with **25 DOI-less** entries and **15 entries with DOIs**:

- **20 `valid` references (`error_type=none`)**: Genuine works verified against live Crossref and/or OpenAlex records.
- **20 `invalid` error samples** (4 per category):
  - `fabricated`: Completely invented paper, authors, and venue.
  - `wrong_authors`: Real paper title, year, and venue paired with wrong authors.
  - `wrong_year_or_venue`: Real authors and title paired with a falsified year and/or venue.
  - `wrong_doi`: DOI resolves to an unrelated real paper.
  - `paraphrased_title`: Real authors, year, and venue with a synonym-paraphrased title.

In the full benchmark run recorded in [`results/run-2026-11-16.md`](./results/run-2026-11-16.md), `tools/check_references.py` achieved **38 / 40 (95.0%)** binary accuracy (`0` network errors):

- **False negative (`R08`)**: A genuine Chinese GB/T 7714 paper matched its exact Chinese title in OpenAlex (`sim=1.00`), but OpenAlex stores the author in Pinyin (`Guangshuai Gao`) rather than Chinese characters (`高广帅`), causing `mismatch (first_author)`.
- **False positive (`R32`)**: An entry keeping Vaswani et al. (2017) *Attention Is All You Need* intact while replacing the NeurIPS venue with a fabricated IEEE journal passed as `verified` because the script does not compare journal/conference names or volume/page numbers.

---

## Manual Verification & Known Limitations

Automated scripts are a fast screening filter, not a substitute for inspecting primary sources. See [`docs/how-to-verify-references.en.md`](./docs/how-to-verify-references.en.md) for:

- A **five-step manual verification checklist** covering identifier cross-checks, multi-database lookup for DOI-less Chinese and book citations, retraction checks, and claim-level reading.
- **Known script limitations**, including incomplete OpenAlex/Crossref indexing of Chinese domestic journals and books, Pinyin vs. Chinese-character author mismatches, `difflib` title similarity threshold trade-offs, and legitimate online-first vs. print year offsets.

---

## Want to Automate This?

If you want a web workflow for larger batches or uploaded manuscripts, [CiteReal Citation Checker](https://citereal.ai/tools/citation-checker) verifies pasted reference lists or uploaded `.pdf`, `.docx`, and `.txt` files (up to 15 MB after sign-in) against Crossref, OpenAlex, PubMed, arXiv, and Semantic Scholar, reporting verified, partial, suspicious, and not-found statuses, flagging retracted papers, and exporting confirmed entries in APA 7, MLA 9, Chicago 18, Harvard, or IEEE. When you have a claim or short paragraph (up to 600 characters) that needs real references, [CiteReal Source Finder](https://citereal.ai/tools/source-finder) searches OpenAlex and Semantic Scholar and ranks non-retracted papers by abstract support. Visitors get 3 free runs per UTC day without an account (up to 2,000 characters per check), free accounts receive 50 credits on sign-up plus 20 daily credits (10 credits per reference checked; 30 credits per Source Finder run), and paid subscriptions start at $20/month or $120/year for 800 monthly credits (Chinese domestic databases such as CNKI and Wanfang are not yet integrated, and metadata checking does not verify full-text claim support).

---

## License

- **Code** (`tools/`): Licensed under the MIT License — see [LICENSE](./LICENSE).
- **Documentation, data, and images** (`data/`, `docs/`, `results/`, `README.md`, `README.zh-CN.md`): Licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
