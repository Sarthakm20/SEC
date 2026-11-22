"""Prompt-injection isolation for retrieved document content (Recommendations §4.5).

Document text is *data*, never instructions. Defenses:
  1. Ingestion-time scan flags passages containing instruction-like patterns (stored on the chunk).
  2. At synthesis time, evidence is wrapped in clearly delimited <evidence> blocks; any delimiter-like
     sequences inside document text are neutralized so a passage cannot "close" its block.
  3. The system prompt states that evidence content cannot change instructions, and the verification
     layer (not the LLM) decides what numbers and citations are acceptable — so a successful
     injection still cannot introduce unverified numbers or fabricated citations.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions", re.compile(r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)", re.I)),
    ("role_override", re.compile(r"\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be)\b.{0,40}\b(assistant|ai|model|system)\b", re.I)),
    ("system_prompt_probe", re.compile(r"\b(system\s+prompt|developer\s+message|hidden\s+instructions)\b", re.I)),
    ("tag_injection", re.compile(r"</?\s*(system|assistant|user|evidence|instructions?)\s*>", re.I)),
    ("tool_call", re.compile(r"\b(call|invoke|execute)\s+(the\s+)?(tool|function|command)\b", re.I)),
    ("exfiltration", re.compile(r"\b(send|post|upload)\b.{0,30}\b(api[\s_-]?key|password|credentials|token)\b", re.I)),
]


def scan(text: str) -> list[str]:
    return [name for name, pat in _PATTERNS if pat.search(text)]


_DELIMS = re.compile(r"</?\s*(evidence|system|assistant|user|instructions?|document)[^>]*>", re.I)


def neutralize(text: str) -> str:
    """Make document text safe to embed inside <evidence> delimiters."""
    return _DELIMS.sub(lambda m: m.group(0).replace("<", "‹").replace(">", "›"), text)


def wrap_evidence(evidence_id: str, header: str, body: str) -> str:
    return f'<evidence id="{evidence_id}">\n{neutralize(header)}\n---\n{neutralize(body)}\n</evidence>'
