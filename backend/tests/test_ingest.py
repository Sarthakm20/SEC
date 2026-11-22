from app.ingest.chunker import chunk_document
from app.ingest.html_parser import parse_10k_html
from app.ingest.xbrl import locate_facts_in_document, normalize_company_facts
from app.models import Company, Filing

COMPANY = Company(ticker="TEST", cik=1234, name="Test Corp")


def _row(start, end, val, accn, fy, filed):
    r = {"end": end, "val": val, "accn": accn, "fy": fy, "fp": "FY", "form": "10-K", "filed": filed}
    if start:
        r["start"] = start
    return r


def company_facts():
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {
                        "USD": [
                            _row("2022-01-01", "2022-12-31", 100, "A-23", 2022, "2023-02-01"),
                            _row("2022-01-01", "2022-12-31", 100, "A-24", 2023, "2024-02-01"),  # comparative
                            _row("2023-01-01", "2023-12-31", 120, "A-24", 2023, "2024-02-01"),
                            _row("2023-01-01", "2023-12-31", 118, "A-25", 2024, "2025-02-01"),  # restated
                            _row("2024-01-01", "2024-12-31", 150, "A-25", 2024, "2025-02-01"),
                            _row("2024-10-01", "2024-12-31", 40, "A-25", 2024, "2025-02-01"),  # quarter: excluded
                        ]
                    },
                },
                "StockholdersEquity": {"label": "Equity", "units": {"USD": [_row(None, "2024-12-31", 500, "A-25", 2024, "2025-02-01"), _row(None, "2024-06-30", 480, "A-25", 2024, "2025-02-01")]}},
            }
        }
    }


def test_normalize_fiscal_years_dedupe_and_conflicts():
    facts, conflicts = normalize_company_facts(COMPANY, company_facts(), [])
    rev = {f.fiscal_year: f for f in facts if f.concept == "us-gaap:Revenues"}
    assert sorted(rev) == [2022, 2023, 2024]  # quarterly fact excluded
    assert rev[2023].value == "120" and rev[2023].accession == "A-24"  # original filing is canonical
    assert len(conflicts) == 1 and conflicts[0].end == "2023-12-31"
    eq = [f for f in facts if f.concept == "us-gaap:StockholdersEquity"]
    assert len(eq) == 1 and eq[0].end == "2024-12-31"  # mid-year instant excluded


HTML = """<?xml version='1.0' encoding='ASCII'?>
<html><body>
<div><table><tr><td>Item 1A.</td><td>Risk Factors</td><td>5</td></tr><tr><td>Item 7.</td><td>MD&amp;A</td><td>9</td></tr></table></div>
<div>Cover page</div><hr style="page-break-after:always"/>
<div><span style="font-weight:700">Item 1A. Risk Factors</span></div>
<div><span style="font-weight:700">Supply risks</span></div>
<div>We depend on a few suppliers located in Taiwan. A disruption could materially harm our results &#8212; including our margins. """ + ("More risk text. " * 60) + """</div>
<div>2</div><hr style="page-break-after:always"/>
<div><span style="font-weight:700">Item 7. Management&#8217;s Discussion and Analysis</span></div>
<div>Revenue grew because of strong demand. """ + ("Discussion text. " * 60) + """</div>
<div><span style="font-weight:700">CONSOLIDATED STATEMENTS OF OPERATIONS</span></div>
<table><tr><td>Revenue</td><td>$</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="c1" scale="0" decimals="0">150</ix:nonFraction></td></tr></table>
<div>3</div><hr style="page-break-after:always"/>
<div><span style="font-weight:700">Item 8. Financial Statements</span></div><div>See statements.</div>
<div style="display:none"><ix:header><ix:resources>
<xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="x">1234</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
</ix:resources></ix:header></div>
</body></html>"""


def test_parse_sections_pages_and_ix_location():
    doc = parse_10k_html(HTML.encode())
    assert {"item_1a", "item_7"} <= set(doc.sections)
    s = doc.sections["item_1a"]
    texts = " ".join(b.text for b in doc.blocks[s.start_block : s.end_block])
    assert "Taiwan" in texts and "Item 1A" not in texts.split("Supply risks")[0][-5:]
    assert doc.page_labels.get(2) == "2"
    assert "—" in texts  # numeric entity decoded despite ASCII declaration
    facts, _ = normalize_company_facts(COMPANY, company_facts(), [])
    assert locate_facts_in_document(facts, doc, "A-25") >= 1
    loc = next(f.location for f in facts if f.location)
    assert loc.page == 3 and loc.row_label == "Revenue" and loc.table_title == "CONSOLIDATED STATEMENTS OF OPERATIONS"


def test_chunker_keeps_subsections_and_metadata():
    doc = parse_10k_html(HTML.encode())
    filing = Filing(accession="A-25", cik=1234, ticker="TEST", form="10-K", filing_date="2025-02-01", report_date="2024-12-31", fiscal_year=2024, primary_document="t.htm")
    chunks = chunk_document(doc, filing, COMPANY, target_tokens=120, overlap_tokens=20)
    risk = [c for c in chunks if c.section == "item_1a"]
    assert risk and all(c.subsection == "Supply risks" for c in risk)
    assert all(c.page_start == 2 for c in risk)
    assert any(c.kind == "table" for c in chunks)


def test_item_headings_laid_out_as_one_row_tables():
    """Walmart formats headings as tiny tables ("ITEM 1A. | RISK FACTORS"); the TOC table must not count."""
    from app.ingest.html_parser import parse_10k_html

    body = "Our business depends on many things that could go wrong in various ways. " * 12
    html = (
        "<html><body>"
        "<table><tr><td>Item 1</td><td>Business</td><td>6</td></tr><tr><td>Item 1A</td><td>Risk Factors</td><td>14</td></tr>"
        "<tr><td>Item 7</td><td>Management's Discussion</td><td>30</td></tr></table>"
        "<table><tr><td>ITEM 1.</td><td>BUSINESS</td></tr></table>"
        f"<p>{body}</p>"
        "<table><tr><td>ITEM 1A.</td><td>RISK FACTORS</td></tr></table>"
        f"<p>{body}</p><p>{body}</p>"
        "<table><tr><td>ITEM 7.</td><td>MANAGEMENT'S DISCUSSION AND ANALYSIS</td></tr></table>"
        f"<p>{body}</p>"
        "</body></html>"
    )
    doc = parse_10k_html(html)
    assert {"item_1", "item_1a", "item_7"} <= set(doc.sections)
