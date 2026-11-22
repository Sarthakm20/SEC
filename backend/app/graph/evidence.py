"""Evidence registry: assigns stable F#/C#/S# ids that answers cite and the auditor validates."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.finance.engine import MetricResult
from app.models import CalculationRecord, Fact, RetrievedChunk


@dataclass
class EvidenceSet:
    facts: dict[str, Fact] = field(default_factory=dict)
    calcs: dict[str, CalculationRecord] = field(default_factory=dict)
    passages: dict[str, RetrievedChunk] = field(default_factory=dict)
    _fact_ids: dict[str, str] = field(default_factory=dict)
    _calc_ids: dict[str, str] = field(default_factory=dict)
    _chunk_ids: dict[str, str] = field(default_factory=dict)

    def add_fact(self, f: Fact) -> str:
        if f.id not in self._fact_ids:
            eid = f"F{len(self.facts) + 1}"
            self._fact_ids[f.id] = eid
            self.facts[eid] = f
        return self._fact_ids[f.id]

    def add_calc(self, c: CalculationRecord) -> str:
        if c.id not in self._calc_ids:
            eid = f"C{len(self.calcs) + 1}"
            self._calc_ids[c.id] = eid
            self.calcs[eid] = c.model_copy(update={"evidence_id": eid})
            for inp in self.calcs[eid].inputs:
                if inp.fact_id and inp.fact_id in self._fact_ids:
                    inp.evidence_id = self._fact_ids[inp.fact_id]
        return self._calc_ids[c.id]

    def add_passage(self, rc: RetrievedChunk) -> str:
        if rc.chunk.id not in self._chunk_ids:
            eid = f"S{len(self.passages) + 1}"
            self._chunk_ids[rc.chunk.id] = eid
            self.passages[eid] = rc.model_copy(update={"evidence_id": eid})
        return self._chunk_ids[rc.chunk.id]

    def add_result(self, r: MetricResult) -> list[str]:
        """Register a metric result's facts and calculation; returns the ids that support it."""
        ids = [self.add_fact(f) for f in r.input_facts]
        if r.calculation is not None:
            ids.insert(0, self.add_calc(r.calculation))
        return ids

    def fact_eid(self, fact: Fact) -> str | None:
        return self._fact_ids.get(fact.id)

    def calc_eid(self, rec: CalculationRecord) -> str | None:
        return self._calc_ids.get(rec.id)

    def is_empty(self) -> bool:
        return not (self.facts or self.calcs or self.passages)
