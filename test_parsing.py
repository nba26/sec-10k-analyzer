"""Check item segmentation against real filings from different kinds of filer.

Run this before a demo. It downloads each ticker's latest 10-K but does no
embedding and makes no OpenAI calls, so it costs nothing.

    python test_parsing.py
    python test_parsing.py KO CAT JPM
"""

import sys
import time

from downloader import fetch_latest_10k
from processor import flatten_html, parse_check, segment_by_item

# Banks, industrials and REITs lay out their filings very differently from
# the big tech names every tutorial tests against.
DEFAULT_TICKERS = [
    "AAPL",  # clean baseline
    "KO",    # heavy tables
    "CAT",   # industrial, long Item 1
    "JPM",   # bank, untitled MD&A recovered by statutory title
    "GS",    # bank, conventional Item 7 header
    "BAC",   # bank, conventional Item 7 header
    "C",     # bank, almost no 'Item N' labels in the primary HTML
    "WFC",   # bank, Items 1A/7/8 live in Exhibit 13 (annual report)
    "WMT",   # retailer
    "XOM",   # energy
    "PLD",   # REIT
    "BRK-B", # holding company, notoriously plain formatting
]

KEY_ITEMS = ("Item 1", "Item 1A", "Item 7", "Item 8")


def check(ticker: str) -> dict:
    filing = fetch_latest_10k(ticker)
    text = flatten_html(filing.path)
    segments = segment_by_item(text)
    found = parse_check(segments)
    found.update(ticker=ticker, year=filing.year, chars=len(text))
    return found


def main(tickers: list[str]) -> int:
    print(f"{'ticker':<8} {'year':<6} {'chars':>10} {'items':>6}  status")
    print("-" * 72)

    failures = []
    for ticker in tickers:
        try:
            result = check(ticker)
        except Exception as exc:
            print(f"{ticker:<8} {'—':<6} {'—':>10} {'—':>6}  ERROR {type(exc).__name__}: {exc}")
            failures.append(ticker)
            time.sleep(0.5)
            continue

        if result["fell_back"]:
            status = "FELL BACK to Full Document"
            failures.append(ticker)
        elif result["missing"]:
            status = f"MISSING {', '.join(result['missing'])}"
            failures.append(ticker)
        else:
            sizes = {k: result["sizes"].get(k, 0) for k in KEY_ITEMS}
            thin = [k for k, v in sizes.items() if v < 3000]
            if thin:
                status = f"THIN: {', '.join(thin)} under 3k chars"
                failures.append(ticker)
            else:
                status = "ok"

        print(f"{result['ticker']:<8} {str(result['year']):<6} {result['chars']:>10,} "
              f"{result['sections']:>6}  {status}")
        time.sleep(0.5)  # EDGAR rate limit

    print("-" * 72)
    print(f"{len(tickers) - len(failures)}/{len(tickers)} parsed cleanly")
    if failures:
        print(f"Needs attention: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or DEFAULT_TICKERS))