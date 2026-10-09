import zipfile

import pytest

from services import documents
from services.documents import MAX_CHARS, SECTION_LABELS, SECTION_TIMES, _decode_shifted, _layout_text, read_document

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


def _line(text, x, y, size=7.0):
    return (text, x, y, size)


def test_layout_separates_the_story_column_from_map_labels():
    story = [
        _line("Leave Kyoshi Station, turn left and follow the railroad tracks to the crossing.", 22.7, 400),
        _line("Cross it and follow the signpost for the Kyoshi Kannon up to the temple gate here.", 22.7, 391),
        _line("The trail begins to the right of the main hall and climbs straight to the peak.", 22.7, 382),
        _line("Proceeding from the temple, you will come to a well-lit road by the river bank.", 31.2, 360),
        _line("After passing the pond you will arrive at the bus stop at the end of the course.", 22.7, 351),
    ]
    labels = [_line("Fujito Tunnel", 500, 395), _line("Pay attention", 640, 380), _line("Mt. Takano", 300, 370), _line("Kyoshi Sta.Kyoshi Sta.", 90, 300)]
    text = _layout_text(labels[:2] + story + labels[2:])
    body, _, label_part = text.partition(SECTION_LABELS)
    assert body.index("Leave Kyoshi Station") < body.index("Proceeding from the temple") < body.index("After passing the pond")
    assert "Proceeding from the temple" in body.split("\n")[2], "an indented line starts a new paragraph"
    assert "Fujito Tunnel" not in body and "Fujito Tunnel" in label_part
    assert "Kyoshi Sta.Kyoshi Sta." not in label_part and "Kyoshi Sta." in label_part


def test_layout_keeps_a_heading_with_its_column_and_two_columns_in_order():
    left = [_line("The first column says where the walk starts and what the road looks like.", 20, 500 - 9 * i) for i in range(3)]
    right = [_line("The second column continues with the temple and how the mountain path goes.", 300, 500 - 9 * i) for i in range(3)]
    text = _layout_text([_line("Course", 20, 512)] + right + left)
    assert text.index("Course") < text.index("first column") < text.index("second column")


def test_layout_gives_up_on_a_page_without_prose():
    assert _layout_text([_line("A", 10, 10), _line("B", 50, 50)]) == ""


def test_shifted_font_text_is_decoded():
    assert _decode_shifted("\x01UPVS\x01PG\x01") == " tour of "
    assert _decode_shifted("plain text") == "plain text"


# the Course Times box of a trail brochure: two columns of stops with the minutes between them, a bridge time across,
# and a stray total ("4 hours 10 minutes") in a stats box above
_COURSE_BOX = [
    ("Approx. 10 km", 90.0, 176.0, 7.1),
    ("4 hours 10 minutes", 88.6, 165.1, 7.1),
    ("START", 47.1, 133.9, 9.0),
    ("Kyoshi Sta. (Nankai Main Line)", 56.9, 125.7, 8.5),
    ("15 min.", 112.8, 111.8, 8.0),
    ("Kosen-ji Temple", 71.4, 93.1, 8.5),
    ("15 min.", 112.8, 78.3, 8.0),
    ("Mt. Takano", 80.0, 60.5, 8.5),
    ("1 hr.", 112.8, 48.3, 8.0),
    ("20 min.", 112.8, 40.3, 8.0),
    ("Mt. Iimori", 82.3, 27.9, 8.5),
    ("1 hr.", 151.9, 108.5, 8.0),
    ("10 min.", 151.9, 100.5, 8.0),
    ("Mt. Fudatate", 199.6, 125.7, 8.5),
    ("25 min.", 235.0, 111.8, 8.0),
    ("Mt. Fudo", 206.1, 93.1, 8.5),
    ("30 min.", 235.0, 78.3, 8.0),
    ("Narutaki Fudoson", 190.9, 60.5, 8.5),
    ("15 min.", 235.0, 44.7, 8.0),
    ("GOAL", 172.3, 37.8, 9.0),
    ("Narutaki-danchi Bus Stop", 178.6, 27.9, 8.5),
]


def test_course_times_box_is_read_as_a_chain():
    story = [_line("Leave Kyoshi Station, turn left and follow the railroad tracks to the crossing.", 22.7, 400 - 9 * i) for i in range(4)]
    text = _layout_text(story + _COURSE_BOX)
    assert SECTION_TIMES in text
    chain = text.split(SECTION_TIMES)[1].split("\n")[1]
    assert chain == (
        "Kyoshi Sta. (Nankai Main Line) -> 15 min. -> Kosen-ji Temple -> 15 min. -> Mt. Takano -> 1 hr. 20 min. -> "
        "Mt. Iimori -> 1 hr. 10 min. -> Mt. Fudatate -> 25 min. -> Mt. Fudo -> 30 min. -> Narutaki Fudoson -> 15 min. -> Narutaki-danchi Bus Stop"
    )
    labels = text.split(SECTION_LABELS)[1] if SECTION_LABELS in text else ""
    assert "15 min." not in labels and "Kosen-ji Temple" not in labels


def test_a_page_without_a_times_box_has_no_times_section():
    story = [_line("Leave Kyoshi Station, turn left and follow the railroad tracks to the crossing.", 22.7, 400 - 9 * i) for i in range(4)]
    assert SECTION_TIMES not in _layout_text(story + [_line("Mt. Takano", 300, 200), _line("15 min.", 310, 190)])
