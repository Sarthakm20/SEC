"""Cross-check gold-set reported values against SEC XBRL facts, independently of the QA pipeline.

For every expected USD / per-share value, search all us-gaap facts of that company and fiscal year for
an exact match. Derived values (percent / ratio) are listed for manual formula review. This guards the
benchmark against transcription errors without grading the system against its own metric mapping.

  python -m evaluation.crosscheck_gold

The summary is also written to evaluation/results/gold_crosscheck.json (served at /api/eval/gold), together
with a SHA-256 of the gold file so the UI can tell when the gold set changed after the last check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.db import repo

GOLD = Path(__file__).parent / "gold" / "questions.jsonl"
RESULT = Path(__file__).parent / "results" / "gold_crosscheck.json"


def gold_sha256(gold: Path = GOLD) -> str:
    return hashlib.sha256(gold.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, default=GOLD)
    gold = ap.parse_args().gold.resolve()
    # the main set's result feeds /api/eval/gold; other sets get their own file
    result = RESULT if gold == GOLD.resolve() else RESULT.with_name(f"{gold.stem}_crosscheck.json")
    items = [json.loads(line) for line in gold.read_text(encoding="utf-8").splitlines() if line.strip()]
    facts_by_ticker = {}
    ok = bad = derived = 0
    mismatches: list[dict] = []
    for it in items:
        checks = []
        for exp in it.get("expected") or []:
            if exp.get("derived"):
                derived += 1
                print(f"  [derived ] {it['id']} {exp['label']}: {exp['value']} — components checked below; formula: {it.get('source', '')}")
                checks.extend(exp.get("components", []))
            else:
                checks.append(exp)
        for exp in checks:
            unit = exp["unit"]
            if unit not in ("USD", "USD/shares"):
                derived += 1
                print(f"  [derived ] {it['id']} {exp['label']}: {exp['value']} {unit} — verify formula: {it.get('source', '')}")
                continue
            tickers = [t for t in it["tickers"] if t in exp["label"]] or it["tickers"]
            years = [int(y) for y in __import__("re").findall(r"FY(\d{4})", exp["label"])] or it["fiscal_years"]
            target = Decimal(str(exp["value"]))
            hits = []
            for t in tickers:
                if t not in facts_by_ticker:
                    facts_by_ticker[t] = repo.load_facts(t)
                for f in facts_by_ticker[t]:
                    if f.fiscal_year in years and f.concept.startswith("us-gaap:") and Decimal(f.value) == target:
                        hits.append(f"{f.concept} FY{f.fiscal_year}")
            if hits:
                ok += 1
                print(f"  [match   ] {it['id']} {exp['label']}: {exp['value']} ↔ {hits[0]}")
            else:
                bad += 1
                mismatches.append({"question_id": it["id"], "label": exp["label"], "value": str(exp["value"]), "tickers": tickers, "fiscal_years": years})
                print(f"  [MISMATCH] {it['id']} {exp['label']}: {exp['value']} not found among XBRL facts for {tickers} FY{years}")
    print(f"\nreported values matched: {ok}, mismatched: {bad}, derived values needing formula review: {derived}")

    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "questions": len(items),
                "reported_checked": ok + bad,
                "matched": ok,
                "mismatched": bad,
                "derived_for_review": derived,
                "mismatches": mismatches,
                "gold_file": gold.name,
                "gold_sha256": gold_sha256(gold),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"summary written to {result}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
