"""Score retrieval and answers against eval_questions.json.

Retrieval is judged at the answer level: a chunk counts as relevant only if it
contains one of the labelled evidence strings, not just because it comes from
the right item.

    python evaluate.py                 # plain search vs. routed, with answers
    python evaluate.py --no-answers    # retrieval only, no chat calls
    python evaluate.py C WFC -v        # some tickers, print every miss
"""
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor

from analyzer import NOT_FOUND, ask_filing, retrieve
from vectorstore import is_indexed, open_collection

K = 6
MODES = {"plain": False, "routed": True}

_DECLINE = re.compile(
    r"couldn'?t find|could not find|not (mentioned|provided|included|disclosed|available|covered)"
    r"|does not (provide|contain|include|mention|discuss|specify)"
    r"|doesn'?t (provide|contain|include|mention|discuss|specify)|no information",
    re.I,
)


def norm(text: str) -> str:
    text = text.lower().replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    text = text.replace(",", "").replace("$", "")
    text = re.sub(r"\s+%", "%", text)
    return re.sub(r"\s+", " ", text).strip()


def _alts(fact) -> list[str]:
    return [norm(a) for a in (fact if isinstance(fact, list) else [fact])]


def covered(chunk: str, fact) -> bool:
    body = norm(chunk)
    return any(alt in body for alt in _alts(fact))


def score_retrieval(docs, case) -> dict:
    facts = case["evidence"]
    top = docs[:K]
    first = next((i for i, d in enumerate(docs, 1)
                  if any(covered(d.page_content, f) for f in facts)), None)
    return {
        "recall@k": sum(any(covered(d.page_content, f) for d in top) for f in facts) / len(facts),
        "context_recall": sum(any(covered(d.page_content, f) for d in docs) for f in facts) / len(facts),
        "rr": 1 / first if first else 0.0,
        "section_hit": any(d.metadata.get("section") == case["item"] for d in top),
        "context_size": len(docs),
    }


def _as_billions(value: str) -> list[str]:
    """Filings report in millions; models often restate in billions."""
    if not value.isdigit() or len(value) < 4:
        return []
    billions = int(value) / 1000
    return sorted({f"{billions:.{d}f} billion" for d in (1, 2, 3)})


def score_answer(answer: str, case) -> dict:
    refused = answer.startswith(NOT_FOUND)
    if case.get("refuse"):
        return {"declined": refused or bool(_DECLINE.search(answer))}
    expected = [norm(a) for a in case.get("answer", [])]
    expected += [b for a in expected for b in _as_billions(a)]
    return {
        "refused": refused,
        "correct": (not refused) and (not expected or any(a in norm(answer) for a in expected)),
    }


def missing_evidence(store, cases) -> list[str]:
    everything = store.get().get("documents") or []
    problems = []
    for case in cases:
        for fact in case.get("evidence", []):
            if not any(covered(doc, fact) for doc in everything):
                problems.append(f"{case['q']!r}: {fact!r}")
    return problems


def run_ticker(symbol, cases, answers, verbose):
    store = open_collection(symbol)
    bad = missing_evidence(store, cases)
    for line in bad:
        print(f"  [label not in index] {symbol} {line}")

    rows = []
    for mode, routed in MODES.items():
        for case in cases:
            row = {"ticker": symbol, "mode": mode, "q": case["q"], "refuse": bool(case.get("refuse"))}
            if not row["refuse"]:
                docs, _ = retrieve(store, case["q"], k=K, routed=routed)
                row.update(score_retrieval(docs, case))
            rows.append(row)

    if answers:
        def answer(row):
            case = next(c for c in cases if c["q"] == row["q"])
            reply = ask_filing(symbol, row["q"], store, k=K, routed=MODES[row["mode"]])
            return {**score_answer(reply["answer"], case), "answer": reply["answer"]}

        with ThreadPoolExecutor(max_workers=8) as pool:
            for row, result in zip(rows, pool.map(answer, rows)):
                row.update(result)

    if verbose:
        for row in rows:
            flags = []
            if not row["refuse"] and row["rr"] == 0:
                flags.append("no evidence retrieved")
            if row.get("refused"):
                flags.append("false refusal")
            if row.get("correct") is False and not row.get("refused"):
                flags.append("answer missing expected fact")
            if row["refuse"] and row.get("declined") is False:
                flags.append("answered a must-refuse question")
            if flags:
                print(f"  {symbol:<5} {row['mode']:<6} {row['q']}  -> {', '.join(flags)}")
                if "answer" in row and verbose > 1:
                    print("        " + row["answer"][:300].replace("\n", " "))
    return rows


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else float("nan")


def summarize(rows, label):
    answerable = [r for r in rows if not r["refuse"]]
    traps = [r for r in rows if r["refuse"]]
    out = {
        "label": label,
        "n": len(answerable),
        "recall@k": _mean(r["recall@k"] for r in answerable),
        "context_recall": _mean(r["context_recall"] for r in answerable),
        "mrr": _mean(r["rr"] for r in answerable),
        "section_hit": _mean(r["section_hit"] for r in answerable),
        "context_size": _mean(r["context_size"] for r in answerable),
    }
    if answerable and "refused" in answerable[0]:
        out["false_refusal"] = _mean(r["refused"] for r in answerable)
        out["accuracy"] = _mean(r["correct"] for r in answerable)
        out["correct_refusal"] = _mean(r["declined"] for r in traps)
    return out


def print_table(summaries):
    cols = [("recall@k", f"Recall@{K}"), ("context_recall", "CtxRecall"), ("mrr", "MRR"),
            ("section_hit", "SectHit@6"), ("context_size", "Chunks"),
            ("false_refusal", "FalseRef"), ("accuracy", "Accuracy"), ("correct_refusal", "TrapRef")]
    cols = [c for c in cols if c[0] in summaries[0]]
    print(f"\n{'':<14}{'n':>4}" + "".join(f"{name:>11}" for _, name in cols))
    for s in summaries:
        cells = "".join(
            f"{s[key]:>11.1f}" if key == "context_size" else f"{s[key]:>11.2f}" for key, _ in cols
        )
        print(f"{s['label']:<14}{s['n']:>4}{cells}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--questions", default="eval_questions.json")
    parser.add_argument("--no-answers", action="store_true")
    parser.add_argument("--out", help="write per-question rows to this JSON file")
    parser.add_argument("--rescore", help="re-grade answers saved by --out instead of calling the API")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    with open(args.questions) as fh:
        dataset = json.load(fh)
    tickers = [t.upper() for t in args.tickers] or list(dataset)

    rows = []
    if args.rescore:
        with open(args.rescore) as fh:
            rows = [r for r in json.load(fh) if r["ticker"] in tickers]
        for row in rows:
            if "answer" in row:
                case = next(c for c in dataset[row["ticker"]] if c["q"] == row["q"])
                row.update(score_answer(row["answer"], case))
    for symbol in [] if args.rescore else tickers:
        if not is_indexed(symbol):
            print(f"{symbol}: not indexed, skipping (analyze it in the app first)")
            continue
        rows += run_ticker(symbol, dataset[symbol], not args.no_answers, args.verbose)

    summaries = []
    for symbol in tickers:
        for mode in MODES:
            subset = [r for r in rows if r["ticker"] == symbol and r["mode"] == mode]
            if subset:
                summaries.append(summarize(subset, f"{symbol} {mode}"))
    for mode in MODES:
        summaries.append(summarize([r for r in rows if r["mode"] == mode], f"ALL {mode}"))
    print_table(summaries)

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rows, fh, indent=2)


if __name__ == "__main__":
    main()
