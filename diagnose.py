"""Show where each item's span stops, and what header ended it.

Use this on a ticker that came back THIN or MISSING in test_parsing.py:

    python diagnose.py CAT
    python diagnose.py JPM
"""

import sys

from downloader import fetch_latest_10k
from processor import (
    ITEM_HEADER_RE,
    flatten_html,
    parse_check,
    segment_by_item,
    _tag,
    _looks_like_heading,
)

KEY_ITEMS = ("Item 1", "Item 1A", "Item 7", "Item 8")


def show(ticker: str) -> None:
    filing = fetch_latest_10k(ticker)
    text = flatten_html(filing.path)
    segments = segment_by_item(text)
    result = parse_check(segments)

    print(f"\n{'=' * 70}")
    print(f"{ticker}  FY{filing.year}  {len(text):,} chars  {result['sections']} sections")
    print(f"{'=' * 70}")

    # Every header the regex matched, and whether title validation accepted it.
    all_hits = list(ITEM_HEADER_RE.finditer(text))
    titled = [m for m in all_hits if _looks_like_heading(text, m, _tag(m))]
    print(f"regex matches: {len(all_hits)}   passed title check: {len(titled)}")

    print("\nKey items:")
    for item in KEY_ITEMS:
        span = segments.get(item)
        if not span:
            print(f"  {item:<8} NOT FOUND")
            continue
        flag = "  <-- suspiciously short" if len(span) < 3000 else ""
        print(f"  {item:<8} {len(span):>8,} chars{flag}")
        print(f"           starts: {span[:90]!r}")
        print(f"           ends:   {span[-90:]!r}")

    # What header immediately follows each key item's span? That is what cut it.
    print("\nWhat ended each key section:")
    for item in KEY_ITEMS:
        span = segments.get(item)
        if not span:
            continue
        end = text.find(span) + len(span)
        nxt = ITEM_HEADER_RE.search(text, end - 1)
        if nxt:
            print(f"  {item:<8} -> {text[nxt.start(): nxt.start() + 70]!r}")
        else:
            print(f"  {item:<8} -> end of document")

    # Incorporation by reference is common for Items 7 and 8 at large banks.
    lowered = text.lower()
    for phrase in ("incorporated by reference", "incorporated herein by reference"):
        if phrase in lowered:
            spot = lowered.find(phrase)
            print(f"\nNote: found {phrase!r} at char {spot:,}")
            print(f"      context: {text[spot - 120: spot + 80]!r}")
            break


if __name__ == "__main__":
    for ticker in sys.argv[1:] or ["CAT"]:
        show(ticker)