"""SEC 10-K Financial Analyzer - chat-first interface."""

import os
from datetime import datetime

import streamlit as st

from analyzer import ask_filing, build_report, coverage
from downloader import fetch_latest_10k, load_company_index
from processor import flatten_html, parse_check, prepare_filing, segment_by_item
from _style import CSS, HERO
from vectorstore import (
    chunk_total,
    index_filing,
    needs_reindex,
    open_collection,
    stored_filing,
    wipe,
)

st.set_page_config(
    page_title="SEC 10-K Analyzer",
    page_icon="§",
    layout="wide",
    initial_sidebar_state="expanded",
)

# (report key, tab label, source items shown to the reader)
TABS = [
    ("overview", "Business", "Item 1"),
    ("risks", "Risks", "Item 1A"),
    ("financials", "Financials", "Item 7 + 8"),
    ("sentiment", "Tone", "Item 7"),
]

STARTERS = [
    "What does this company actually sell?",
    "What risks are disclosed?",
    "How did revenue change?",
    "Any pending litigation?",
]

MAX_MATCHES = 25
THIN_SECTION_CHARS = 3000

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

st.markdown(CSS, unsafe_allow_html=True)


def md(text) -> str:
    """Streamlit reads $...$ as LaTeX. Filings are full of dollar amounts."""
    return str(text).replace("$", "\\$")


def pills(items) -> str:
    return ('<div class="cites">'
            + "".join(f'<span class="cite">{i}</span>' for i in items)
            + "</div>")


def label_for(record: dict) -> str:
    return f"{record['ticker']} — {record['title']}"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

st.session_state.setdefault("reports", {})
st.session_state.setdefault("chats", {})
st.session_state.setdefault("active", None)
st.session_state.setdefault("pending", None)


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def company_index() -> list[dict]:
    try:
        return load_company_index()
    except Exception:
        return []


@st.cache_resource(show_spinner=False)
def cached_store(symbol: str):
    return open_collection(symbol)


def search_companies(term: str, catalog: list[dict]) -> list[dict]:
    """Match on ticker, name or CIK, one row per company.

    Searching 'jpm' used to return nine rows because preferred shares and
    ETFs (JPM-PC, VYLD, AMJB) all carry the same company title.
    """
    term = term.strip().lower()
    if not term:
        return []

    hits = [
        row for row in catalog
        if term == row["ticker"].lower()
        or term in row["title"].lower()
        or term in row["ticker"].lower()
        or term in row["cik"].lstrip("0")
    ]

    # Shortest ticker per company name is the common share class.
    best: dict[str, dict] = {}
    for row in hits:
        key = row["title"].lower()
        if key not in best or len(row["ticker"]) < len(best[key]["ticker"]):
            best[key] = row

    ranked = sorted(best.values(),
                    key=lambda r: (term != r["ticker"].lower(), r["title"]))
    return ranked[:MAX_MATCHES]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_analysis(record: dict, force: bool) -> None:
    symbol = record["ticker"]
    year = "—"

    with st.status(f"Working on {symbol}", expanded=True) as status:
        try:
            if force:
                st.write("Dropping the existing index.")
                wipe(symbol)
                cached_store.clear()

            if force or needs_reindex(symbol):
                st.write("Fetching the latest 10-K from EDGAR.")
                filing = fetch_latest_10k(symbol)
                year = filing.year or "—"

                st.write("Splitting the filing into items.")
                found = parse_check(segment_by_item(flatten_html(filing.path)))
                if found["fell_back"]:
                    st.write("Could not recognise the item headings. Indexing the "
                             "whole document, so section answers will be weaker.")
                elif found["missing"]:
                    st.write(f"Parsed, but missing: {', '.join(found['missing'])}")
                else:
                    st.write(f"Recovered {found['sections']} items cleanly.")

                docs = prepare_filing(filing.path, symbol=symbol)
                bar = st.progress(0.0, text=f"Embedding {len(docs):,} chunks")
                index_filing(
                    docs, symbol,
                    filing_meta={"accession": filing.accession, "year": filing.year},
                    on_progress=lambda done, total: bar.progress(
                        done / total, text=f"Embedding {done:,} / {total:,} chunks"),
                )
                bar.empty()
                cached_store.clear()
            else:
                year = stored_filing(symbol).get("year") or "—"
                st.write(f"Reusing the stored index ({chunk_total(symbol):,} chunks).")

            st.write("Reading Items 1, 1A, 7 and 8.")
            store = cached_store(symbol)
            report = build_report(symbol, store)
            seen = coverage(store)

        except Exception as exc:
            status.update(label=f"{symbol} failed", state="error", expanded=True)
            st.write(f"**{type(exc).__name__}:** {exc}")
            return

        status.update(label=f"{symbol} ready", state="complete", expanded=False)

    st.session_state["reports"][symbol] = {
        "report": report,
        "record": record,
        "year": year,
        "coverage": seen,
        "at": datetime.now().strftime("%d %b %Y, %H:%M"),
    }
    st.session_state["chats"].setdefault(symbol, [])
    st.session_state["active"] = symbol


def to_markdown(entry: dict) -> str:
    record, report = entry["record"], entry["report"]
    lines = [
        f"# {record['title']} ({record['ticker']})",
        f"CIK {record.get('cik', '—')} · FY {entry['year']} · generated {entry['at']}",
        "",
        "*Generated from the filing by an LLM. Verify against the source document.*",
        "",
    ]
    for key, title, item in TABS:
        lines += [f"## {title} ({item})", "", report.get(key, ""), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown('<div class="sidelabel">Look up a filer</div>', unsafe_allow_html=True)

    catalog = company_index()
    picked: dict | None = None

    if catalog:
        term = st.text_input("Company, ticker, or CIK",
                             placeholder="Apple, AAPL, 320193",
                             label_visibility="collapsed")
        matches = search_companies(term, catalog)
        if term and not matches:
            st.caption(f"No EDGAR filer matches “{term}”.")
        elif matches:
            choice = st.radio("Matches", options=range(len(matches)),
                              format_func=lambda i: label_for(matches[i]),
                              label_visibility="collapsed")
            picked = matches[choice]
    else:
        st.caption("EDGAR's company list didn't load. Enter a ticker directly.")
        typed = st.text_input("Ticker", placeholder="AAPL").strip().upper()
        if typed:
            picked = {"ticker": typed, "cik": "—", "title": typed}

    if picked and not needs_reindex(picked["ticker"]):
        st.caption(f"Indexed · FY {stored_filing(picked['ticker']).get('year') or '—'}")

    refresh = st.checkbox("Re-download and re-index",
                          help="Use when a newer 10-K has been filed. Replaces the "
                               "stored vectors rather than adding to them.")

    if st.button("Analyze 10-K", type="primary", use_container_width=True,
                 disabled=picked is None):
        st.session_state["pending"] = (picked, refresh)
        st.rerun()

    done = st.session_state["reports"]
    if done:
        st.divider()
        st.markdown('<div class="sidelabel">Analyzed</div>', unsafe_allow_html=True)
        for sym in list(reversed(list(done)))[:8]:
            if st.button(label_for(done[sym]["record"]), key=f"go_{sym}",
                         use_container_width=True,
                         disabled=sym == st.session_state["active"]):
                st.session_state["active"] = sym
                st.rerun()

    st.divider()
    st.caption("OpenAI key loaded · gpt-4o-mini" if os.getenv("OPENAI_API_KEY")
               else "No OPENAI_API_KEY found. Add it to .env before analyzing.")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if st.session_state["pending"]:
    record, force = st.session_state["pending"]
    st.session_state["pending"] = None
    run_analysis(record, force)

active = st.session_state["active"]
entry = st.session_state["reports"].get(active) if active else None

if not entry:
    st.markdown(HERO, unsafe_allow_html=True)
    st.stop()

record = entry["record"]
report = entry["report"]
seen = entry["coverage"]
symbol = record["ticker"]

st.markdown(
    f'<div class="topline"><h2>{record["title"]}</h2>'
    f'<span class="tick">{symbol}</span></div>'
    f'<div class="docket">'
    f'<div><div class="dk">CIK</div><div class="dv">{record.get("cik", "—")}</div></div>'
    f'<div><div class="dk">Fiscal year</div><div class="dv">{entry["year"]}</div></div>'
    f'<div><div class="dk">Chunks</div><div class="dv">{chunk_total(symbol):,}</div></div>'
    f'<div><div class="dk">Analyzed</div><div class="dv">{entry["at"]}</div></div>'
    f'</div>',
    unsafe_allow_html=True,
)

history = st.session_state["chats"].setdefault(symbol, [])

# The briefing opens on arrival and folds away once the conversation starts,
# so the chat is not pushed off screen by four long report sections.
with st.expander("Filing briefing", expanded=not history):
    tabs = st.tabs([title for _, title, _ in TABS])
    for tab, (key, title, item) in zip(tabs, TABS):
        with tab:
            info = seen.get(key, {})
            note = f"Source: <code>{item}</code>"
            if info.get("found") and 0 < info.get("total", 0) < THIN_SECTION_CHARS:
                note += (" · this item is only a stub in the filing (often "
                         "incorporated by reference to a separate exhibit), so "
                         "this section is limited")
            elif info.get("found") and info["share"] < 1:
                note += f" · {info['share']:.0%} of the section read"
            st.markdown(f'<div class="section-note">{note}</div>',
                        unsafe_allow_html=True)
            with st.container(height=320, border=False):
                st.markdown(md(report.get(key, "")) or "_Nothing generated._")

    st.download_button("Download this analysis", data=to_markdown(entry),
                       file_name=f"{symbol}_10K_analysis.md", mime="text/markdown")

queued: str | None = None
if not history:
    st.markdown(f'<div class="eyebrow">Ask the {symbol} filing</div>', unsafe_allow_html=True)
    cols = st.columns(2)
    for i, starter in enumerate(STARTERS):
        if cols[i % 2].button(starter, key=f"s_{symbol}_{i}",
                              use_container_width=True):
            queued = starter

for msg in history:
    with st.chat_message(msg["role"]):
        st.markdown(md(msg["content"]))
        if msg["role"] == "assistant":
            if msg.get("sources"):
                st.markdown(pills(msg["sources"]), unsafe_allow_html=True)
            else:
                st.markdown('<div class="nosrc">no matching passage in the filing</div>',
                            unsafe_allow_html=True)

query = st.chat_input(f"Ask anything covered by {symbol}'s 10-K") or queued

if query:
    history.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(md(query))

    with st.chat_message("assistant"):
        with st.spinner("Searching the filing"):
            try:
                reply = ask_filing(symbol, query, cached_store(symbol))
            except Exception as exc:
                reply = {"answer": f"That query failed: {exc}", "sources": []}
        st.markdown(md(reply["answer"]))
        if reply.get("sources"):
            st.markdown(pills(reply["sources"]), unsafe_allow_html=True)
        else:
            st.markdown('<div class="nosrc">no matching passage in the filing</div>',
                        unsafe_allow_html=True)

    history.append({"role": "assistant", "content": reply["answer"],
                    "sources": reply.get("sources", [])})
    st.rerun()