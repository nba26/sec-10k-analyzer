"""Synthetic-filing tests for the item segmentation logic.

Runs without langchain installed, so it can be used as a fast local check.
"""
import importlib.util
import sys
import types

for name in ("langchain_core", "langchain_core.documents", "langchain_text_splitters"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["langchain_core.documents"].Document = object
sys.modules["langchain_text_splitters"].RecursiveCharacterTextSplitter = object

spec = importlib.util.spec_from_file_location("processor", "processor.py")
proc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proc)

FILLER = "The Company continued its operations across all reportable segments. "

TOC_ITEMS = [
    ("1", "Business"), ("1A", "Risk Factors"), ("1B", "Unresolved Staff Comments"),
    ("1C", "Cybersecurity"), ("2", "Properties"), ("3", "Legal Proceedings"),
    ("4", "Mine Safety Disclosures"),
    ("5", "Market for Registrant's Common Equity"), ("6", "[Reserved]"),
    ("7", "Management's Discussion and Analysis of Financial Condition"),
    ("7A", "Quantitative and Qualitative Disclosures About Market Risk"),
    ("8", "Financial Statements and Supplementary Data"),
    ("9", "Changes in and Disagreements with Accountants"),
    ("9A", "Controls and Procedures"), ("9B", "Other Information"),
    ("10", "Directors, Executive Officers and Corporate Governance"),
    ("11", "Executive Compensation"),
    ("12", "Security Ownership of Certain Beneficial Owners"),
    ("13", "Certain Relationships and Related Transactions"),
    ("14", "Principal Accountant Fees and Services"),
    ("15", "Exhibits, Financial Statement Schedules"),
    ("16", "Form 10-K Summary"),
]


def make_filing(period=True, toc=True, crossref=False, part_iii_short=False):
    dot = "." if period else ""
    out = ["ANNUAL REPORT PURSUANT TO SECTION 13 " + FILLER * 3]
    if toc:
        out.append("TABLE OF CONTENTS ")
        for num, title in TOC_ITEMS:
            out.append(f"Item {num}{dot} {title} 12 ")
    out.append("PART I ")
    for num, title in TOC_ITEMS:
        out.append(f"Item {num}{dot} {title} ")
        if part_iii_short and num in ("9B", "10", "11", "12", "13", "14"):
            out.append("Incorporated by reference to the Proxy Statement. ")
        else:
            out.append(FILLER * 40)
        if crossref and num == "2":
            out.append("For more detail see Item 1A. Risk Factors above. ")
    return "".join(out)


def make_untitled_mda():
    """Item 7 exists only as a stub; the MD&A is printed under its title."""
    out = ["ANNUAL REPORT " + FILLER * 3, "TABLE OF CONTENTS "]
    for num, title in TOC_ITEMS:
        out.append(f"Item {num}. {title} 12 ")
    out.append("PART I ")
    out.append("Item 1. Business " + FILLER * 40)
    out.append("Item 1A. Risk Factors " + FILLER * 40)
    out.append(
        "Item 7. Management's Discussion and Analysis of Financial Condition "
        "and Results of Operations. See the discussion beginning on page 46. "
    )
    out.append("Item 8. Financial Statements and Supplementary Data. ")
    out.append("The statements commence on page 162. ")
    out.append("Management's Discussion and Analysis " + FILLER * 50)
    out.append("Item 9. Changes in and Disagreements with Accountants " + FILLER * 10)
    return "".join(out)


def make_citi_style():
    """No 'Item N' labels — only statutory titles, plus a page-number TOC."""
    toc = (
        "CROSS-REFERENCE INDEX 1. Business 4 1A. Risk Factors 10 "
        "7. Management's Discussion and Analysis of Financial Condition and "
        "Results of Operations 20 8. Financial Statements 40 "
        "OVERVIEW 4 Non-GAAP Financial Measures "
        "MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND "
        "RESULTS OF OPERATIONS 8 Executive "
        "RISK FACTORS 49 SUSTAINABILITY "
        "CONSOLIDATED FINANCIAL STATEMENTS 134 NOTES "
    )
    body = (
        "OVERVIEW Citigroup history dates back to a bank. " + FILLER * 60
        + "MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND "
        "RESULTS OF OPERATIONS Executive summary follows. " + FILLER * 60
        + "RISK FACTORS The following discussion presents material risks. "
        + FILLER * 60
        + "CONSOLIDATED FINANCIAL STATEMENTS Consolidated Statement of Income. "
        + FILLER * 60
    )
    return toc + body


def make_annual_report():
    """Exhibit-13 style: Financial Review / Risk Factors / auditor report."""
    return (
        "Exhibit 13 Financial Review 2 Overview 114 Risk Factors 62 "
        "Financial Statements 75 "
        "Financial Review Overview Wells Fargo is a bank. " + FILLER * 60
        + "Risk Factors An investment in the Company involves risk. " + FILLER * 60
        + "Report of Independent Registered Public Accounting Firm To the "
        "Stockholders. " + FILLER * 60
    )


def make_late_xref_1a():
    """Real Item 1A, then a late cross-ref that would win on max-gap alone."""
    return (
        "Item 1. Business " + FILLER * 40
        + "Item 1A. Risk Factors. The following discussion sets forth the "
        "material risk factors. " + FILLER * 60
        + "Item 7. Management's Discussion and Analysis of Financial Condition "
        + FILLER * 40
        + "Item 8. Financial Statements and Supplementary Data " + FILLER * 40
        + "Item 1A: Risk Factors in this Form 10-K. Any forward-looking "
        "statements made by the Firm. " + FILLER * 80
    )


CASES = {
    "standard (periods, TOC)": make_filing(),
    "no periods in headers": make_filing(period=False),
    "no table of contents": make_filing(toc=False),
    "cross-reference in body": make_filing(crossref=True),
    "Part III incorporated by ref": make_filing(part_iii_short=True),
    "no periods + crossrefs": make_filing(period=False, crossref=True),
    "untitled MD&A (JPM-style)": make_untitled_mda(),
    "no Item labels (Citi-style)": make_citi_style(),
}

failures = 0
for name, text in CASES.items():
    segments = proc.segment_by_item(text)
    result = proc.parse_check(segments)
    if not result["ok"]:
        failures += 1
    print(f"[{'PASS' if result['ok'] else 'FAIL'}] {name:<32} "
          f"sections={result['sections']:>2} missing={result['missing'] or '-'}")
    if result["ok"] and name not in {
        "untitled MD&A (JPM-style)",
        "no Item labels (Citi-style)",
    }:
        for key in ("Item 1", "Item 1A", "Item 7", "Item 8"):
            assert len(segments[key]) > 2000, f"{name}: {key} is only {len(segments[key])} chars"

print()
segments = proc.segment_by_item(CASES["cross-reference in body"])
assert "Risk Factors above" not in segments["Item 1A"][:200], "crossref beat the real section"
print("crossref did not displace real Item 1A: OK")

segments = proc.segment_by_item(CASES["standard (periods, TOC)"])
assert len(segments["Item 1"]) > 2000, "TOC stub survived as Item 1"
assert "TABLE OF CONTENTS" not in segments.get("Item 16", ""), "Item 16 swallowed the TOC"
print("TOC stripped cleanly: OK")

untitled = proc.segment_by_item(CASES["untitled MD&A (JPM-style)"])
assert len(untitled["Item 7"]) > 2000, f"untitled MD&A not recovered: {len(untitled.get('Item 7', ''))}"
assert FILLER.strip() in untitled["Item 7"]
print("untitled MD&A recovered as Item 7: OK")

citi = proc.segment_by_item(CASES["no Item labels (Citi-style)"])
for key in ("Item 1", "Item 1A", "Item 7", "Item 8"):
    assert len(citi.get(key, "")) > 2000, f"Citi-style {key} is {len(citi.get(key, ''))}"
assert citi["Item 1"].startswith("OVERVIEW Citigroup")
assert "The following discussion" in citi["Item 1A"]
print("statutory titles recover Citi-style filings: OK")

annual = proc.segment_by_item(make_annual_report())
assert len(annual.get("Item 7", "")) > 2000, "annual-report MD&A not found"
assert len(annual.get("Item 1A", "")) > 2000, "annual-report risks not found"
assert len(annual.get("Item 8", "")) > 2000, "annual-report financials not found"
assert "Wells Fargo is a bank" in annual["Item 7"]
print("annual-report titles map to Items 1A/7/8: OK")

xref = proc.segment_by_item(make_late_xref_1a())
assert "sets forth the material risk factors" in xref["Item 1A"]
assert not xref["Item 1A"].startswith("Item 1A: Risk Factors in this")
print("late Item 1A cross-ref did not beat the real section: OK")

assert proc.segment_by_item("nothing here") == {"Full Document": "nothing here"}
assert "Full Document" in proc.segment_by_item("Item 1. Business " + FILLER)
print("degrades to Full Document on unparseable input: OK")

print(f"\n{len(CASES) - failures}/{len(CASES)} filing shapes parsed correctly")
sys.exit(1 if failures else 0)