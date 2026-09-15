import os
from collections import Counter
from functools import lru_cache

import chromadb
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

load_dotenv()

VECTOR_DB_DIR = "chroma_db"
EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 256

# Bump when the parser or chunking changes so old collections rebuild instead
# of serving vectors that no longer match how the app reads them.
INDEX_VERSION = 4


class MissingAPIKey(RuntimeError):
    pass


@lru_cache(maxsize=1)
def make_embedder() -> OpenAIEmbeddings:
    if not os.getenv("OPENAI_API_KEY"):
        raise MissingAPIKey("OPENAI_API_KEY is not set. Add it to your .env file.")
    return OpenAIEmbeddings(model=EMBED_MODEL)


def _collection_for(symbol: str) -> str:
    # Prefix keeps the name inside Chroma's 3-63 char rule, which single-letter
    # tickers like "F" would otherwise break.
    return f"filing_{symbol.strip().upper()}"


def _db(db_dir: str):
    return chromadb.PersistentClient(path=db_dir)


def open_collection(symbol: str, db_dir: str = VECTOR_DB_DIR) -> Chroma:
    return Chroma(
        collection_name=_collection_for(symbol),
        embedding_function=make_embedder(),
        persist_directory=db_dir,
    )


def is_indexed(symbol: str, db_dir: str = VECTOR_DB_DIR) -> bool:
    """Does this ticker already have vectors on disk?

    Goes through the raw chroma client on purpose. LangChain's Chroma wrapper
    is get-or-create, so the old version of this left an empty collection
    behind for every ticker I merely asked about.
    """
    if not os.path.isdir(db_dir):
        return False
    try:
        return _db(db_dir).get_collection(_collection_for(symbol)).count() > 0
    except Exception:
        return False


def chunk_total(symbol: str, db_dir: str = VECTOR_DB_DIR) -> int:
    if not os.path.isdir(db_dir):
        return 0
    try:
        return _db(db_dir).get_collection(_collection_for(symbol)).count()
    except Exception:
        return 0


def stored_filing(symbol: str, db_dir: str = VECTOR_DB_DIR) -> dict:
    """Which filing is sitting in this collection."""
    if not is_indexed(symbol, db_dir):
        return {}
    try:
        sample = _db(db_dir).get_collection(_collection_for(symbol)).get(
            limit=1, include=["metadatas"]
        )
        meta = (sample.get("metadatas") or [{}])[0] or {}
        return {
            "accession": meta.get("accession", ""),
            "year": meta.get("year", ""),
            "version": meta.get("version", 0),
        }
    except Exception:
        return {}


def needs_reindex(symbol: str, db_dir: str = VECTOR_DB_DIR) -> bool:
    """True if the ticker isn't indexed yet, or was built by an older parser."""
    if not is_indexed(symbol, db_dir):
        return True
    return stored_filing(symbol, db_dir).get("version", 0) != INDEX_VERSION


def chunks_per_item(symbol: str, db_dir: str = VECTOR_DB_DIR) -> dict[str, int]:
    if not is_indexed(symbol, db_dir):
        return {}
    try:
        result = _db(db_dir).get_collection(_collection_for(symbol)).get(
            include=["metadatas"]
        )
        metas = result.get("metadatas") or []
        return dict(Counter((m or {}).get("section", "Unknown") for m in metas))
    except Exception:
        return {}


def wipe(symbol: str, db_dir: str = VECTOR_DB_DIR) -> bool:
    if not os.path.isdir(db_dir):
        return False
    try:
        _db(db_dir).delete_collection(_collection_for(symbol))
        return True
    except Exception:
        return False


def index_filing(
    docs: list[Document],
    symbol: str,
    db_dir: str = VECTOR_DB_DIR,
    filing_meta: dict | None = None,
    replace: bool = True,
    on_progress=None,
) -> Chroma:
    """Embed a filing's chunks and store them.

    Replaces by default. Appending would leave last year's vectors mixed in
    with this year's, and retrieval would quietly blend the two filings.
    """
    if not docs:
        raise ValueError(f"Nothing to index for {symbol}: no chunks were produced.")

    if replace:
        wipe(symbol, db_dir)

    filing_meta = filing_meta or {}
    for doc in docs:
        doc.metadata.setdefault("accession", filing_meta.get("accession", ""))
        doc.metadata.setdefault("year", filing_meta.get("year") or "")
        doc.metadata["version"] = INDEX_VERSION

    store = open_collection(symbol, db_dir)

    # Batched so a 3,000-chunk filing can report progress instead of hanging.
    for start in range(0, len(docs), EMBED_BATCH):
        batch = docs[start: start + EMBED_BATCH]
        store.add_documents(batch)
        if on_progress:
            on_progress(min(start + len(batch), len(docs)), len(docs))

    return store


if __name__ == "__main__":
    from downloader import fetch_latest_10k
    from processor import flatten_html, parse_check, prepare_filing, segment_by_item

    symbol = "AAPL"

    if is_indexed(symbol):
        print(f"{symbol} already indexed ({chunk_total(symbol):,} chunks).")
    else:
        filing = fetch_latest_10k(symbol)
        report = parse_check(segment_by_item(flatten_html(filing.path)))
        print(f"Sections: {report['sections']}, missing: {report['missing'] or 'none'}")

        docs = prepare_filing(filing.path, symbol=symbol)
        print(f"Embedding {len(docs):,} chunks ...")
        index_filing(
            docs,
            symbol,
            filing_meta={"accession": filing.accession, "year": filing.year},
            on_progress=lambda done, total: print(f"  {done}/{total}"),
        )

    store = open_collection(symbol)
    question = "What are the main risks the company faces?"
    print(f"\nSearching: {question!r}\n")
    for n, doc in enumerate(store.similarity_search(question, k=3), start=1):
        print(f"--- {n} | {doc.metadata.get('section')} ---")
        print(doc.page_content[:250], "...\n")