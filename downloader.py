import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv
from sec_edgar_downloader import Downloader

load_dotenv()

MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds; multiplied by the attempt number each retry

# EDGAR wants a real name and email on every request. Fake ones get you
# rate-limited, which I hit once while testing.
FILER_NAME = os.getenv("SEC_COMPANY_NAME", "").strip()
FILER_EMAIL = os.getenv("SEC_EMAIL", "").strip()

FILINGS_DIR = "sec_filings"
TICKER_INDEX_URL = "https://www.sec.gov/files/company_tickers.json"
ACCESSION_RE = re.compile(r"(\d{10})-(\d{2})-(\d{6})")


class EdgarSetupError(RuntimeError):
    pass


def _contact() -> tuple[str, str]:
    if not FILER_NAME or not FILER_EMAIL:
        raise EdgarSetupError(
            "SEC_COMPANY_NAME and SEC_EMAIL must be set in .env. "
            "EDGAR requires a real contact on every request."
        )
    if "example.com" in FILER_EMAIL or "@" not in FILER_EMAIL:
        raise EdgarSetupError(f"SEC_EMAIL is not a usable address: {FILER_EMAIL!r}.")
    return FILER_NAME, FILER_EMAIL


def agent_string() -> str:
    name, email = _contact()
    return f"{name} {email}"


@dataclass(frozen=True)
class Filing:
    path: Path
    accession: str
    year: int | None


def load_company_index() -> list[dict]:
    """Every EDGAR filer that has a ticker, sorted by name."""
    resp = requests.get(
        TICKER_INDEX_URL,
        headers={"User-Agent": agent_string()},
        timeout=30,
    )
    resp.raise_for_status()

    companies = [
        {
            "cik": str(row["cik_str"]).zfill(10),
            "ticker": row["ticker"],
            "title": row["title"],
        }
        for row in resp.json().values()
        if row.get("ticker")
    ]
    companies.sort(key=lambda c: c["title"])
    return companies


def fetch_latest_10k(symbol: str, dest: str = FILINGS_DIR) -> Filing:
    symbol = symbol.strip().upper()
    name, email = _contact()

    # Network hiccups and EDGAR rate limits are transient, so retry with a
    # growing backoff. Whether a filing actually arrived is decided by the disk,
    # not the download count (the library returns 0 for already-cached filings).
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            Downloader(name, email, dest).get(
                "10-K", symbol, limit=1, download_details=True
            )
        except Exception as exc:  # connection error, rate limit, etc.
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
                continue
            raise EdgarSetupError(
                f"Couldn't reach EDGAR for {symbol} after {MAX_RETRIES} attempts. "
                f"Last error: {exc}"
            ) from exc

        if _has_download(symbol, dest):
            return _newest_download(symbol, dest)

        # Nothing on disk: could be a transient empty response, so retry;
        # if it stays empty, the company likely just doesn't file a 10-K.
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * attempt)

    raise FileNotFoundError(
        f"EDGAR has no 10-K on file for {symbol}. The ticker may point to a newly "
        f"registered entity that hasn't filed yet, a foreign issuer that files a "
        f"20-F instead, or the ticker/CIK may be wrong."
    )


def _has_download(symbol: str, dest: str) -> bool:
    base = Path(dest) / "sec-edgar-filings" / symbol / "10-K"
    return base.exists() and any(d.is_dir() for d in base.iterdir())


def _newest_download(symbol: str, dest: str) -> Filing:
    base = Path(dest) / "sec-edgar-filings" / symbol / "10-K"
    if not base.exists():
        raise FileNotFoundError(
            f"Nothing downloaded for {symbol}. Either the ticker is wrong, or the "
            f"company files a 20-F instead (foreign issuers do)."
        )

    # Accession folders happen to sort chronologically, but mtime is what
    # actually tells me which download is newest.
    folders = sorted(
        (d for d in base.iterdir() if d.is_dir()),
        key=lambda d: (d.stat().st_mtime, d.name),
    )
    if not folders:
        raise FileNotFoundError(f"Filings folder for {symbol} is empty: {base}")

    newest = folders[-1]
    doc = newest / "primary-document.html"
    if not doc.exists():
        doc = newest / "full-submission.txt"
    if not doc.exists():
        raise FileNotFoundError(f"No readable document inside {newest}")

    return Filing(path=doc, accession=newest.name, year=_year_of(newest.name))


def _year_of(accession: str) -> int | None:
    """0000320193-24-000123 -> 2024"""
    match = ACCESSION_RE.search(accession)
    if not match:
        return None
    yy = int(match.group(2))
    return 2000 + yy if yy < 80 else 1900 + yy


if __name__ == "__main__":
    symbol = "AAPL"
    print(f"Downloading the most recent 10-K for {symbol} ...")
    filing = fetch_latest_10k(symbol)
    print(f"  file:      {filing.path}")
    print(f"  accession: {filing.accession}")
    print(f"  year:      {filing.year}")