"""Structure-aware chunking of 10-K narrative sections.

* Chunks never cross section boundaries and prefer to break at sub-headings (risk-factor titles,
  MD&A sub-sections), which are carried as `subsection` metadata.
* Tables become their own chunks (kind="table") with the header row repeated when split, so row
  semantics are preserved instead of being shredded across text chunks.
* Every chunk keeps page range, accession and source URL for evidence-aware citations.
"""

from __future__ import annotations

import re

from app.ingest.html_parser import Block, ParsedDocument, table_to_text
from app.models import SECTION_TITLES, Chunk, Company, Filing
from app.security.injection import scan


def approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3) + 1


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"“])")


def _tail_overlap(text: str, overlap_tokens: int) -> str:
    if overlap_tokens <= 0:
        return ""
    sentences = _SENT_SPLIT.split(text)
    out: list[str] = []
    total = 0
    for s in reversed(sentences):
        total += approx_tokens(s)
        if total > overlap_tokens and out:
            break
        out.insert(0, s)
        if total > overlap_tokens:
            break
    return " ".join(out)


def _is_subheading(b: Block) -> bool:
    return b.kind == "text" and b.bold and 3 <= len(b.text) <= 400 and not b.text.isdigit()


def _split_long(text: str, target: int) -> list[str]:
    if approx_tokens(text) <= target * 1.5:
        return [text]
    parts: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    for s in _SENT_SPLIT.split(text):
        t = approx_tokens(s)
        if cur and cur_tok + t > target:
            parts.append(" ".join(cur))
            cur, cur_tok = [], 0
        cur.append(s)
        cur_tok += t
    if cur:
        parts.append(" ".join(cur))
    return parts


def chunk_document(
    doc: ParsedDocument,
    filing: Filing,
    company: Company,
    target_tokens: int = 350,
    overlap_tokens: int = 50,
    sections: tuple[str, ...] = ("item_1", "item_1a", "item_7", "item_7a", "notes"),
) -> list[Chunk]:
    chunks: list[Chunk] = []

    def make(section: str, subsection: str | None, text: str, kind: str, pages: list[int], table_id: str | None = None) -> None:
        labels = [doc.page_label(p) for p in pages if p is not None]
        nums = [int(l) for l in labels if l and l.isdigit()]
        cid = f"{company.ticker}-FY{filing.fiscal_year}-{section}-{len(chunks):04d}"
        chunks.append(
            Chunk(
                id=cid,
                ticker=company.ticker,
                cik=company.cik,
                fiscal_year=filing.fiscal_year,
                accession=filing.accession,
                filing_date=filing.filing_date,
                section=section,
                section_title=SECTION_TITLES.get(section, section),
                subsection=subsection,
                kind=kind,  # type: ignore[arg-type]
                table_id=table_id,
                text=text,
                page_start=min(nums) if nums else None,
                page_end=max(nums) if nums else None,
                source_url=filing.url,
                injection_flags=scan(text),
            )
        )

    for key in sections:
        sec = doc.sections.get(key)
        if sec is None:
            continue
        subsection: str | None = None
        buf: list[str] = []
        buf_pages: list[int] = []
        buf_tokens = 0

        def flush(carry: bool) -> None:
            nonlocal buf, buf_pages, buf_tokens
            if not buf:
                return
            text = " ".join(buf).strip()
            if approx_tokens(text) >= 25:
                make(key, subsection, text, "text", buf_pages)
            if carry:
                tail = _tail_overlap(text, overlap_tokens)
                buf, buf_pages, buf_tokens = ([tail] if tail else []), buf_pages[-1:], approx_tokens(tail) if tail else 0
            else:
                buf, buf_pages, buf_tokens = [], [], 0

        for b in doc.blocks[sec.start_block : sec.end_block]:
            if b.boilerplate:
                continue
            if b.kind == "table":
                rows = b.rows or []
                if not rows or sum(len(r) for r in rows) < 2:
                    continue  # layout-only table
                header, body = (rows[0], rows[1:]) if len(rows) > 1 else ([], rows)
                pieces: list[list[list[str]]] = []
                cur: list[list[str]] = []
                for r in body:
                    cur.append(r)
                    if approx_tokens(table_to_text(([header] if header else []) + cur)) > target_tokens * 1.5:
                        pieces.append(cur)
                        cur = []
                if cur:
                    pieces.append(cur)
                for i, piece in enumerate(pieces):
                    title = b.table_title or subsection or ""
                    body_text = table_to_text(([header] if header else []) + piece)
                    text = f"{title}\n{body_text}".strip() if title else body_text
                    make(key, subsection, text, "table", [b.page], table_id=f"T{b.idx}" + (f".{i+1}" if len(pieces) > 1 else ""))
                continue
            if _is_subheading(b) and len(b.text) <= 400:
                if buf_tokens > 60:
                    flush(carry=False)
                subsection = b.text
                continue
            for piece in _split_long(b.text, target_tokens):
                t = approx_tokens(piece)
                if buf and buf_tokens + t > target_tokens:
                    flush(carry=True)
                buf.append(piece)
                buf_pages.append(b.page)
                buf_tokens += t
        flush(carry=False)
    return chunks


def index_text(chunk: Chunk) -> str:
    """Text that is embedded / BM25-indexed: a contextual header + the passage."""
    parts = [f"{chunk.ticker} FY{chunk.fiscal_year} 10-K", chunk.section_title]
    if chunk.subsection:
        parts.append(chunk.subsection)
    return " — ".join(parts) + "\n" + chunk.text
