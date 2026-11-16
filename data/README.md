# Dataset Schema & Construction (`data/references.csv`)

`references.csv` contains **40 academic bibliography entries** designed to benchmark reference verification workflows—especially **references without DOIs** and **references with hijacked/mismatched DOIs** that DOI-only existence scripts miss.

---

## Summary Statistics

| Dimension | Breakdown |
| --- | --- |
| Total entries | **40** (`R01`–`R40`) |
| Ground-truth `label` | **20 `valid`** (`R01`–`R20`, verified via Crossref / OpenAlex APIs) · **20 `invalid`** (`R21`–`R40`, controlled error samples) |
| Citation styles (`style`) | **10 `APA`** · **10 `GB/T 7714`** · **10 `Vancouver`** · **10 `IEEE`** (5 `valid` + 5 `invalid` per style) |
| Languages (`language`) | **28 `en`** (English) · **12 `zh`** (Chinese) |
| DOI in reference string (`has_doi`) | **15 `true`** (8 `valid` + 7 `invalid`) · **25 `false`** (12 `valid` + 13 `invalid`) |

---

## Column Definitions (`references.csv`)

| Column | Type / Allowed Values | Description |
| --- | --- | --- |
| `id` | `R01`–`R40` | Stable row identifier. |
| `style` | `APA` \| `GB/T 7714` \| `Vancouver` \| `IEEE` | Formatting style used in `reference`. |
| `language` | `en` \| `zh` | Primary language of the cited work (`en` = English, `zh` = Simplified Chinese). |
| `has_doi` | `true` \| `false` | Whether the formatted `reference` string explicitly prints a DOI or `doi.org` link. Note: several `has_doi=false` papers do have a DOI in scholarly registries, omitted here to simulate real-world DOI-less citations. |
| `reference` | UTF-8 string | Full formatted bibliography entry as it would appear in a manuscript reference list. **This is the only bibliographic field read by `tools/check_references.py`.** |
| `label` | `valid` \| `invalid` | Ground-truth binary label: `valid` = genuine work with accurate metadata; `invalid` = fabricated or corrupted entry. |
| `error_type` | `none` \| `fabricated` \| `wrong_authors` \| `wrong_year_or_venue` \| `wrong_doi` \| `paraphrased_title` | Fine-grained error taxonomy (see table below). |
| `verified_doi` | DOI string or empty | Canonical DOI confirmed via Crossref/OpenAlex for the real underlying paper (empty for completely fabricated entries or real papers without a registered DOI). |
| `openalex_id` | OpenAlex URL or empty | Canonical OpenAlex Work URI (`https://openalex.org/W...`) confirmed via OpenAlex API for the real underlying paper. |
| `notes` | UTF-8 string | Provenance note for `valid` rows, or exact corruption applied for `invalid` rows. |

---

## Error Type Taxonomy (`error_type` / 错误类型说明)

| `error_type` | 中文对应类型 | Count | Construction Rule |
| --- | --- | --- | --- |
| `none` | 真实无误文献 | 20 | Real published journal articles and conference papers verified against live Crossref and/or OpenAlex records (`R01`–`R20`). |
| `fabricated` | 完全编造 | 4 | Non-existent paper title, author combination, and venue (`R21`–`R24`; includes `R23` with a plausible-looking non-existent DOI). |
| `wrong_authors` | 标题真实但作者错 | 4 | Exact title, year, and venue of a real paper paired with unrelated or invented authors (`R25`–`R28`). |
| `wrong_year_or_venue` | 作者真实但年份/期刊错 | 4 | Real authors and exact title paired with a falsified publication year and/or falsified journal/proceedings (`R29`–`R32`). |
| `wrong_doi` | DOI 属于另一篇论文 | 4 | Citation text describes Paper A (or a fabricated paper), while the attached DOI resolves in Crossref to an unrelated real Paper B (`R33`–`R36`). |
| `paraphrased_title` | 标题轻微改写 | 4 | Real authors, year, and venue (cited without DOI), with content words in the title rewritten via synonym substitution (`R37`–`R40`). |

---

## Zero-Leakage Evaluation Note

When `tools/check_references.py` runs on `data/references.csv`, it parses **only** `id` and `reference`. Ground-truth columns (`label`, `error_type`, `verified_doi`, `openalex_id`, `notes`) are never read during verification and are inspected only afterward when `--evaluate` is passed to compute accuracy and confusion matrices.

---

## License

`data/references.csv` and `data/README.md` are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
