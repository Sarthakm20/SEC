"""Parse an EDGAR 10-K (inline XBRL HTML) into ordered, page-aware blocks.

A single document-order walk produces:
  * text / table blocks with physical page index (page breaks are <hr style="page-break-after">)
  * printed page labels recovered from page footers ("21" or "Apple Inc. | 2024 Form 10-K | 21")
  * Item sections (1, 1A, 7, 7A, Notes) — the table of contents repeats every heading, so for each
    item we keep the occurrence that yields the longest span
  * bold sub-headings (risk-factor titles, MD&A sub-sections) used as `subsection` metadata
  * inline-XBRL numeric facts with their page, table and row label, so every XBRL number can be
    traced to the exact rendered table cell in the filing
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "center", "blockquote"}
SKIP_TAGS = {"script", "style", "head", "title", "ix:header"}
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\xa0", " ").replace("​", "")).strip()


@dataclass
class Block:
    idx: int
    kind: str  # "text" | "table"
    text: str
    page: int  # physical page index, 1-based
    bold: bool = False
    rows: list[list[str]] | None = None  # for tables
    table_title: str | None = None
    boilerplate: bool = False  # repeated page header/footer


@dataclass
class IxFact:
    concept: str  # us-gaap:Revenues
    context_ref: str
    display: str
    scale: int
    sign: str | None
    page: int
    table_block: int | None
    table_fact_count: int
    row_label: str | None
    element_id: str | None


@dataclass
class Context:
    id: str
    start: str | None
    end: str | None
    instant: str | None
    dimensional: bool


@dataclass
class Section:
    key: str
    title: str
    start_block: int
    end_block: int  # exclusive


@dataclass
class ParsedDocument:
    blocks: list[Block]
    page_labels: dict[int, str]
    sections: dict[str, Section]
    ix_facts: list[IxFact] = field(default_factory=list)
    contexts: dict[str, Context] = field(default_factory=dict)

    def page_label(self, page: int | None) -> str | None:
        if page is None:
            return None
        return self.page_labels.get(page, str(page))


# --------------------------------------------------------------------------- helpers
def _is_page_break(tag: Tag) -> tuple[bool, bool]:
    """Return (break_before, break_after)."""
    style = (tag.get("style") or "").replace(" ", "").lower()
    before = "page-break-before:always" in style or "break-before:page" in style
    after = "page-break-after:always" in style or "break-after:page" in style
    return before, after


def _is_hidden(tag: Tag) -> bool:
    style = (tag.get("style") or "").replace(" ", "").lower()
    return "display:none" in style


def _has_block_child(tag: Tag) -> bool:
    for d in tag.descendants:
        if isinstance(d, Tag) and (d.name in BLOCK_TAGS or d.name == "table"):
            return True
    return False


def _is_bold(tag: Tag) -> bool:
    texty = [s for s in tag.find_all(string=True) if s.strip()]
    if not texty:
        return False
    for s in texty:
        el = s.parent
        bold = False
        while el is not None and el is not tag.parent:
            if el.name in ("b", "strong"):
                bold = True
                break
            st = (el.get("style") or "").replace(" ", "").lower() if isinstance(el, Tag) else ""
            if "font-weight:bold" in st or re.search(r"font-weight:(6|7|8|9)00", st):
                bold = True
                break
            if el is tag:
                break
            el = el.parent
        if not bold:
            return False
    return True


def _table_rows(table: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [_clean(td.get_text("")) for td in tr.find_all(["td", "th"])]
        merged: list[str] = []
        for c in cells:
            if not c:
                continue
            if merged and c in (")", "%", ")%", "%)"):
                merged[-1] += c
            elif merged and merged[-1] in ("$", "(", "$(", "($"):
                merged[-1] = merged[-1] + c
            else:
                merged.append(c)
        if merged:
            rows.append(merged)
    return rows


def table_to_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(r) for r in rows)


_FOOTER_NUM = re.compile(r"(?:^|\|\s*)(\d{1,3})\s*$")
_ITEM_RE = re.compile(
    r"^\s*item\s*(10|11|12|13|14|15|16|1a|1b|1c|1|2|3|4|5|6|7a|7|8|9a|9b|9c|9)(?![0-9a-z])\s*[\.:\-–—]?\s*(.*)$",
    re.I,
)
_NOTES_RE = re.compile(r"^\s*notes\s+to\s+(the\s+)?(consolidated\s+)?financial\s+statements\s*$", re.I)
_NOTES_END_RE = re.compile(
    r"^\s*(report\s+of\s+independent\s+registered\s+public\s+accounting\s+firm|schedule\s+ii\b|signatures\s*$|exhibit\s+index)",
    re.I,
)

WANTED_ITEMS = {
    "1": ("item_1", "Item 1. Business"),
    "1a": ("item_1a", "Item 1A. Risk Factors"),
    "7": ("item_7", "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations"),
    "7a": ("item_7a", "Item 7A. Quantitative and Qualitative Disclosures About Market Risk"),
}


# --------------------------------------------------------------------------- main parser
class _Walker:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.page = 1
        self.ix_facts: list[IxFact] = []

    def _emit_ix(self, el: Tag, table_block: int | None, table_count: int) -> None:
        for nf in el.find_all("ix:nonfraction"):
            row_label = None
            tr = nf.find_parent("tr")
            if tr is not None:
                for td in tr.find_all(["td", "th"]):
                    t = _clean(td.get_text(""))
                    if t and not re.fullmatch(r"[\$\(\)\d,.\-—–%\s]+", t):
                        row_label = t
                        break
            try:
                scale = int(nf.get("scale") or 0)
            except ValueError:
                scale = 0
            self.ix_facts.append(
                IxFact(
                    concept=nf.get("name", ""),
                    context_ref=nf.get("contextref", ""),
                    display=_clean(nf.get_text("")),
                    scale=scale,
                    sign=nf.get("sign"),
                    page=self.page,
                    table_block=table_block,
                    table_fact_count=table_count,
                    row_label=row_label,
                    element_id=nf.get("id"),
                )
            )

    def walk(self, node: Tag) -> None:
        pending_text: list[str] = []

        def flush() -> None:
            t = _clean("".join(pending_text))
            pending_text.clear()
            if t:
                self.blocks.append(Block(idx=len(self.blocks), kind="text", text=t, page=self.page))

        for child in node.children:
            if isinstance(child, NavigableString):
                if child.strip():
                    pending_text.append(str(child))
                continue
            if not isinstance(child, Tag) or child.name in SKIP_TAGS:
                continue
            if _is_hidden(child):
                continue
            before, after = _is_page_break(child)
            if before and self.blocks:
                flush()
                self.page += 1
            if child.name == "hr":
                # a bare <hr> is a visual rule; only a styled page-break advances the page
                flush()
                if after:
                    self.page += 1
                continue
            if child.name == "table":
                flush()
                rows = _table_rows(child)
                n_facts = len(child.find_all("ix:nonfraction"))
                if rows:
                    blk = Block(
                        idx=len(self.blocks), kind="table", text=table_to_text(rows), page=self.page, rows=rows
                    )
                    self.blocks.append(blk)
                    self._emit_ix(child, blk.idx, n_facts)
                else:
                    self._emit_ix(child, None, n_facts)
            elif child.name in BLOCK_TAGS and not _has_block_child(child):
                flush()
                text = _clean(child.get_text(""))
                if text:
                    self.blocks.append(
                        Block(idx=len(self.blocks), kind="text", text=text, page=self.page, bold=_is_bold(child))
                    )
                self._emit_ix(child, None, 0)
            elif child.name in BLOCK_TAGS or child.name in ("body", "html", "span", "font", "ix:nonnumeric", "a", "ix:continuation", "section"):
                if child.name in ("span", "font", "a") and not _has_block_child(child):
                    pending_text.append(child.get_text(""))
                    self._emit_ix(child, None, 0)
                else:
                    flush()
                    self.walk(child)
            else:
                if _has_block_child(child):
                    flush()
                    self.walk(child)
                else:
                    pending_text.append(child.get_text(""))
                    self._emit_ix(child, None, 0)
            if after and child.name != "hr":
                flush()
                self.page += 1
        flush()


def _page_labels(blocks: list[Block]) -> dict[int, str]:
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    labels: dict[int, str] = {}
    for page, bl in by_page.items():
        for b in reversed(bl[-3:]):
            if b.kind != "text" or len(b.text) > 80:
                continue
            m = _FOOTER_NUM.search(b.text)
            if m:
                labels[page] = m.group(1)
                break
    return labels


def _detect_sections(blocks: list[Block]) -> dict[str, Section]:
    heads: list[tuple[int, str]] = []  # (block idx, item code)
    for b in blocks:
        if b.kind != "text" or len(b.text) > 250 or b.boilerplate:
            continue
        m = _ITEM_RE.match(b.text)
        if m:
            heads.append((b.idx, m.group(1).lower()))
    sections: dict[str, Section] = {}
    for code, (key, title) in WANTED_ITEMS.items():
        best: tuple[int, int, int] | None = None  # (chars, start, end)
        for pos, (start, c) in enumerate(heads):
            if c != code:
                continue
            end = len(blocks)
            for start2, c2 in heads[pos + 1 :]:
                if c2 != code:
                    end = start2
                    break
            chars = sum(len(blocks[i].text) for i in range(start, end))
            if best is None or chars > best[0]:
                best = (chars, start, end)
        if best and best[0] > 500:
            sections[key] = Section(key=key, title=title, start_block=best[1] + 1, end_block=best[2])

    # Notes to consolidated financial statements
    notes_best: tuple[int, int, int] | None = None
    for b in blocks:
        if b.kind == "text" and _NOTES_RE.match(b.text):
            end = len(blocks)
            for b2 in blocks[b.idx + 1 :]:
                if b2.kind != "text" or len(b2.text) > 250 or b2.boilerplate:
                    continue
                if _NOTES_END_RE.match(b2.text) or _ITEM_RE.match(b2.text):
                    end = b2.idx
                    break
            chars = sum(len(blocks[i].text) for i in range(b.idx, end))
            if notes_best is None or chars > notes_best[0]:
                notes_best = (chars, b.idx, end)
    if notes_best and notes_best[0] > 2000:
        sections["notes"] = Section(
            key="notes",
            title="Notes to Consolidated Financial Statements",
            start_block=notes_best[1] + 1,
            end_block=notes_best[2],
        )
    return sections


def _contexts(soup: BeautifulSoup) -> dict[str, Context]:
    out: dict[str, Context] = {}
    for ctx in soup.find_all("xbrli:context"):
        cid = ctx.get("id")
        if not cid:
            continue

        def _t(name: str) -> str | None:
            el = ctx.find(name)
            return _clean(el.get_text()) if el else None

        out[cid] = Context(
            id=cid,
            start=_t("xbrli:startdate"),
            end=_t("xbrli:enddate"),
            instant=_t("xbrli:instant"),
            dimensional=ctx.find("xbrli:segment") is not None,
        )
    return out


_STATEMENT_TITLE = re.compile(
    r"(consolidated|condensed)?\s*(statements?\s+of|balance\s+sheets?)|summary|reconciliation|segment", re.I
)
_UNITS_LINE = re.compile(r"^\(?\s*in\s+(millions|thousands|billions)", re.I)


def _attach_table_titles(blocks: list[Block]) -> None:
    for b in blocks:
        if b.kind != "table":
            continue
        fallback: str | None = None
        for j in range(b.idx - 1, max(b.idx - 8, -1), -1):
            prev = blocks[j]
            if prev.kind == "table":
                break
            t = prev.text
            if not (3 < len(t) <= 150) or t.endswith(".") or _UNITS_LINE.match(t):
                continue
            if re.fullmatch(r"[\d\s|]+", t) or "form 10-k" in t.lower():
                continue
            if _STATEMENT_TITLE.search(t):
                b.table_title = t
                break
            if fallback is None and (prev.bold or t.isupper()):
                fallback = t
        if b.table_title is None:
            b.table_title = fallback


def _mark_boilerplate(blocks: list[Block]) -> None:
    """Flag running headers/footers: short lines that recur on many pages (digits normalized)."""
    counts: dict[str, set[int]] = {}
    for b in blocks:
        if b.kind == "text" and len(b.text) <= 120:
            key = re.sub(r"\d+", "#", b.text.lower())
            counts.setdefault(key, set()).add(b.page)
    for b in blocks:
        if b.kind == "text" and len(b.text) <= 120:
            key = re.sub(r"\d+", "#", b.text.lower())
            if len(counts[key]) >= 5 or re.fullmatch(r"#", key):
                b.boilerplate = True


def _decode(html: bytes | str) -> str:
    """Decode ourselves: filings often declare encoding='ASCII' while using numeric entities such as
    &#8217;, which lxml then cannot represent and replaces with U+FFFD."""
    if isinstance(html, bytes):
        try:
            text = html.decode("utf-8")
        except UnicodeDecodeError:
            text = html.decode("cp1252", errors="replace")
    else:
        text = html
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)


def parse_10k_html(html: bytes | str) -> ParsedDocument:
    soup = BeautifulSoup(_decode(html), "lxml")
    contexts = _contexts(soup)
    for t in soup.find_all(SKIP_TAGS):
        t.decompose()
    walker = _Walker()
    root = soup.body or soup
    walker.walk(root)
    blocks = walker.blocks
    _attach_table_titles(blocks)
    _mark_boilerplate(blocks)
    return ParsedDocument(
        blocks=blocks,
        page_labels=_page_labels(blocks),
        sections=_detect_sections(blocks),
        ix_facts=walker.ix_facts,
        contexts=contexts,
    )
