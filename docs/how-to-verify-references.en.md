# Manual Reference Verification Checklist & Script Limitations

English | [简体中文](./how-to-verify-references.md)

AI writing assistants frequently generate citations that look properly formatted on the surface yet fail against the scholarly record: some entries are completely fabricated, some pair a real paper's title with the wrong authors, and others attach a valid DOI from an unrelated paper to a hallucinated citation. Checking citation formatting alone—or merely testing whether a DOI link resolves—will miss these errors.

This guide provides a **five-step manual verification checklist** that works without any paid tools, followed by an honest discussion of the technical limitations and design trade-offs in `tools/check_references.py`.

---

## Part 1: Five-Step Manual Verification Checklist

### Step 1: Break Each Reference into Four Verifiable Claims
Treat every bibliography entry as a conjunction of four factual claims that must all hold simultaneously:
1. **Title**: Exact main title and subtitle wording, without synonym substitution.
2. **Authors**: At minimum the first author's surname and the overall author team (watch out for real titles paired with wrong authors, or famous researchers paired with invented titles).
3. **Year & Venue**: Publication year and the journal, conference proceedings, or book publisher.
4. **Identifiers (DOI / PMID / arXiv ID / ISBN)**: Any persistent identifier printed in the reference string.

### Step 2: Resolve Identifiers First, Then Cross-Check Every Field
When a reference includes a DOI, PMID, or arXiv ID:
- Open `https://doi.org/<DOI>`, PubMed, or arXiv directly, or query Crossref (`https://api.crossref.org/works/<DOI>`).
- **Never stop at HTTP 200**. Verify that the resolved record actually describes the cited work:
  - Does the landing-page title match the cited title? (Catches hijacked or mismatched DOIs pointing to a completely different paper.)
  - Does the first author match?
  - Does the publication year agree (allowing for legitimate ±1 year online-first vs. print issue differences where appropriate)?
- If a DOI fails to resolve (404), do not immediately assume the paper is fake—typos in DOI suffixes are common. Proceed to Step 3 and search by title.

### Step 3: Verify DOI-Less References by Exact Title + First Author
Many legitimate works have no DOI—or are commonly cited without one—including Chinese domestic journal papers, older computer science conference papers (e.g., NeurIPS, ICML, AAAI), books, book chapters, theses, and technical standards:
- **English journals & conferences**: Search the full title in [OpenAlex](https://openalex.org/), [Crossref Metadata Search](https://search.crossref.org/), DBLP (computer science), or PubMed (biomedicine), and verify the first author and year against the top candidate.
- **Chinese journals & theses**: Because international open indexes have incomplete coverage of Chinese-language periodicals, verify exact Chinese titles and authors in CNKI, Wanfang, VIP, or the National Center for Philosophy and Social Sciences Documentation.
- **Books, chapters & standards**: Check WorldCat, national library OPAC catalogs, or the publisher's catalog to confirm title, author/editor, edition, and year.
- **Watch for paraphrased titles**: If a search surfaces a paper by the exact same authors in the same year and venue, but several words in your cited title are replaced with synonyms (e.g., *Hallucination and inaccuracies in bibliographic references...* instead of *Fabrication and errors in the bibliographic citations...*), treat it as an AI-paraphrased citation and restore the exact published title.

### Step 4: Check Retractions, Errata, and Preprint Status
Even when a paper exists and every metadata field matches, check its editorial standing:
- Inspect the publisher's page, Crossref `update-to` metadata, or OpenAlex `is_retracted` flags to confirm the work has not been **retracted** or flagged with an Expression of Concern. Retracted works should not be cited as supporting evidence.
- If the entry cites an arXiv, bioRxiv, or medRxiv preprint, check whether a peer-reviewed journal or conference version has since been published, and update the venue, year, and DOI accordingly.

### Step 5: Verify Claim-Level Support in the Primary Source
Bibliographic verification only proves that a paper exists—**not that it supports your sentence**:
- Read the abstract, results, or specific tables/figures of the source paper to confirm its findings actually support (rather than contradict or merely touch upon) the claim in your manuscript.

---

## Part 2: Limitations & Trade-Offs of `tools/check_references.py`

`tools/check_references.py` is a zero-dependency Python standard-library CLI tool that checks entries with DOIs via Crossref and searches DOI-less entries via OpenAlex. Keep the following technical limitations in mind when interpreting its output:

### 1. Incomplete Coverage of Non-English Literature and Books in OpenAlex / Crossref
- **Indexing gaps**: OpenAlex and Crossref cover English-language journals well, along with Chinese journals that register DOIs or participate in international open-access indexes. However, many Chinese domestic journal articles, books, book chapters, dissertations, and national standards (e.g., GB/T) are absent from both APIs and will return `not_found` even when the work is genuine.
- **Cross-script author names (Chinese characters vs. Pinyin)**: Many Chinese papers indexed in OpenAlex or Crossref store author names only in romanized Pinyin (e.g., `Wei Zhang`), whereas a GB/T 7714 reference lists Chinese characters (`张伟`)—or vice versa. Because a pure standard-library script does not bundle a Chinese-to-Pinyin transliteration table, cross-script author comparison can fail and report `mismatch (author)` on a valid Chinese paper. Always verify Chinese `not_found` and `mismatch (author)` results manually.

### 2. Title Similarity Threshold Trade-Offs (`difflib.SequenceMatcher`)
The script normalizes titles (stripping GB/T type markers such as `[J]`/`[M]`, punctuation, and case differences) and computes character-level similarity with `difflib.SequenceMatcher`:
- **If the threshold is too strict (e.g., `> 0.92`)**: Legitimate citations get flagged as `mismatch` or `not_found` whenever a subtitle is omitted, Greek letters or chemical formulas are transliterated (`β` vs. `beta`), or punctuation differs.
- **If the threshold is too loose (e.g., `< 0.75`)**: Subtle AI title paraphrases slip through as `verified`, and distinct papers with formulaic survey titles (*A Survey of Deep Learning for ...*) can be confused with one another.
- **Current threshold choice**: `tools/check_references.py` uses `0.60` as the minimum candidate recall threshold (below `0.60` is `not_found`) and `0.85` as the exact-title match threshold (scores in `[0.60, 0.85)` trigger `mismatch` on `title` so a human can inspect the closest candidate). Short titles or entries with long subtitles can still fall on the wrong side of any fixed cutoff.

### 3. Legitimate Publication Year Discrepancies
Scholarly databases frequently record slightly different years for the same work:
- Online-first publication in late year $Y$ followed by print volume assignment in year $Y+1$;
- Preprint year vs. conference proceedings year (e.g., arXiv 2017 vs. conference 2018), or retroactive DOIs registered years after the original conference;
- Different editions or reprints of books.
The script allows a `±1` year tolerance for minor online/print offsets while flagging larger year gaps as `mismatch (year)`. Any year mismatch on a book or conference paper should be checked against the edition actually consulted.

### 4. Heuristic Plain-Text Parsing Boundaries
To run without external NLP dependencies or LLM API keys, the script uses regular expressions and structural rules to extract DOIs, years, first-author surnames, and titles across APA, GB/T 7714, Vancouver, and IEEE styles:
- Malformed plain-text citations—such as unparenthesized years, missing period delimiters between authors and titles, or multi-sentence titles—can cause partial title extraction, degrading OpenAlex search ranking and similarity scores.

### 5. No Full-Text Semantic or Editorial Judgement
The script checks bibliographic existence and core metadata alignment (`title`, `year`, `first_author`). It cannot read the full text to verify whether a cited paper actually supports your argument, nor can it substitute for checking publisher retraction notices before submission.
