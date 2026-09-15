import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from vectorstore import open_collection

load_dotenv()

CHAT_MODEL = "gpt-4o-mini"

# gpt-4o-mini holds 128k tokens. 90k characters is roughly 22k of them, which
# covers the risk factors of all but the longest filers.
MAX_CONTEXT_CHARS = 90_000


@lru_cache(maxsize=4)
def make_llm(temp: float = 0.0) -> ChatOpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
    return ChatOpenAI(model=CHAT_MODEL, temperature=temp)


def _item_body(store, item: str, limit: int = MAX_CONTEXT_CHARS) -> tuple[str, int]:
    """Return (text, length before truncation) for one item."""
    result = store.get(where={"section": item})
    texts = result.get("documents") or []
    if not texts:
        return "", 0

    # Chroma can hand back None for metadatas, and zipping against None blows up.
    metas = [m or {} for m in (result.get("metadatas") or [{} for _ in texts])]

    # Chunks come back unordered; put them in reading order.
    in_order = sorted(zip(texts, metas), key=lambda p: p[1].get("chunk_index", 0))
    joined = "\n".join(t for t, _ in in_order)
    return joined[:limit], len(joined)


def _pull(store, items, limit=MAX_CONTEXT_CHARS) -> tuple[str, int, int]:
    """Gather one or more items. Splits the budget so a long Item 8 can't
    crowd out the MD&A, which is where most of the numbers actually are."""
    share = limit // len(items)
    parts, total = [], 0
    for item in items:
        text, full = _item_body(store, item, limit=share)
        if text:
            parts.append(text)
        total += full
    body = "\n\n".join(parts).strip()
    return body, len(body), total


def _complete(template: str, **fields) -> str:
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | make_llm() | StrOutputParser()
    return chain.invoke(fields).strip()


BUSINESS_TMPL = """Act as an equity analyst. Based strictly on the Item 1
(Business) excerpt below, describe in 3-4 sentences what this company does, the
products or services it sells, and where its revenue comes from. Stick to the
text; do not add outside knowledge.

EXCERPT:
{body}

BUSINESS SUMMARY:"""

RISKS_TMPL = """Act as an equity analyst. From the Item 1A (Risk Factors)
excerpt below, list the 5 to 7 most material risks as bullet points. Lead each
bullet with a short bold label, then one sentence in plain English. Only use
risks that appear in the text.

EXCERPT:
{body}

TOP RISKS:"""

FINANCIALS_TMPL = """Act as an equity analyst. Using the Item 7 (MD&A) and
Item 8 (Financial Statements) excerpts below, pull out the notable financial
figures as bullet points -- revenue, net income, growth, margins, cash, and
similar. Quote real numbers from the text and never estimate a missing one. If
a figure is not in the excerpts, leave it out.

EXCERPTS:
{body}

FINANCIAL HIGHLIGHTS:"""

TONE_TMPL = """Act as an equity analyst reading Item 7 (MD&A). Judge how
management sounds overall. Begin with a single word (Optimistic, Cautiously
Optimistic, Neutral, Cautious, or Negative), then justify it in 2-3 sentences
referencing specific wording from the excerpt.

EXCERPT:
{body}

TONE ASSESSMENT:"""


def summarize_business(symbol: str, store=None) -> str:
    store = store or open_collection(symbol)
    body, _, _ = _pull(store, ["Item 1"])
    if not body:
        return "Business section (Item 1) was not found in the filing."
    return _complete(BUSINESS_TMPL, body=body)


def summarize_risks(symbol: str, store=None) -> str:
    store = store or open_collection(symbol)
    body, _, _ = _pull(store, ["Item 1A"])
    if not body:
        return "Risk factors section (Item 1A) was not found in the filing."
    return _complete(RISKS_TMPL, body=body)


def summarize_financials(symbol: str, store=None) -> str:
    store = store or open_collection(symbol)
    body, _, _ = _pull(store, ["Item 7", "Item 8"])
    if not body:
        return "Financial sections (Item 7 / Item 8) were not found in the filing."
    return _complete(FINANCIALS_TMPL, body=body)


def gauge_sentiment(symbol: str, store=None) -> str:
    store = store or open_collection(symbol)
    body, _, _ = _pull(store, ["Item 7"])
    if not body:
        return "MD&A section (Item 7) was not found in the filing."
    return _complete(TONE_TMPL, body=body)


def build_report(symbol: str, store=None) -> dict[str, str]:
    """Run all four sections at once.

    They don't depend on each other and each takes 10-20 seconds, so running
    them in sequence made the wait about four times longer than needed.
    """
    store = store or open_collection(symbol)

    jobs = {
        "overview": summarize_business,
        "risks": summarize_risks,
        "financials": summarize_financials,
        "sentiment": gauge_sentiment,
    }

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {key: pool.submit(fn, symbol, store) for key, fn in jobs.items()}
        return {key: future.result() for key, future in futures.items()}


# Which items feed each tab, for the coverage readout.
SECTION_ITEMS = {
    "overview": ["Item 1"],
    "risks": ["Item 1A"],
    "financials": ["Item 7", "Item 8"],
    "sentiment": ["Item 7"],
}


def coverage(store) -> dict[str, dict]:
    """How much of each item the model actually got to read."""
    out = {}
    for key, items in SECTION_ITEMS.items():
        _, used, total = _pull(store, items)
        out[key] = {
            "used": used,
            "total": total,
            "share": min(1.0, used / total) if total else 0.0,
            "found": total > 0,
        }
    return out


QA_TMPL = """You are an analyst answering a question about {company}'s 10-K.
Use ONLY the CONTEXT below, pulled from the filing. Do not use outside knowledge.

Filings rarely rank items as "biggest" or "most important." If the question
asks for that and the excerpt has no ranking, answer from the risks or facts
the excerpt actually discusses and say that the filing does not single one out.

Reply exactly: "I couldn't find that in the filing." only when the context
does not discuss the topic at all.

CONTEXT:
{context}

QUESTION: {question}

ANSWER:"""

NOT_FOUND = "I couldn't find that in the filing."

QA_FOLLOWUP = """The CONTEXT is from {company}'s 10-K and does cover this topic.
Question: {question}

Answer from the context in 3-6 sentences. If the filing lists several risks
or figures but does not rank them, say so and summarize the main ones it
discusses. Do not say you could not find the answer.

CONTEXT:
{context}

ANSWER:"""


def _stitch(docs) -> str:
    parts = []
    for doc in docs:
        item = doc.metadata.get("section", "Unknown section")
        parts.append(f"[{item}]\n{doc.page_content}")
    return "\n\n".join(parts)


# Question words that mean "read this item first," not just nearest embedding.
_ROUTE = (
    (("risk", "litigation", "lawsuit", "cyber", "threat"), ("Item 1A",)),
    (("revenue", "sales", "margin", "income", "earning", "profit", "cash"),
     ("Item 7", "Item 8")),
    (("business", "overview", "what does", "company do", "products", "services"),
     ("Item 1",)),
    (("outlook", "md&a", "sentiment", "management discuss"), ("Item 7",)),
    (("summarize", "summary", "filing about", "main things", "things to know",
      "key takeaway", "key point", "should i know", "this filing", "this 10-k",
      "this 10k", "this report"),
     ("Item 1", "Item 1A", "Item 7")),
)


def _route(question: str) -> tuple[str, ...]:
    q = question.lower()
    for keys, items in _ROUTE:
        if any(key in q for key in keys):
            return items
    return ()


def _leading_chunks(store, items, n: int = 4) -> list[Document]:
    """First n chunks of each item, in reading order — usually the overview."""
    docs = []
    for item in items:
        result = store.get(where={"section": item})
        texts = result.get("documents") or []
        metas = [m or {} for m in (result.get("metadatas") or [{} for _ in texts])]
        ordered = sorted(zip(texts, metas), key=lambda p: p[1].get("chunk_index", 0))
        for text, meta in ordered[:n]:
            docs.append(Document(page_content=text, metadata=meta))
    return docs


def _dedupe(docs: list[Document]) -> list[Document]:
    seen: set[str] = set()
    out = []
    for doc in docs:
        key = doc.page_content[:160]
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def ask_filing(symbol: str, question: str, store=None, k: int = 6) -> dict:
    """Answer from retrieved chunks only.

    Semantic search alone often misses the start of a long Item 1A, which is
    where filers list the principal risks. Questions that clearly map to an
    item get those opening chunks plus the nearest matches.
    """
    store = store or open_collection(symbol)
    seeded = _leading_chunks(store, _route(question))
    hits = store.similarity_search(question, k=k)
    docs = _dedupe(seeded + hits)

    if not docs:
        return {"answer": NOT_FOUND, "sources": []}

    context = _stitch(docs)
    answer = _complete(QA_TMPL, company=symbol, context=context, question=question)
    # Seeded a known section but the model still refused because the filing
    # never says "biggest." Ask again, forbidding the canned refusal.
    if answer.startswith(NOT_FOUND) and seeded:
        answer = _complete(QA_FOLLOWUP, company=symbol, context=context, question=question)
    sources = sorted({doc.metadata.get("section", "Unknown") for doc in docs})
    return {
        "answer": answer,
        "sources": [] if answer.startswith(NOT_FOUND) else sources,
    }


if __name__ == "__main__":
    symbol = "AAPL"
    store = open_collection(symbol)

    report = build_report(symbol, store)
    for key, text in report.items():
        print(f"=== {key.upper()} ===")
        print(text, "\n")

    print("=== COVERAGE ===")
    for key, info in coverage(store).items():
        print(f"  {key:<12} {info['share']:.0%} of {info['total']:,} chars")

    print("\n=== Q&A TEST ===")
    q = "How much revenue did the company generate and how did it change?"
    reply = ask_filing(symbol, q, store)
    print("Q:", q)
    print("A:", reply["answer"])
    print("Sources:", reply["sources"])