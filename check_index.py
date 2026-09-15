"""Inspect what actually got stored for a ticker.

Answers two questions:
  - Did Item 1A / Item 7 / Item 8 make it into the index at all?
  - Is the "% of the section read" figure real, or a constant?

    python check_index.py MSFT
    python check_index.py MSFT JPM V
"""

import sys

from analyzer import MAX_CONTEXT_CHARS, _pull
from vectorstore import (
    chunk_total,
    chunks_per_item,
    is_indexed,
    open_collection,
    stored_filing,
)

# Mirrors the four report sections and the items each one reads.
REPORT_SECTIONS = [
    ("Business", ("Item 1",)),
    ("Risks", ("Item 1A",)),
    ("Financials", ("Item 7", "Item 8")),
    ("Tone", ("Item 7",)),
]


def check(ticker: str) -> None:
    print(f"\n{'=' * 66}")
    print(ticker)
    print("=" * 66)

    if not is_indexed(ticker):
        print("  NOT INDEXED - analyze it in the app first.")
        return

    print(f"  chunks stored : {chunk_total(ticker):,}")
    print(f"  filing meta   : {stored_filing(ticker)}")

    tally = chunks_per_item(ticker)
    print("\n  chunks per item:")
    for item in sorted(tally, key=lambda s: (len(s), s)):
        print(f"    {item:<18} {tally[item]:>5}")

    for key in ("Item 1", "Item 1A", "Item 7", "Item 8"):
        if key not in tally:
            print(f"    >>> {key} IS MISSING from the index")

    store = open_collection(ticker)
    print("\n  coverage math per report section:")
    for label, items in REPORT_SECTIONS:
        _body, used, source = _pull(store, items)
        pct = (used / source * 100) if source else 0.0
        share = MAX_CONTEXT_CHARS // len(items)
        capped = "  <- hit the char cap" if used >= share * len(items) - 5 else ""
        print(f"    {label:<11} {'+'.join(items):<16} "
              f"used {used:>7,} / source {source:>8,} = {pct:5.1f}%{capped}")


if __name__ == "__main__":
    for ticker in sys.argv[1:] or ["MSFT"]:
        check(ticker.strip().upper())