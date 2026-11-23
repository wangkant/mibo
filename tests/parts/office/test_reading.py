"""read_file on documents: a Word document's paragraphs with each table row on one line and its headers after the
body, the same text from a copy kept under another name, and a PDF's text page by page, with a plain sentence when
a PDF holds no text, asks for a password or is damaged."""
from __future__ import annotations

import io
from pathlib import Path

from docx import Document

from mibo.shell import files, office


def _pdf(pages: list[str]) -> bytes:
    """A PDF whose pages carry these lines of text (an empty one is a page with no text, as a scan's is)."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * n} 0 R" for n in range(len(pages)))
               + f"] /Count {len(pages)} >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for n, words in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({words}) Tj ET" if words else ""
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                       f"/Contents {5 + 2 * n} 0 R >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for n, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    start = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return out.getvalue()


def test_a_word_document_reads_as_paragraphs_rows_and_its_header(tmp_path: Path):
    data = office.make(".docx", "# 报价单\n\n说明\t附件\n\n| 品名 | 数量 |\n|---|---|\n| 纸张 | 20 |\n")
    document = Document(io.BytesIO(data))
    document.sections[0].header.paragraphs[0].text = "某某公司"
    out = io.BytesIO()
    document.save(out)
    path = tmp_path / "报价单.docx"
    path.write_bytes(out.getvalue())
    text = files.read(str(path))
    assert "text of the Word document" in text
    body = [line.split("\t", 1)[1] for line in text.splitlines()[1:]]
    # The page number in the footer is left out; a tab stays a tab, as edit_file matches it.
    assert body == ["报价单", "说明\t附件", "| 品名 | 数量 |", "| 纸张 | 20 |", "[header]", "某某公司"]


def test_a_copy_kept_under_another_name_reads_as_the_document_it_is(tmp_path: Path):
    copy = tmp_path / "1700000000.before"
    copy.write_bytes(office.make(".docx", "第一段\n\n第二段"))
    assert files.document_lines(str(copy)) == ["第一段", "第二段"]
    assert files.document_lines(str(tmp_path / "a.zip"), b"PK\x03\x04 not really") is None
    (tmp_path / "notes.before").write_text("plain text", encoding="utf-8")
    assert files.document_lines(str(tmp_path / "notes.before")) is None


def test_a_pdf_reads_page_by_page(tmp_path: Path):
    path = tmp_path / "report.pdf"
    path.write_bytes(_pdf(["Quarterly report", "Revenue grew 24 percent"]))
    text = files.read(str(path))
    assert "text of the PDF" in text
    body = [line.split("\t", 1)[1] for line in text.splitlines()[1:]]
    assert body == ["[page 1]", "Quarterly report", "[page 2]", "Revenue grew 24 percent"]


def test_a_pdf_of_pictures_says_it_holds_no_text(tmp_path: Path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf(["", ""]))
    text = files.read(str(path))
    assert text.startswith("scan.pdf is a PDF of 2 pages with no text in it") and "open with show true" in text


def test_a_damaged_pdf_is_said_to_be_so(tmp_path: Path):
    path = tmp_path / "发票.pdf"
    path.write_bytes(b"%PDF-1.4\n%\xe5\x8f\x91\xe7\xa5\xa8\n")
    assert files.read(str(path)).startswith("发票.pdf could not be read as a PDF")
