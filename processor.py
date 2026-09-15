import re
from pathlib import Path

from bs4 import BeautifulSoup
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Reg S-K fixes both the item numbers and their titles, so I can check the
# title as well as the number. Cuts out most false matches.
ITEM_TITLES = {
    "1": ("business",),
    "1A": ("risk factor",),
    "1B": ("unresolved staff comment",),
    "1C": ("cybersecurity",),
    "2": ("propert",),
    "3": ("legal proceeding",),
    "4": ("mine safety", "submission of matters"),
    "5": ("market for", "market information"),
    "6": ("reserved", "selected financial", "selected consolidated"),
    "7": ("management's discussion", "management s discussion", "managements discussion"),
    "7A": ("quantitative and qualitative", "market risk"),
    "8": ("financial statements",),
    "9": ("changes in and disagreements", "disagreements with accountants"),
    "9A": ("controls and procedures",),
    "9B": ("other information",),
    "9C": ("foreign jurisdiction",),
    "10": ("directors", "corporate governance"),
    "11": ("executive compensation",),
    "12": ("security ownership", "beneficial owner"),
    "13": ("certain relationships", "related transaction", "director independence"),
    "14": ("principal account", "accountant fees"),
    "15": ("exhibit", "financial statement schedule"),
    "16": ("form 10-k summary", "10-k summary"),
}

# Trailing punctuation is optional. Plenty of filers write "ITEM 1A" with
# nothing after it, and requiring the period made me miss those filings.
ITEM_HEADER_RE = re.compile(
    r"\bItems?\s+(\d{1,2})\s?([A-C])?\b\s*[\.\:\)\-\u2013\u2014]?\s*",
    re.IGNORECASE,
)

TITLE_WINDOW = 120   # how far past the number to look for the title
MIN_SECTIONS = 3
MIN_BODY = 3000      # below this, a slice is a stub (TOC / "refer to" / index)

KEY_ITEMS = ("Item 1", "Item 1A", "Item 7", "Item 8")

# Some filers print a section under its statutory title without repeating
# "Item N" (JPMorgan's MD&A is the usual case). Only recover titles that are
# distinctive — "business" and "risk factors" appear as running text too often.
RECOVERABLE_TITLES = {
    "Item 7": re.compile(
        r"management['’` ]?s?\s*discussion\s*and\s*analysis",
        re.IGNORECASE,
    ),
}

# Banks that drop "Item N" still keep the statutory heading (Citi: "RISK FACTORS
# The following..."; Wells annual report: "Financial Review Overview...").
STATUTORY_PATTERNS = {
    "Item 1": re.compile(r"\bOVERVIEW\b", re.IGNORECASE),
    "Item 1A": re.compile(r"\bRISK\s+FACTORS\b", re.IGNORECASE),
    "Item 7": re.compile(
        r"(?:MANAGEMENT['’`]?S?\s+DISCUSSION\s+AND\s+ANALYSIS"
        r"|FINANCIAL\s+REVIEW)\b",
        re.IGNORECASE,
    ),
    "Item 8": re.compile(
        r"(?:CONSOLIDATED\s+FINANCIAL\s+STATEMENTS"
        r"|REPORT\s+OF\s+INDEPENDENT\s+REGISTERED\s+PUBLIC\s+ACCOUNTING\s+FIRM)\b",
        re.IGNORECASE,
    ),
}

EXHIBIT_TYPE_RE = re.compile(r"^(EX-13|EX-99)(\b|[.\-])", re.IGNORECASE)
EXHIBIT_HTML_RE = re.compile(r"\.(htm|html)$", re.IGNORECASE)
MIN_EXHIBIT_CHARS = 50_000


def flatten_markup(raw: str) -> str:
    """HTML (or HTML wrapped in SGML) -> one long line of plain text."""
    soup = BeautifulSoup(raw, "html.parser")

    # Inline XBRL hides a second copy of a lot of facts. Left in, they turn up
    # mid-sentence and throw off the item matching.
    for tag in soup(["script", "style", "ix:header", "ix:hidden"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()

    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip()


def flatten_html(filepath) -> str:
    raw = Path(filepath).read_text(encoding="utf-8", errors="ignore")
    return flatten_markup(raw)


def _tag(match) -> str:
    return f"Item {match.group(1)}{(match.group(2) or '').upper()}"


def _looks_like_heading(text, match, tag) -> bool:
    """Check the item's real title shows up right after the number.

    Filers style headings with letter-spacing, so the extracted text can read
    "RIS K FACTORS" or "B USINESS" with spaces wedged inside words. Matching the
    despaced window as well keeps those genuine headers from being missed.
    """
    expected = ITEM_TITLES.get(tag.removeprefix("Item "))
    if not expected:
        return False

    window = text[match.end(): match.end() + TITLE_WINDOW].lower()
    window = re.sub(r"[^a-z0-9\s'-]", " ", window)
    squished = window.replace(" ", "")
    return any(
        phrase in window or phrase.replace(" ", "") in squished for phrase in expected
    )


def _after_title(text, match, tag) -> str:
    expected = ITEM_TITLES.get(tag.removeprefix("Item "))
    if not expected:
        return text[match.end(): match.end() + 80]
    window = text[match.end(): match.end() + 160]
    lowered = re.sub(r"[^a-z0-9\s'-]", " ", window.lower())
    for phrase in expected:
        pos = lowered.find(phrase)
        if pos >= 0:
            return window[pos + len(phrase): pos + len(phrase) + 80]
    return window


def _is_crossref(text, match, tag) -> bool:
    """True when the title is followed by a pointer, not the section body."""
    after = _after_title(text, match, tag)
    return bool(re.search(
        r"\b(on page|on pages|of this form|in this form|above|below|herein|hereof)\b"
        r"|\bin\b.{0,50}form\s*10-k",
        after,
        re.I,
    ))


def _looks_like_section_open(text, match, tag) -> bool:
    after = _after_title(text, match, tag)
    return bool(re.match(
        r"\s*s?[\.\"]?\s*(The following|The statements|In addition|We face|We |Our |This |An investment)",
        after,
        re.I,
    ))


def _pick_starts(hits, text) -> dict[str, int]:
    """Choose one real start per item: the occurrence with the most text after it.

    A 10-K lists every item once in the table of contents and often again as an
    in-body cross-reference ("refer to Part II, Item 7 ..."). Both are trailed
    almost immediately by the next header, so they score a tiny gap. The genuine
    section is the occurrence with real content before the next header, so per
    item we keep the start with the largest following gap.

    Exception: a late cross-reference near EOF can beat a real section on gap
    size. If the max-gap winner is a cross-ref and an earlier occurrence already
    has a real body, keep the earlier one.
    """
    starts = [m.start() for m in hits]
    cands: dict[str, list[tuple[int, int, object]]] = {}
    for i, match in enumerate(hits):
        tag = _tag(match)
        nxt = starts[i + 1] if i + 1 < len(starts) else len(text)
        cands.setdefault(tag, []).append((nxt - match.start(), match.start(), match))

    chosen: dict[str, int] = {}
    for tag, opts in cands.items():
        winner = max(opts, key=lambda o: o[0])
        if _is_crossref(text, winner[2], tag):
            earlier = [
                o for o in opts
                if o[1] < winner[1]
                and o[0] >= MIN_BODY
                and not _is_crossref(text, o[2], tag)
                and _looks_like_section_open(text, o[2], tag)
            ]
            if earlier:
                winner = min(earlier, key=lambda o: o[1])
        chosen[tag] = winner[1]
    return chosen


def _item_rank(tag: str) -> tuple[int, str]:
    match = re.match(r"Item\s+(\d+)([A-C])?", tag, re.IGNORECASE)
    if not match:
        return (99, "Z")
    return (int(match.group(1)), match.group(2) or "")


def _owner_of(chosen: list[tuple[int, str]], pos: int, end: int) -> str | None:
    for start, tag in chosen:
        stop = next((s for s, _ in chosen if s > start), end)
        if start <= pos < stop:
            return tag
    return None


def _recover_untitled(chosen: list[tuple[int, str]], text: str) -> list[tuple[int, str]]:
    """If a key item is only a stub, look for its statutory title in the body.

    Will not steal text from an earlier, already-substantial key item (so a
    mention of "MD&A" inside Item 1 never becomes a fake Item 7). It will
    split a later item that swallowed the untitled section (Item 8 sitting
    on top of JPMorgan's MD&A).
    """
    chosen = list(chosen)

    def span(tag: str) -> tuple[int, int] | None:
        for i, (start, name) in enumerate(chosen):
            if name == tag:
                stop = chosen[i + 1][0] if i + 1 < len(chosen) else len(text)
                return start, stop
        return None

    for tag, pattern in RECOVERABLE_TITLES.items():
        current = span(tag)
        if current and current[1] - current[0] >= MIN_BODY:
            continue

        best: int | None = None
        for match in pattern.finditer(text):
            pos = match.start()
            nxt = next((start for start, _ in chosen if start > pos), len(text))
            if nxt - pos < MIN_BODY:
                continue
            owner = _owner_of(chosen, pos, len(text))
            if owner and owner != tag:
                held = span(owner)
                if (
                    held
                    and held[1] - held[0] >= MIN_BODY
                    and _item_rank(owner) < _item_rank(tag)
                ):
                    continue
            if best is None or pos < best:
                best = pos

        if best is not None:
            chosen = [(start, name) for start, name in chosen if name != tag]
            chosen.append((best, tag))
            chosen.sort()

    return chosen


def _slice(chosen: list[tuple[int, str]], text: str) -> dict[str, str]:
    segments: dict[str, str] = {}
    for pos, (start, tag) in enumerate(chosen):
        stop = chosen[pos + 1][0] if pos + 1 < len(chosen) else len(text)
        body = text[start:stop].strip()
        if body:
            segments[tag] = body
    return segments


def _key_quality(segments: dict[str, str]) -> int:
    if not segments or "Full Document" in segments:
        return 0
    return sum(1 for k in KEY_ITEMS if len(segments.get(k, "")) >= MIN_BODY)


def _looks_like_title_start(text: str, after: int) -> bool:
    """Reject TOC lines ('RISK FACTORS 49') and mid-sentence mentions."""
    rest = text[after: after + 140]
    rest = re.sub(
        r"^\s*(of\s+financial\s+condition(?:\s+and\s+results\s+of\s+operations)?)\s*",
        " ",
        rest,
        flags=re.I,
    ).lstrip()
    return bool(rest) and rest[0].isalpha() and rest[0].isupper()


def _segment_item_headers(text: str) -> dict[str, str]:
    all_hits = list(ITEM_HEADER_RE.finditer(text))
    if not all_hits:
        return {}

    titled = [m for m in all_hits if _looks_like_heading(text, m, _tag(m))]
    hits = titled if len(titled) >= MIN_SECTIONS else all_hits
    chosen = sorted((start, tag) for tag, start in _pick_starts(hits, text).items())
    chosen = _recover_untitled(chosen, text)
    segments = _slice(chosen, text)
    return segments if len(segments) >= MIN_SECTIONS else {}


def _segment_statutory(text: str) -> dict[str, str]:
    """Cut on statutory titles when the filer never writes 'Item 7'."""
    hits: list[tuple[int, str]] = []
    for tag, pattern in STATUTORY_PATTERNS.items():
        for match in pattern.finditer(text):
            if tag == "Item 1" and "financial review" in text[max(0, match.start() - 40): match.start()].lower():
                continue
            if not _looks_like_title_start(text, match.end()):
                continue
            hits.append((match.start(), tag))
    if not hits:
        return {}

    hits.sort()
    starts = [pos for pos, _ in hits]
    cands: dict[str, list[tuple[int, int]]] = {}
    for i, (pos, tag) in enumerate(hits):
        nxt = starts[i + 1] if i + 1 < len(starts) else len(text)
        cands.setdefault(tag, []).append((nxt - pos, pos))

    # First substantial hit per title. Max-gap here would prefer a later
    # "OVERVIEW This section..." inside the MD&A over the real opening.
    chosen: dict[str, int] = {}
    for tag, opts in cands.items():
        fat = [o for o in opts if o[0] >= MIN_BODY]
        chosen[tag] = min(fat, key=lambda o: o[1])[1] if fat else max(opts, key=lambda o: o[0])[1]

    segments = _slice(sorted((start, tag) for tag, start in chosen.items()), text)
    return segments if _key_quality(segments) >= 2 else {}


def segment_by_item(text: str) -> dict[str, str]:
    """Split a filing into {"Item 1A": "...", ...}.

    Tries Regulation S-K 'Item N' headers first. If that cannot recover at
    least three substantial key items, falls back to statutory titles
    (OVERVIEW / RISK FACTORS / MD&A / financial statements) used by filers
    that drop the word Item.
    """
    header = _segment_item_headers(text)
    titled = _segment_statutory(text)
    header_q = _key_quality(header)
    titled_q = _key_quality(titled)
    header_keys = sum(1 for k in KEY_ITEMS if header.get(k))

    # Statutory titles only win when they clearly recover more real key items.
    # Otherwise a conventional 10-K (Item 1. Business ...) stays on headers,
    # even if a couple of those items are short.
    if titled_q >= 3 and titled_q > header_q:
        return titled
    if header_keys >= 3 and header:
        return header
    if titled_q > header_q:
        return titled
    if header:
        return header
    if titled:
        return titled
    return {"Full Document": text}


def parse_check(segments: dict[str, str]) -> dict:
    """What the parser actually got. Used by the UI and by test_parsing.py."""
    found = [item for item in KEY_ITEMS if segments.get(item)]
    missing = [item for item in KEY_ITEMS if item not in found]
    return {
        "sections": len(segments),
        "found": found,
        "missing": missing,
        "fell_back": "Full Document" in segments,
        "ok": not missing and "Full Document" not in segments,
        "sizes": {k: len(v) for k, v in sorted(segments.items())},
    }


def to_chunks(
    segments: dict[str, str],
    symbol: str | None = None,
    size: int = 1000,
    overlap: int = 100,
) -> list[Document]:
    # cl100k_base is what text-embedding-3-small uses, so chunk sizes here
    # match what the embedding model actually sees.
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=size,
        chunk_overlap=overlap,
    )

    docs = []
    for item, body in segments.items():
        for pos, piece in enumerate(splitter.split_text(body)):
            meta: dict[str, str | int] = {"section": item, "chunk_index": pos}
            if symbol:
                meta["ticker"] = symbol.strip().upper()
            docs.append(Document(page_content=piece, metadata=meta))
    return docs


def _merge_longer(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    """Keep whichever copy of each item is longer. Extra never overwrites Full Document."""
    if "Full Document" in extra:
        extra = {k: v for k, v in extra.items() if k != "Full Document"}
    out = dict(base)
    if "Full Document" in out and extra:
        out.pop("Full Document", None)
    for tag, body in extra.items():
        if len(body) > len(out.get(tag, "")):
            out[tag] = body
    return out


def _exhibit_texts(filepath) -> list[str]:
    """Flatten annual-report-like exhibits sitting next to this 10-K."""
    submission = Path(filepath).parent / "full-submission.txt"
    if not submission.exists():
        return []

    raw = submission.read_text(encoding="utf-8", errors="ignore")
    texts = []
    for block in raw.split("<DOCUMENT>")[1:]:
        kind = re.search(r"<TYPE>(.*)", block)
        if not kind or not EXHIBIT_TYPE_RE.match(kind.group(1).strip()):
            continue
        name = re.search(r"<FILENAME>(.*)", block)
        if not name or not EXHIBIT_HTML_RE.search(name.group(1).strip()):
            continue
        payload = re.search(r"<TEXT>(.*?)</TEXT>", block, re.DOTALL)
        if not payload or len(payload.group(1)) < MIN_EXHIBIT_CHARS:
            continue
        flat = flatten_markup(payload.group(1))
        if len(flat) >= MIN_BODY:
            texts.append(flat)
    return texts


def prepare_filing(
    filepath,
    symbol: str | None = None,
    size: int = 1000,
    overlap: int = 100,
) -> list[Document]:
    segments = segment_by_item(flatten_html(filepath))
    if _key_quality(segments) < len(KEY_ITEMS):
        for exhibit in _exhibit_texts(filepath):
            segments = _merge_longer(segments, segment_by_item(exhibit))
            if _key_quality(segments) >= len(KEY_ITEMS):
                break
    if not segments:
        raise ValueError("No text could be extracted from the filing.")
    return to_chunks(segments, symbol, size, overlap)


if __name__ == "__main__":
    matches = sorted(Path("sec_filings").glob("**/primary-document.html"))
    if not matches:
        raise SystemExit("No filing found. Run downloader.py first.")

    filing = matches[-1]
    print(f"Processing: {filing}\n")

    body = flatten_html(filing)
    print(f"Clean text: {len(body):,} characters")

    report = parse_check(segment_by_item(body))
    print(f"\n{report['sections']} sections detected:")
    for item, chars in report["sizes"].items():
        print(f"  {item:<10} {chars:>9,} chars")

    print(f"\nKey items found:   {', '.join(report['found']) or 'none'}")
    if report["missing"]:
        print(f"Key items MISSING: {', '.join(report['missing'])}")