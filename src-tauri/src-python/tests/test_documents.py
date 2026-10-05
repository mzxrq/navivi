import zipfile

import pytest

from services import documents
from services.documents import MAX_CHARS, read_document

DOCX_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    "<w:p><w:r><w:t>葛城修験</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>First</w:t></w:r><w:r><w:tab/><w:t>second</w:t></w:r></w:p>"
    "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Place</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Temple</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    "</w:body></w:document>"
)


def _docx(path, body=DOCX_BODY):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", body)
    return str(path)


def test_docx_paragraphs_and_tables(tmp_path):
    result = read_document(_docx(tmp_path / "trip.docx"))
    assert result["success"] and not result["truncated"]
    assert result["text"].splitlines() == ["葛城修験", "First\tsecond", "Place | Temple"]


def test_broken_docx_is_a_clean_error(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a zip")
    result = read_document(str(bad))
    assert not result["success"] and "docx" in result["error"]


def test_text_falls_back_to_cp932(tmp_path):
    f = tmp_path / "memo.txt"
    f.write_bytes("白浜の海".encode("cp932"))
    assert read_document(str(f))["text"] == "白浜の海"


def test_long_text_is_cut_and_flagged(tmp_path):
    f = tmp_path / "long.md"
    f.write_text("a" * (MAX_CHARS + 500), encoding="utf-8")
    result = read_document(str(f))
    assert result["truncated"] and len(result["text"]) == MAX_CHARS


def test_unknown_missing_and_empty(tmp_path):
    exe = tmp_path / "a.exe"
    exe.write_bytes(b"x")
    assert "Unsupported" in read_document(str(exe))["error"]
    assert "not found" in read_document(str(tmp_path / "nope.txt"))["error"]
    empty = tmp_path / "e.txt"
    empty.write_text("  \n", encoding="utf-8")
    assert not read_document(str(empty))["success"]


def test_pdf_text(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (Hello pilgrim route) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    f = tmp_path / "t.pdf"
    with open(f, "wb") as fh:
        writer.write(fh)
    result = read_document(str(f))
    assert result["success"] and result["pages"] == 1 and "Hello pilgrim route" in result["text"]


def test_not_a_pdf(tmp_path):
    pytest.importorskip("pypdf")
    f = tmp_path / "x.pdf"
    f.write_bytes(b"nope")
    assert "PDF" in read_document(str(f))["error"]


def test_extension_sets():
    assert {".pdf", ".docx", ".txt", ".md"} <= documents.DOCUMENT_EXTENSIONS
