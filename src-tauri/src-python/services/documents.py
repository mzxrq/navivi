"""Plain text out of a document the user attached to the assistant (PDF, Word, text).

[NOTE] [Assistant] Everything is read on this PC. .docx needs no library (it is a zip of XML); .pdf uses pypdf.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Dict
from xml.etree import ElementTree

MAX_CHARS = 60_000
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv"}
DOCUMENT_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _paragraph_text(p: ElementTree.Element) -> str:
    parts = []
    for node in p.iter():
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("This is not a readable Word (.docx) file.") from exc
    body = root.find(f"{_W}body")
    lines = []
    for block in body if body is not None else []:
        if block.tag == f"{_W}p":
            lines.append(_paragraph_text(block))
        elif block.tag == f"{_W}tbl":
            for row in block.iter(f"{_W}tr"):
                cells = [" ".join(_paragraph_text(p) for p in cell.iter(f"{_W}p")).strip() for cell in row.findall(f"{_W}tc")]
                lines.append(" | ".join(c for c in cells if c))
    return "\n".join(lines)


# ── Layout-aware PDF reading ──
# [NOTE] [Assistant] pypdf's plain extract_text() returns text in the order the file stores it. A brochure or map sheet
# stores its map labels first and the story column later, so a model reading it lists "Fujito Tunnel" and "Pay attention
# to the fork" as places. Here every text fragment keeps its position: long lines that line up form columns of prose
# (read top to bottom, left to right, indents start paragraphs); everything else (map labels, legends, captions) goes in
# a separate section that says it is not in travel order.

PROSE_MIN_CHARS = 35  # a line this long is a sentence, not a label
COLUMN_MIN_LINES = 3  # fewer aligned prose lines than this is a caption, not a column
COLUMN_X_TOLERANCE = 12.0  # a paragraph indent is smaller than this: it stays in the column
SECTION_LABELS = "[labels and captions on the page: not in travel order]"
SECTION_TEXT = "[text]"
SECTION_TIMES = "[course times: stop -> time -> stop]"


def _decode_shifted(text: str) -> str:
    """Some PDF fonts store every glyph 31 below its character code (space is 0x01): undo it for fragments that show it."""
    if not any(ord(c) < 0x20 and c not in "\n\r\t" for c in text):
        return text
    return "".join(c if c in "\n\r\t" else chr(ord(c) + 31) for c in text)


def _clean_fragment(text: str) -> str:
    text = _decode_shifted(text).encode("utf-8", "ignore").decode("utf-8").replace("\n", " ").strip()
    text = re.sub(r"\s{2,}", " ", text)
    half, odd = divmod(len(text), 2)
    if not odd and half >= 3 and text[:half] == text[half:]:
        text = text[:half]  # a label drawn twice (a drop shadow): "Kyoshi Sta.Kyoshi Sta."
    return text


_READABLE_SCRIPTS = ("LATIN", "CJK", "HIRAGANA", "KATAKANA", "FULLWIDTH LATIN", "HALFWIDTH KATAKANA")


def _is_readable_letter(c: str) -> bool:
    if not c.isalpha():
        return False
    try:
        return unicodedata.name(c).startswith(_READABLE_SCRIPTS) and unicodedata.category(c) != "Lm"
    except ValueError:
        return False


def _looks_garbled(text: str) -> bool:
    letters = [c for c in text if _is_readable_letter(c)]
    odd = [c for c in text if not (c.isalnum() or c in " .,-'()/&:;!?\u201c\u201d\u2019*")]
    return bool(text) and (not letters or len(odd) > len(text) / 3)


_TIME = re.compile(r"^(?:\d+\s*(?:hours?|hrs?|minutes?|mins?|h|min|時間|分)\.?\s*)+$", re.IGNORECASE)
_NOT_A_STOP = {"START", "GOAL", "COURSE TIMES"}


def _center(item: dict) -> float:
    return item["x"] + len(item["text"]) * item["size"] * 0.27


def _course_times(items: list[dict]) -> tuple[list[str], set[int]]:
    """A "Course Times" box (stop, minutes, stop, minutes...) drawn as columns: its text fragments are scattered in the
    file, but their positions give the chain back. Returns (["A -> 15 min. -> B -> ..."], ids of the items used) or ([], set())."""
    times = sorted((i for i in items if _TIME.match(i["text"])), key=lambda i: -i["y"])
    if len(times) < 3:
        return [], set()
    # "1 hr." and "20 min." stacked at the same x are one duration
    merged: list[dict] = []
    for t in times:
        last = next((m for m in merged if abs(m["x"] - t["x"]) <= 3 and 0 < m["y_low"] - t["y"] <= 12), None)
        if last:
            last["text"] += " " + t["text"]
            last["y_low"] = t["y"]
            last["ids"].append(id(t))
        else:
            merged.append({"text": t["text"], "x": t["x"], "y": t["y"], "y_low": t["y"], "size": t["size"], "ids": [id(t)]})
    for m in merged:
        m["cx"] = _center(m)

    groups: list[list[dict]] = []
    for m in sorted(merged, key=lambda m: m["cx"]):
        if groups and m["cx"] - groups[-1][-1]["cx"] <= 25:
            groups[-1].append(m)
        else:
            groups.append([m])
    # a column's durations share one font size: a stray total elsewhere ("4 hours 10 minutes" in the stats box) does not
    groups = [[m for m in g if abs(m["size"] - sorted(x["size"] for x in g)[len(g) // 2]) <= 0.3] for g in groups]
    columns = [g for g in groups if len(g) >= 2]
    bridges = [m for g in groups if len(g) < 2 for m in g]
    if not columns:
        return [], set()

    used: set[int] = set()
    chains: list[list[str]] = []
    centers: list[float] = []
    for col in columns:
        cx = sum(m["cx"] for m in col) / len(col)
        top, bottom = max(m["y"] for m in col) + 40, min(m["y_low"] for m in col) - 40
        nodes = [
            i for i in items
            if not _TIME.match(i["text"]) and i["text"].upper() not in _NOT_A_STOP and len(i["text"]) <= 40
            and abs(_center(i) - cx) <= 45 and bottom <= i["y"] <= top
        ]
        events = [("node", n["y"], n["text"], [id(n)]) for n in nodes] + [("time", m["y"], m["text"], m["ids"]) for m in col]
        events.sort(key=lambda e: -e[1])
        while events and events[0][0] == "time":
            events.pop(0)
        while events and events[-1][0] == "time":
            events.pop()
        if not any(e[0] == "node" for e in events):
            continue
        chains.append([e[2] for e in events])
        centers.append(cx)
        for e in events:
            used.update(e[3])
    if not chains:
        return [], set()

    line: list[str] = []
    for k, chain in enumerate(chains):
        if k:
            between = [b for b in bridges if centers[k - 1] < b["cx"] < centers[k]]
            if between:
                line.append(between[0]["text"])
                used.update(between[0]["ids"])
        line.extend(chain)
    return [" -> ".join(line)], used


def _layout_text(fragments: list[tuple[str, float, float, float]]) -> str:
    """(text, x, y, size) of one page -> reading-order text, or "" when the page has no columns of prose."""
    items = []
    for raw, x, y, size in fragments:
        text = _clean_fragment(raw)
        if text and not _looks_garbled(text):
            items.append({"text": text, "x": x, "y": y, "size": size or 1.0})
    prose = sorted((i for i in items if len(i["text"]) >= PROSE_MIN_CHARS), key=lambda i: i["x"])

    columns: list[list[dict]] = []
    for item in prose:
        for col in columns:
            if abs(item["x"] - min(i["x"] for i in col)) <= COLUMN_X_TOLERANCE:
                col.append(item)
                break
        else:
            columns.append([item])
    columns = [c for c in columns if len(c) >= COLUMN_MIN_LINES]
    if not columns:
        return ""
    columns.sort(key=lambda c: min(i["x"] for i in c))

    used: set[int] = set()
    parts: list[str] = [SECTION_TEXT]
    for col in columns:
        left = min(i["x"] for i in col)
        top, bottom = max(i["y"] for i in col), min(i["y"] for i in col)
        pitch = sorted(abs(a["y"] - b["y"]) for a, b in zip(col, col[1:]))
        gap = (pitch[len(pitch) // 2] if pitch else 10.0) * 1.8
        # short lines that start at the column's left edge inside its vertical span are its headings and bullets; a
        # label further right is on the map, even where the box would reach it
        members = list(col) + [
            i for i in items
            if id(i) not in {id(c) for c in col} and abs(i["x"] - left) <= COLUMN_X_TOLERANCE and bottom - gap <= i["y"] <= top + gap and len(i["text"]) < PROSE_MIN_CHARS
        ]
        members.sort(key=lambda i: (-round(i["y"], 1), i["x"]))
        paragraph: list[str] = []
        last_y = None
        for i in members:
            used.add(id(i))
            new_paragraph = last_y is not None and (last_y - i["y"] > gap or i["x"] - left > 5)
            if new_paragraph and paragraph:
                parts.append(" ".join(paragraph))
                paragraph = []
            paragraph.append(i["text"])
            last_y = i["y"]
        if paragraph:
            parts.append(" ".join(paragraph))

    time_lines, time_ids = _course_times(items)
    used |= time_ids
    if time_lines:
        parts.append(SECTION_TIMES)
        parts.extend(time_lines)

    labels = sorted((i for i in items if id(i) not in used), key=lambda i: (-round(i["y"] / 20), i["x"]))
    seen: set[str] = set()
    label_lines = []
    for i in labels:
        key = i["text"].lower()
        if key not in seen:
            seen.add(key)
            label_lines.append(i["text"])
    if label_lines:
        parts.append(SECTION_LABELS)
        parts.extend(label_lines)
    return "\n".join(parts)


def _page_layout_text(page) -> str:
    fragments: list[tuple[str, float, float, float]] = []

    def visit(text, cm, tm, _font, font_size):
        if not text or not text.strip():
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        scale = max(abs(tm[0] * cm[0] + tm[1] * cm[2]), abs(tm[2] * cm[1] + tm[3] * cm[3]))
        fragments.append((text, x, y, (font_size or 1.0) * scale))

    try:
        page.extract_text(visitor_text=visit)
        return _layout_text(fragments)
    except Exception:
        return ""


def _pdf_text(path: Path) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("Reading PDFs needs the pypdf package, which is not installed.") from exc
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("This PDF is password protected.")
        pages = []
        for page in reader.pages:
            plain = page.extract_text() or ""
            layout = _page_layout_text(page)
            # the layout reading is only trusted when it kept most of the text
            pages.append(layout if layout and len(layout) >= 0.6 * len(plain) else plain)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("This is not a readable PDF file.") from exc
    return "\n\n".join(pages), len(pages)


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = text.encode("utf-8", "ignore").decode("utf-8")  # lone surrogates from broken PDF fonts would break the JSON reply
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def read_document(path: str) -> Dict[str, Any]:
    """{"success": True, "text", "pages", "truncated"} or {"success": False, "error"}."""
    file = Path(path)
    if not file.is_file():
        return {"success": False, "error": f"File not found: {file.name or path}"}
    extension = file.suffix.lower()
    if extension not in DOCUMENT_EXTENSIONS:
        return {"success": False, "error": f"Unsupported file type: {extension or file.name}"}
    try:
        pages = 1
        if extension == ".pdf":
            text, pages = _pdf_text(file)
        elif extension == ".docx":
            text = _docx_text(file)
        else:
            text = _decode(file.read_bytes())
    except (ValueError, OSError) as exc:
        return {"success": False, "error": str(exc)}
    text = _tidy(text)
    if not text:
        return {"success": False, "error": "No text could be read from this file (a scanned PDF has none)."}
    truncated = len(text) > MAX_CHARS
    return {"success": True, "text": text[:MAX_CHARS], "pages": pages, "truncated": truncated}
