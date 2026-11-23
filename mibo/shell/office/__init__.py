"""Office documents made and changed as files: a Word document, an Excel workbook, a PowerPoint deck.

write_file's text for a .docx, .xlsx or .pptx path is Markdown, the form a model writes without being taught;
the module for the format (docx.py, xlsx.py, pptx.py, each on the library made for it) turns it into the finished
document, so a document someone asks for is a file and no program's window is driven for it. edit_file's exact
replacement is done inside the document, which keeps its styles, pictures and layout.

Each module has make(text), replaced(data, old, new, every) and summary(data); this one picks it by the file's
extension, turns away bytes from disk that are not a document of that kind before a library reads them, and
writes every document the same way: the same text makes the same bytes.
"""
from __future__ import annotations

import importlib
import io
import zipfile
import zlib
from xml.etree import ElementTree

KINDS = (".docx", ".xlsx", ".pptx")
# The formats before 2007, which these libraries do not write, and the one each became.
OLD = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx"}
NAMES = {".docx": "Word document", ".xlsx": "Excel workbook", ".pptx": "PowerPoint deck"}
# What the parts of one document may add up to once unpacked; more is not a document a person made.
UNPACKED_MOST = 512 * 1024 * 1024
# The relationship that names a package's main part.
_MAIN = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
# The main part's content type for each kind (a template or a macro-enabled file has its own).
_TYPES = {".docx": "wordprocessingml.document.main", ".xlsx": "spreadsheetml.sheet.main",
          ".pptx": "presentationml.presentation.main"}


def _module(ext: str):
    return importlib.import_module(f"{__name__}.{ext[1:]}")


def _fixed(data: bytes) -> bytes:
    """The package again with every part's date set to one fixed time, so the same document is the same bytes."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if not info.is_dir():
                target.writestr(zipfile.ZipInfo(info.filename, (1980, 1, 1, 0, 0, 0)), source.read(info),
                                zipfile.ZIP_DEFLATED)
    return out.getvalue()


def check(ext: str, data: bytes, name: str) -> None:
    """ValueError when `data` from disk is not a document of kind `ext` that the library can open: an old-format
    or password-protected file under the new name, a damaged package, or one that unpacks to far more than it is."""
    kind = NAMES[ext]
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError(f"{name} is protected with a password, or is an old-format file under a {ext} name, so it "
                         f"cannot be changed here. Ask them to save it as a {kind} without a password first.")
    damaged = ValueError(f"{name} is not a {kind} that can be opened: the file is damaged or of another kind.")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise damaged
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        names = set(package.namelist())
        if sum(info.file_size for info in package.infolist()) > UNPACKED_MOST:
            raise ValueError(f"{name} unpacks to more than {UNPACKED_MOST >> 20} MB, too large to change here.")
        if not {"_rels/.rels", "[Content_Types].xml"} <= names:
            raise damaged
        try:
            if package.testzip() is not None:
                raise damaged
            rels = ElementTree.fromstring(package.read("_rels/.rels"))
            types = package.read("[Content_Types].xml").decode("utf-8", "replace")
        except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError, ElementTree.ParseError):
            raise damaged from None
    main = next((r.get("Target", "").lstrip("/") for r in rels if r.get("Type") == _MAIN), "")
    if main not in names or _TYPES[ext] not in types:
        raise damaged


def make(ext: str, text: str) -> bytes:
    """The document of kind `ext` that `text`, written as Markdown, describes."""
    return _fixed(_module(ext).make(text))


def replaced(ext: str, data: bytes, old: str, new: str, every: bool, name: str = "the file") -> bytes:
    """The document with `old` replaced by `new`, exactly once unless `every`; ValueError says what went wrong."""
    check(ext, data, name)
    return _fixed(_module(ext).replaced(data, old, new, every))


def summary(ext: str, data: bytes) -> str:
    """What the document holds, in a few words for the model."""
    return _module(ext).summary(data)
