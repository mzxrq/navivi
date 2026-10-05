"""Plain text out of a document the user attached to the assistant (PDF, Word, text).

[NOTE] [Assistant] Everything is read on this PC. .docx needs no library (it is a zip of XML); .pdf uses pypdf.
"""

from __future__ import annotations

import re
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


def _pdf_text(path: Path) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("Reading PDFs needs the pypdf package, which is not installed.") from exc
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("This PDF is password protected.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("This is not a readable PDF file.") from exc
    return "\n\n".join(pages), len(pages)


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
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
