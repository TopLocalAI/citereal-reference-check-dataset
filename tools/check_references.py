#!/usr/bin/env python3
"""Verify academic references with or without DOIs using Python's standard library.

Workflow per reference:
1. Extract DOI, title, publication year, and first-author surname from CSV or plain text.
2. If a DOI is present, resolve it via Crossref (`https://api.crossref.org/works/<DOI>`)
   and compare title (`difflib`), year, and first author.
3. If no DOI is present, search OpenAlex by title (`https://api.openalex.org/works?search=...`),
   select the candidate with highest `difflib` title similarity, and compare title, year,
   and first-author surname.
4. Emit one of four verdicts: `verified`, `mismatch` (listing mismatched fields),
   `not_found`, or `network_error`.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

USER_AGENT = "citereal-reference-check-dataset/0.1"
CROSSREF_WORKS_URL = "https://api.crossref.org/works/"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"

DEFAULT_INTERVAL = 1.05
MIN_ALLOWED_INTERVAL = 1.0
DEFAULT_TITLE_THRESHOLD = 0.85
CANDIDATE_FLOOR = 0.60
DEFAULT_YEAR_TOLERANCE = 1

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
GBT_MARKER_RE = re.compile(
    r"\[(?:J|M|C|D|R|S|N|G|P|EB|DB|CP|Z|A)(?:/OL)?\]", re.IGNORECASE
)
DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi\s*[:：]\s*)(10\.\d{4,9}/[^\s,;\"'<>]+)"
    r"|\b(10\.\d{4,9}/[^\s,;\"'<>]+)",
    re.IGNORECASE,
)


@dataclass
class ParsedReference:
    ref_id: str
    raw: str
    title: str = ""
    first_author: str = ""
    year: int | None = None
    doi: str | None = None


@dataclass
class CandidateRecord:
    source: str  # "crossref" | "openalex"
    identifier: str
    doi: str | None
    title: str
    authors: list[str]
    year: int | None
    venue: str | None = None
    cited_by_count: int = 0


@dataclass
class CheckOutcome:
    ref_id: str
    raw: str
    parsed_title: str
    parsed_first_author: str
    parsed_year: int | None
    parsed_doi: str | None
    status: str  # verified | mismatch | not_found | network_error
    mismatched_fields: list[str] = field(default_factory=list)
    title_similarity: float | None = None
    matched_source: str | None = None
    matched_id: str | None = None
    matched_title: str | None = None
    matched_first_author: str | None = None
    matched_year: int | None = None
    reason: str = ""


class PoliteHttpClient:
    """Enforces >= 1.0s spacing between requests with fixed User-Agent."""

    def __init__(self, min_interval: float = DEFAULT_INTERVAL, timeout: float = 15.0):
        self.min_interval = max(MIN_ALLOWED_INTERVAL, float(min_interval))
        self.timeout = timeout
        self._last_request_at: float | None = None

    def get_json(
        self, url: str, max_retries: int = 2
    ) -> tuple[int, dict[str, Any] | None, str | None]:
        for attempt in range(max_retries + 1):
            if self._last_request_at is not None:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self.min_interval:
                    time.sleep(self.min_interval - elapsed)

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                },
            )
            try:
                self._last_request_at = time.monotonic()
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw_bytes = resp.read()
                    status_code = resp.getcode() or 200
                data = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                return status_code, data, None
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return 404, None, None
                if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    retry_hdr = exc.headers.get("Retry-After") if exc.headers else None
                    wait_sec = 3.0 * (attempt + 1)
                    if retry_hdr:
                        try:
                            wait_sec = min(45.0, max(self.min_interval, float(retry_hdr) + 1.0))
                        except ValueError:
                            pass
                    time.sleep(wait_sec)
                    self._last_request_at = time.monotonic()
                    continue
                return exc.code, None, f"HTTP {exc.code}: {exc.reason}"
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                if attempt < max_retries:
                    time.sleep(2.0 * (attempt + 1))
                    self._last_request_at = time.monotonic()
                    continue
                return 0, None, str(exc)
        return 0, None, "Exhausted retries"


def clean_doi(raw_doi: str) -> str:
    doi = raw_doi.strip()
    while doi and doi[-1] in ".,;]}>\"'":
        doi = doi[:-1]
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    return doi.lower()


def extract_doi(text: str) -> str | None:
    match = DOI_RE.search(text)
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    return clean_doi(raw) if raw else None


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_title(title: str) -> str:
    text = html.unescape(title or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = GBT_MARKER_RE.sub("", text)
    text = strip_accents(text).lower()
    # Keep ASCII alphanumerics and CJK unified ideographs; turn punctuation into spaces.
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    # Remove spaces between adjacent CJK characters while keeping word spaces for Latin.
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    return re.sub(r"\s+", " ", text).strip()


def compute_title_similarity(title_a: str, title_b: str) -> float:
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)
    if not norm_a or not norm_b:
        return 0.0
    return difflib.SequenceMatcher(None, norm_a, norm_b).ratio()


def extract_first_author_key(authors_segment: str) -> str:
    """Extract first-author surname (Latin) or full name (CJK) from an author list string."""
    seg = authors_segment.strip()
    seg = re.sub(r"^\s*(?:\[\d+\]|\d{1,3}[.)])\s*", "", seg)
    seg = re.sub(r"\b(?:et\s+al\.?|and\s+others)\b.*$", "", seg, flags=re.IGNORECASE)
    seg = re.sub(r"(?:等|等人)\s*$", "", seg)
    if not seg:
        return ""

    # If the segment starts with CJK characters, extract the first Chinese author name.
    first_chunk = re.split(r"[,，;；、&]|\band\b", seg, maxsplit=1)[0].strip()
    cjk_chars = "".join(CJK_RE.findall(first_chunk))
    if cjk_chars:
        return cjk_chars

    # APA style: "Surname, F. M., & ..." -> before first comma is the surname.
    if "," in seg:
        before_comma = seg.split(",", 1)[0].strip()
        # Distinguish "Jumper, J." (APA) from "J. Jumper, R. Evans" (IEEE):
        # IEEE has initials with periods or 1-letter tokens before surname.
        tokens = before_comma.split()
        if len(tokens) >= 2 and (
            tokens[0].endswith(".")
            or (len(tokens[0].rstrip(".")) == 1 and tokens[0][0].isupper())
        ):
            # IEEE "J. Jumper" or "W.-N. Hsu"
            return tokens[-1].strip(".")
        # Vancouver / GB/T 7714: "Polack FP", "Lake B M", "Van Der Maaten L"
        m_van = re.match(r"^(.+?)(?:\s+[A-Z]{1,4}\.?)+$", before_comma)
        if m_van:
            return m_van.group(1).strip()
        return before_comma

    # Single-author without comma: e.g. "K. He" or "Polack FP" or "Lake B M"
    m_van = re.match(r"^(.+?)(?:\s+[A-Z]{1,4}\.?)+$", first_chunk)
    if m_van and not first_chunk.split()[0].endswith("."):
        return m_van.group(1).strip()
    tokens = first_chunk.split()
    return tokens[-1].strip(".") if tokens else ""


def extract_year_from_tail(tail: str) -> int | None:
    # Remove page ranges like "pp. 1877-1901", "1920–1933", ": 1990-2005" before year search
    cleaned = re.sub(r"(?:\bpp?\.\s*|[:：]\s*)\d+\s*[-–—]\s*\d+", " ", tail, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{3,5}\s*[-–—]\s*\d{3,5}\b", " ", cleaned)
    years = re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", cleaned)
    return int(years[0]) if years else None


def parse_reference(raw: str, ref_id: str = "") -> ParsedReference:
    text = raw.strip()
    doi = extract_doi(text)

    # Remove leading numbering and trailing DOI / URL segments to simplify field extraction.
    work = re.sub(r"^\s*(?:\[\d+\]|\d{1,3}[.)]|\(\d+\))\s*", "", text)
    work = re.sub(
        r"\s*(?:https?://(?:dx\.)?doi\.org/\S+|doi\s*[:：]\s*\S+)\s*\.?\s*$",
        "",
        work,
        flags=re.IGNORECASE,
    )
    work = re.sub(
        r"\s*(?:Available\s*:\s*)?https?://\S+\s*\.?\s*$",
        "",
        work,
        flags=re.IGNORECASE,
    ).strip()

    # 1. IEEE style: Authors, "Title," Venue, ..., Year.
    m_quote = re.search(r"^(?P<authors>.+?)[,，.\s]+[\"“](?P<title>[^\"”]{5,})[\"”](?P<tail>.*)$", work)
    if m_quote:
        authors_part = m_quote.group("authors")
        title = m_quote.group("title").strip().rstrip(",，.。")
        tail = m_quote.group("tail")
        year = extract_year_from_tail(tail)
        return ParsedReference(
            ref_id=ref_id,
            raw=raw,
            title=title,
            first_author=extract_first_author_key(authors_part),
            year=year,
            doi=doi,
        )

    # 2. APA style: Authors (2021). Title. Venue...
    m_apa = re.match(
        r"^(?P<authors>.+?)\s*[\(（](?P<year>19\d{2}|20\d{2})[a-z]?[\)）][.．。]?\s*(?P<rest>.+)$",
        work,
    )
    if m_apa:
        authors_part = m_apa.group("authors").rstrip(".．,， ")
        year = int(m_apa.group("year"))
        rest = m_apa.group("rest").strip()
        # Split title from venue at the first sentence terminator followed by space or end.
        title_split = re.split(r"(?<!\bvs)[.。]\s+|(?<=[\u4e00-\u9fff])[.．。]\s*", rest, maxsplit=1)
        title = title_split[0].strip()
        # Strip trailing book edition markers like "(2nd ed.)"
        title = re.sub(r"\s*[\(（][^\)）]*\bed(?:ition|\.)?[\)）]\s*$", "", title, flags=re.IGNORECASE)
        title = GBT_MARKER_RE.sub("", title).strip()
        return ParsedReference(
            ref_id=ref_id,
            raw=raw,
            title=title,
            first_author=extract_first_author_key(authors_part),
            year=year,
            doi=doi,
        )

    # 3. GB/T 7714 style with [J], [M], [C], [D], etc.
    m_gbt = GBT_MARKER_RE.search(work)
    if m_gbt:
        before_marker = work[: m_gbt.start()].strip()
        after_marker = work[m_gbt.end() :]
        parts = re.split(r"[.．。]\s*", before_marker, maxsplit=1)
        if len(parts) == 2:
            authors_part, title = parts[0], parts[1]
        else:
            authors_part, title = "", before_marker
        year = extract_year_from_tail(after_marker)
        return ParsedReference(
            ref_id=ref_id,
            raw=raw,
            title=title.strip(),
            first_author=extract_first_author_key(authors_part),
            year=year,
            doi=doi,
        )

    # 4. Vancouver / general period-delimited style: Authors. Title. Venue. Year;Vol(Issue):Pages.
    segments = [
        s.strip()
        for s in re.split(r"[.。]\s+|\s*。\s*", work)
        if s.strip()
    ]
    authors_part = segments[0] if len(segments) >= 2 else ""
    title = segments[1] if len(segments) >= 2 else work
    tail = " ".join(segments[2:]) if len(segments) > 2 else work
    year = extract_year_from_tail(tail) or extract_year_from_tail(work)
    return ParsedReference(
        ref_id=ref_id,
        raw=raw,
        title=title.strip(),
        first_author=extract_first_author_key(authors_part),
        year=year,
        doi=doi,
    )


def candidate_author_keys(author_display: str) -> set[str]:
    """Generate comparable normalized surname/CJK keys from a Crossref/OpenAlex author string."""
    keys: set[str] = set()
    raw = (author_display or "").strip()
    if not raw:
        return keys

    cjk_all = "".join(CJK_RE.findall(raw))
    if cjk_all:
        keys.add(cjk_all)
        # OpenAlex sometimes stores Chinese names in Western order with space: "玉志 王" -> "王玉志"
        cjk_parts = ["".join(CJK_RE.findall(tok)) for tok in raw.split() if CJK_RE.search(tok)]
        if len(cjk_parts) == 2 and len(cjk_parts[1]) == 1:
            keys.add(cjk_parts[1] + cjk_parts[0])

    latin_raw = re.sub(r"[\(（][^\)）]*[\)）]", " ", raw)
    latin_norm = strip_accents(latin_raw).lower()
    latin_norm = re.sub(r"[^a-z\s\-']", " ", latin_norm).strip()
    if latin_norm:
        if "," in raw:
            surname = strip_accents(raw.split(",", 1)[0]).lower()
            surname = re.sub(r"[^a-z\-']", "", surname)
            if surname:
                keys.add(surname)
        tokens = [t.strip("-'") for t in latin_norm.split() if t.strip("-'")]
        if tokens:
            keys.add(tokens[-1])
            # Also add full joined surname for particle names like "van der maaten"
            if len(tokens) >= 2:
                keys.add("".join(tokens[-2:]))
    return keys


def first_author_matches(cited_first_author: str, record_authors: list[str]) -> bool:
    if not cited_first_author or not record_authors:
        return False

    cited_cjk = "".join(CJK_RE.findall(cited_first_author))
    cand_keys = candidate_author_keys(record_authors[0])

    if cited_cjk:
        return cited_cjk in cand_keys

    cited_norm = strip_accents(cited_first_author).lower()
    cited_clean = re.sub(r"[^a-z\-']", "", cited_norm)
    cited_last_word = strip_accents(cited_first_author).lower().split()[-1]
    cited_last_word = re.sub(r"[^a-z\-']", "", cited_last_word)

    for key in cand_keys:
        if CJK_RE.search(key):
            continue
        key_clean = re.sub(r"[^a-z\-']", "", key)
        if cited_clean == key_clean or cited_last_word == key_clean:
            return True
        # Handle hyphenated surnames where one source omits half, e.g., Garcia-Lopez
        if "-" in cited_clean and key_clean in cited_clean.split("-"):
            return True
        if "-" in key_clean and cited_clean in key_clean.split("-"):
            return True
    return False


def fetch_crossref_by_doi(
    client: PoliteHttpClient, doi: str
) -> tuple[CandidateRecord | None, str | None]:
    url = CROSSREF_WORKS_URL + urllib.parse.quote(doi, safe="")
    code, payload, err = client.get_json(url)
    if err:
        return None, err
    if code == 404 or not payload or "message" not in payload:
        return None, None

    msg = payload["message"]
    titles = msg.get("title") or []
    subtitles = msg.get("subtitle") or []
    main_title = titles[0].strip() if titles else ""
    if subtitles and subtitles[0].strip() and subtitles[0].strip().lower() not in main_title.lower():
        full_title = f"{main_title}: {subtitles[0].strip()}"
    else:
        full_title = main_title

    authors: list[str] = []
    for a in msg.get("author") or []:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        literal = (a.get("name") or "").strip()
        if family:
            authors.append(f"{family}, {given}".strip(", "))
        elif literal:
            authors.append(literal)

    year: int | None = None
    for date_key in ("published-print", "published-online", "issued"):
        parts = ((msg.get(date_key) or {}).get("date-parts") or [[None]])[0]
        if parts and isinstance(parts[0], int):
            year = parts[0]
            break

    containers = msg.get("container-title") or []
    rec_doi = (msg.get("DOI") or doi).lower()
    return (
        CandidateRecord(
            source="crossref",
            identifier=rec_doi,
            doi=rec_doi,
            title=full_title,
            authors=authors,
            year=year,
            venue=containers[0] if containers else None,
            cited_by_count=int(msg.get("is-referenced-by-count") or 0),
        ),
        None,
    )


def search_openalex_by_title(
    client: PoliteHttpClient, title: str, max_candidates: int = 10
) -> tuple[list[CandidateRecord], str | None]:
    params = urllib.parse.urlencode({"search": title})
    url = f"{OPENALEX_WORKS_URL}?{params}"
    code, payload, err = client.get_json(url)
    if err:
        return [], err
    if code == 404 or not payload:
        return [], None

    candidates: list[CandidateRecord] = []
    for item in (payload.get("results") or [])[:max_candidates]:
        cand_title = (item.get("display_name") or item.get("title") or "").strip()
        if not cand_title:
            continue
        authors = [
            (auth.get("author") or {}).get("display_name", "").strip()
            for auth in (item.get("authorships") or [])
            if (auth.get("author") or {}).get("display_name")
        ]
        raw_doi = item.get("doi")
        norm_doi = (
            raw_doi.replace("https://doi.org/", "").lower()
            if isinstance(raw_doi, str) and raw_doi
            else None
        )
        loc = item.get("primary_location") or {}
        src = loc.get("source") or {}
        candidates.append(
            CandidateRecord(
                source="openalex",
                identifier=str(item.get("id") or ""),
                doi=norm_doi,
                title=cand_title,
                authors=authors,
                year=item.get("publication_year"),
                venue=src.get("display_name"),
                cited_by_count=int(item.get("cited_by_count") or 0),
            )
        )
    return candidates, None


def compare_fields(
    parsed: ParsedReference,
    record: CandidateRecord,
    title_threshold: float,
    year_tolerance: int,
) -> tuple[float, list[str]]:
    # Compare against both full title and main title before subtitle colon if Crossref appended subtitle
    sim_full = compute_title_similarity(parsed.title, record.title)
    if ":" in record.title and ":" not in parsed.title:
        sim_main = compute_title_similarity(parsed.title, record.title.split(":", 1)[0])
        sim = max(sim_full, sim_main)
    else:
        sim = sim_full

    mismatches: list[str] = []
    if sim < title_threshold:
        mismatches.append("title")

    if parsed.year is not None and record.year is not None:
        if abs(parsed.year - record.year) > year_tolerance:
            mismatches.append("year")
    elif parsed.year is not None and record.year is None:
        mismatches.append("year")

    if parsed.first_author:
        if not first_author_matches(parsed.first_author, record.authors):
            mismatches.append("first_author")

    return sim, mismatches


def check_single_reference(
    parsed: ParsedReference,
    client: PoliteHttpClient,
    title_threshold: float = DEFAULT_TITLE_THRESHOLD,
    year_tolerance: int = DEFAULT_YEAR_TOLERANCE,
) -> CheckOutcome:
    if not parsed.title and not parsed.doi:
        return CheckOutcome(
            ref_id=parsed.ref_id,
            raw=parsed.raw,
            parsed_title=parsed.title,
            parsed_first_author=parsed.first_author,
            parsed_year=parsed.year,
            parsed_doi=parsed.doi,
            status="not_found",
            reason="Could not parse title or DOI from reference string.",
        )

    # Path 1: Reference includes a DOI -> query Crossref first.
    if parsed.doi:
        record, err = fetch_crossref_by_doi(client, parsed.doi)
        if err:
            return CheckOutcome(
                ref_id=parsed.ref_id,
                raw=parsed.raw,
                parsed_title=parsed.title,
                parsed_first_author=parsed.first_author,
                parsed_year=parsed.year,
                parsed_doi=parsed.doi,
                status="network_error",
                reason=f"Crossref lookup failed: {err}",
            )
        if record is None:
            # DOI does not resolve in Crossref; check OpenAlex by title to distinguish
            # a broken DOI on a real paper vs. a completely non-existent work.
            if parsed.title:
                candidates, oa_err = search_openalex_by_title(client, parsed.title)
                if oa_err:
                    return CheckOutcome(
                        ref_id=parsed.ref_id,
                        raw=parsed.raw,
                        parsed_title=parsed.title,
                        parsed_first_author=parsed.first_author,
                        parsed_year=parsed.year,
                        parsed_doi=parsed.doi,
                        status="network_error",
                        reason=f"OpenAlex fallback failed after Crossref 404: {oa_err}",
                    )
                if candidates:
                    best = max(
                        candidates,
                        key=lambda c: compute_title_similarity(parsed.title, c.title),
                    )
                    sim, field_mismatches = compare_fields(
                        parsed, best, title_threshold, year_tolerance
                    )
                    if sim >= title_threshold and not field_mismatches:
                        return CheckOutcome(
                            ref_id=parsed.ref_id,
                            raw=parsed.raw,
                            parsed_title=parsed.title,
                            parsed_first_author=parsed.first_author,
                            parsed_year=parsed.year,
                            parsed_doi=parsed.doi,
                            status="mismatch",
                            mismatched_fields=["doi"],
                            title_similarity=round(sim, 4),
                            matched_source=best.source,
                            matched_id=best.identifier,
                            matched_title=best.title,
                            matched_first_author=best.authors[0] if best.authors else None,
                            matched_year=best.year,
                            reason=(
                                f"DOI {parsed.doi} was not found in Crossref, but title/author/year "
                                f"match OpenAlex {best.identifier} (DOI: {best.doi or 'none'})."
                            ),
                        )
            return CheckOutcome(
                ref_id=parsed.ref_id,
                raw=parsed.raw,
                parsed_title=parsed.title,
                parsed_first_author=parsed.first_author,
                parsed_year=parsed.year,
                parsed_doi=parsed.doi,
                status="not_found",
                reason=f"DOI {parsed.doi} not found in Crossref and no matching work in OpenAlex.",
            )

        sim, mismatches = compare_fields(parsed, record, title_threshold, year_tolerance)
        if not mismatches:
            return CheckOutcome(
                ref_id=parsed.ref_id,
                raw=parsed.raw,
                parsed_title=parsed.title,
                parsed_first_author=parsed.first_author,
                parsed_year=parsed.year,
                parsed_doi=parsed.doi,
                status="verified",
                title_similarity=round(sim, 4),
                matched_source="crossref",
                matched_id=record.identifier,
                matched_title=record.title,
                matched_first_author=record.authors[0] if record.authors else None,
                matched_year=record.year,
                reason=f"DOI resolved in Crossref; title (sim={sim:.2f}), year, and first author match.",
            )
        return CheckOutcome(
            ref_id=parsed.ref_id,
            raw=parsed.raw,
            parsed_title=parsed.title,
            parsed_first_author=parsed.first_author,
            parsed_year=parsed.year,
            parsed_doi=parsed.doi,
            status="mismatch",
            mismatched_fields=mismatches,
            title_similarity=round(sim, 4),
            matched_source="crossref",
            matched_id=record.identifier,
            matched_title=record.title,
            matched_first_author=record.authors[0] if record.authors else None,
            matched_year=record.year,
            reason=(
                f"DOI {parsed.doi} resolved to '{record.title}' "
                f"({record.authors[0] if record.authors else 'unknown'}, {record.year}); "
                f"mismatch in: {', '.join(mismatches)} (title sim={sim:.2f})."
            ),
        )

    # Path 2: No DOI -> search OpenAlex by title and rank with difflib.
    candidates, err = search_openalex_by_title(client, parsed.title)
    if err:
        return CheckOutcome(
            ref_id=parsed.ref_id,
            raw=parsed.raw,
            parsed_title=parsed.title,
            parsed_first_author=parsed.first_author,
            parsed_year=parsed.year,
            parsed_doi=None,
            status="network_error",
            reason=f"OpenAlex search failed: {err}",
        )
    if not candidates:
        return CheckOutcome(
            ref_id=parsed.ref_id,
            raw=parsed.raw,
            parsed_title=parsed.title,
            parsed_first_author=parsed.first_author,
            parsed_year=parsed.year,
            parsed_doi=None,
            status="not_found",
            reason="OpenAlex returned 0 candidates for title search.",
        )

    def candidate_rank_key(cand: CandidateRecord) -> tuple[float, int, int, int]:
        sim_val = compute_title_similarity(parsed.title, cand.title)
        if ":" in cand.title and ":" not in parsed.title:
            sim_val = max(
                sim_val,
                compute_title_similarity(parsed.title, cand.title.split(":", 1)[0]),
            )
        auth_ok = int(first_author_matches(parsed.first_author, cand.authors))
        yr_ok = int(
            parsed.year is not None
            and cand.year is not None
            and abs(parsed.year - cand.year) <= year_tolerance
        )
        # Primary key is rounded difflib title similarity; ties (e.g. preprint vs journal
        # copy of the exact same title) prefer matching author/year and higher citation count.
        return (round(sim_val, 3), auth_ok, yr_ok, cand.cited_by_count)

    best = max(candidates, key=candidate_rank_key)
    sim, mismatches = compare_fields(parsed, best, title_threshold, year_tolerance)

    if sim < CANDIDATE_FLOOR:
        return CheckOutcome(
            ref_id=parsed.ref_id,
            raw=parsed.raw,
            parsed_title=parsed.title,
            parsed_first_author=parsed.first_author,
            parsed_year=parsed.year,
            parsed_doi=None,
            status="not_found",
            title_similarity=round(sim, 4),
            matched_source="openalex",
            matched_id=best.identifier,
            matched_title=best.title,
            matched_first_author=best.authors[0] if best.authors else None,
            matched_year=best.year,
            reason=f"Closest OpenAlex candidate has low title similarity ({sim:.2f} < {CANDIDATE_FLOOR:.2f}).",
        )

    # When title similarity is only moderate ([0.60, threshold)) AND neither first author
    # nor year matches, the candidate is an unrelated work sharing generic keywords rather
    # than a paraphrased version of the same paper.
    if "title" in mismatches and "first_author" in mismatches and "year" in mismatches:
        return CheckOutcome(
            ref_id=parsed.ref_id,
            raw=parsed.raw,
            parsed_title=parsed.title,
            parsed_first_author=parsed.first_author,
            parsed_year=parsed.year,
            parsed_doi=None,
            status="not_found",
            title_similarity=round(sim, 4),
            matched_source="openalex",
            matched_id=best.identifier,
            matched_title=best.title,
            matched_first_author=best.authors[0] if best.authors else None,
            matched_year=best.year,
            reason=(
                f"No matching work found; closest OpenAlex hit '{best.title}' "
                f"(sim={sim:.2f}) also differs in author and year."
            ),
        )

    if not mismatches:
        return CheckOutcome(
            ref_id=parsed.ref_id,
            raw=parsed.raw,
            parsed_title=parsed.title,
            parsed_first_author=parsed.first_author,
            parsed_year=parsed.year,
            parsed_doi=None,
            status="verified",
            title_similarity=round(sim, 4),
            matched_source="openalex",
            matched_id=best.identifier,
            matched_title=best.title,
            matched_first_author=best.authors[0] if best.authors else None,
            matched_year=best.year,
            reason=f"Matched OpenAlex {best.identifier}; title (sim={sim:.2f}), year, and first author agree.",
        )

    return CheckOutcome(
        ref_id=parsed.ref_id,
        raw=parsed.raw,
        parsed_title=parsed.title,
        parsed_first_author=parsed.first_author,
        parsed_year=parsed.year,
        parsed_doi=None,
        status="mismatch",
        mismatched_fields=mismatches,
        title_similarity=round(sim, 4),
        matched_source="openalex",
        matched_id=best.identifier,
        matched_title=best.title,
        matched_first_author=best.authors[0] if best.authors else None,
        matched_year=best.year,
        reason=(
            f"Closest OpenAlex candidate '{best.title}' "
            f"({best.authors[0] if best.authors else 'unknown'}, {best.year}); "
            f"mismatch in: {', '.join(mismatches)} (title sim={sim:.2f})."
        ),
    )


def load_inputs(
    input_path: Path, fmt: str = "auto"
) -> tuple[list[ParsedReference], list[dict[str, str]]]:
    actual_fmt = fmt
    if actual_fmt == "auto":
        actual_fmt = "csv" if input_path.suffix.lower() == ".csv" else "text"

    parsed_items: list[ParsedReference] = []
    raw_rows: list[dict[str, str]] = []

    if actual_fmt == "csv":
        with input_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                raw_rows.append(dict(row))
                ref_id = (row.get("id") or f"R{idx:02d}").strip()
                ref_str = (
                    row.get("reference")
                    or row.get("raw_reference")
                    or row.get("citation")
                    or row.get("text")
                    or ""
                ).strip()
                if ref_str:
                    parsed_items.append(parse_reference(ref_str, ref_id=ref_id))
                else:
                    year_str = (row.get("year") or "").strip()
                    parsed_items.append(
                        ParsedReference(
                            ref_id=ref_id,
                            raw=json.dumps(row, ensure_ascii=False),
                            title=(row.get("title") or "").strip(),
                            first_author=extract_first_author_key(row.get("authors") or row.get("first_author") or ""),
                            year=int(year_str) if year_str.isdigit() else None,
                            doi=clean_doi(row["doi"]) if row.get("doi") else None,
                        )
                    )
    else:
        lines = input_path.read_text(encoding="utf-8-sig").splitlines()
        merged: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            if (
                merged
                and line[:1].isspace()
                and not re.match(r"^\s*(?:\[\d+\]|\d{1,3}[.)])\s", line)
            ):
                merged[-1] += " " + line.strip()
            else:
                merged.append(line.strip())
        for idx, entry in enumerate(merged, start=1):
            ref_id = f"R{idx:02d}"
            parsed_items.append(parse_reference(entry, ref_id=ref_id))
            raw_rows.append({"id": ref_id, "reference": entry})

    return parsed_items, raw_rows


def print_evaluation(outcomes: list[CheckOutcome], rows: list[dict[str, str]]) -> None:
    if not rows or "label" not in rows[0]:
        return

    total = len(outcomes)
    correct = 0
    by_error_type: dict[str, dict[str, int]] = {}

    for outcome, row in zip(outcomes, rows):
        label = (row.get("label") or "").strip().lower()
        err_type = (row.get("error_type") or "none").strip()
        by_error_type.setdefault(
            err_type,
            {"total": 0, "verified": 0, "mismatch": 0, "not_found": 0, "network_error": 0, "correct": 0},
        )
        bucket = by_error_type[err_type]
        bucket["total"] += 1
        bucket[outcome.status] = bucket.get(outcome.status, 0) + 1

        is_real = label in ("valid", "real", "true", "1")
        pred_valid = outcome.status == "verified"
        if is_real == pred_valid and outcome.status != "network_error":
            correct += 1
            bucket["correct"] += 1

    print("\n=== Dataset Evaluation Summary ===")
    print(f"Binary Accuracy (valid -> verified vs. invalid -> mismatch/not_found): {correct}/{total} ({correct / total * 100:.1f}%)")
    print(f"{'error_type':<22} {'total':>5} {'verified':>9} {'mismatch':>9} {'not_found':>10} {'net_err':>8} {'acc':>7}")
    print("-" * 76)
    for etype, stats in by_error_type.items():
        acc = stats["correct"] / stats["total"] * 100 if stats["total"] else 0.0
        print(
            f"{etype:<22} {stats['total']:>5} {stats['verified']:>9} "
            f"{stats['mismatch']:>9} {stats['not_found']:>10} {stats['network_error']:>8} {acc:>6.1f}%"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check academic references with or without DOIs via Crossref and OpenAlex."
    )
    parser.add_argument("input", type=Path, help="Input CSV file or plain-text reference list.")
    parser.add_argument(
        "--format",
        choices=["auto", "csv", "text"],
        default="auto",
        help="Input format (default: auto-detect from file extension).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="Minimum delay in seconds between HTTP requests (clamped to >= 1.0).",
    )
    parser.add_argument(
        "--title-threshold",
        type=float,
        default=DEFAULT_TITLE_THRESHOLD,
        help="Minimum difflib title similarity for a verified title match (default: 0.85).",
    )
    parser.add_argument(
        "--year-tolerance",
        type=int,
        default=DEFAULT_YEAR_TOLERANCE,
        help="Allowed publication year difference before flagging year mismatch (default: 1).",
    )
    parser.add_argument("--output-json", type=Path, help="Optional path to write full JSON results.")
    parser.add_argument("--output-csv", type=Path, help="Optional path to write CSV results.")
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="If input CSV contains `label` and `error_type`, print accuracy & confusion breakdown.",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 2

    parsed_refs, raw_rows = load_inputs(args.input, fmt=args.format)
    client = PoliteHttpClient(min_interval=max(MIN_ALLOWED_INTERVAL, args.interval))

    outcomes: list[CheckOutcome] = []
    counts = {"verified": 0, "mismatch": 0, "not_found": 0, "network_error": 0}

    for item in parsed_refs:
        outcome = check_single_reference(
            item,
            client=client,
            title_threshold=args.title_threshold,
            year_tolerance=args.year_tolerance,
        )
        outcomes.append(outcome)
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        mismatch_detail = (
            f" ({', '.join(outcome.mismatched_fields)})" if outcome.mismatched_fields else ""
        )
        print(
            f"[{outcome.ref_id}] {outcome.status}{mismatch_detail} | "
            f"doi={outcome.parsed_doi or '-'} | sim={outcome.title_similarity if outcome.title_similarity is not None else '-'} | "
            f"{outcome.reason}"
        )

    print("\n=== Verdict Counts ===")
    print(
        f"Total: {len(outcomes)} | verified: {counts['verified']} | "
        f"mismatch: {counts['mismatch']} | not_found: {counts['not_found']} | "
        f"network_error: {counts['network_error']}"
    )

    if args.evaluate:
        print_evaluation(outcomes, raw_rows)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps([asdict(o) for o in outcomes], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.output_csv:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "ref_id",
            "status",
            "mismatched_fields",
            "title_similarity",
            "parsed_doi",
            "parsed_year",
            "parsed_first_author",
            "parsed_title",
            "matched_source",
            "matched_id",
            "matched_year",
            "matched_first_author",
            "matched_title",
            "reason",
        ]
        with args.output_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for o in outcomes:
                d = asdict(o)
                d["mismatched_fields"] = ";".join(o.mismatched_fields)
                writer.writerow({k: d[k] for k in fieldnames})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
