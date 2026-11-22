"""Synthetic fixtures: a fictional company 'Acme Robotics' with known numbers."""

from __future__ import annotations

from app.models import Chunk, Company, Fact

ACME = Company(ticker="ACME", cik=9999999, name="Acme Robotics Inc.", fiscal_year_end="1231")

# (concept, fiscal_year, value, period_type)
_VALUES = [
    ("us-gaap:Revenues", 2023, "1000000000", "duration"),
    ("us-gaap:Revenues", 2024, "1250000000", "duration"),
    ("us-gaap:CostOfRevenue", 2024, "500000000", "duration"),
    ("us-gaap:GrossProfit", 2024, "750000000", "duration"),
    ("us-gaap:OperatingIncomeLoss", 2024, "300000000", "duration"),
    ("us-gaap:NetIncomeLoss", 2023, "150000000", "duration"),
    ("us-gaap:NetIncomeLoss", 2024, "200000000", "duration"),
    ("us-gaap:NetCashProvidedByUsedInOperatingActivities", 2024, "400000000", "duration"),
    ("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", 2024, "100000000", "duration"),
    ("us-gaap:AssetsCurrent", 2024, "900000000", "instant"),
    ("us-gaap:LiabilitiesCurrent", 2024, "600000000", "instant"),
    ("us-gaap:StockholdersEquity", 2024, "800000000", "instant"),
    ("us-gaap:LongTermDebtNoncurrent", 2024, "300000000", "instant"),
    ("us-gaap:LongTermDebtCurrent", 2024, "100000000", "instant"),
    ("us-gaap:ResearchAndDevelopmentExpense", 2024, "125000000", "duration"),
]


def acme_facts() -> list[Fact]:
    out = []
    for concept, fy, value, ptype in _VALUES:
        start = f"{fy}-01-01" if ptype == "duration" else None
        end = f"{fy}-12-31"
        out.append(
            Fact(
                id=f"ACME|{concept}|USD|{start or ''}|{end}",
                ticker="ACME", cik=ACME.cik, concept=concept, label=concept.split(":")[1], value=value, unit="USD",
                period_type=ptype, start=start, end=end, fiscal_year=fy, accession=f"0009999999-{fy % 100 + 1:02d}-000001",
                form="10-K", filed=f"{fy + 1}-02-15",
            )
        )
    return out


def acme_chunks() -> list[Chunk]:
    texts = [
        ("item_1a", "Supply chain concentration", "We depend on a single-source supplier in Taiwan for our motion controllers. Any disruption at this supplier could delay robot shipments and increase our component costs."),
        ("item_1a", "Competition", "The industrial robotics market is intensely competitive, and larger competitors may reduce prices aggressively."),
        ("item_7", "Results of operations", "Revenue increased 25% in fiscal 2024, primarily driven by higher warehouse automation unit volumes and expanded service contracts."),
        ("notes", "Revenue recognition", "We recognize revenue when control of robots transfers to customers, generally upon delivery, and recognize service revenue ratably over the contract term."),
    ]
    return [
        Chunk(
            id=f"ACME-FY2024-{sec}-{i:04d}", ticker="ACME", cik=ACME.cik, fiscal_year=2024, accession="0009999999-25-000001",
            filing_date="2025-02-15", section=sec, section_title=sec, subsection=sub, text=txt, page_start=10 + i, page_end=10 + i,
            source_url="https://www.sec.gov/Archives/edgar/data/9999999/000999999925000001/acme-20241231.htm",
        )
        for i, (sec, sub, txt) in enumerate(texts)
    ]
