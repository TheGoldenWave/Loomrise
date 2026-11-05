"""Bounded local text extraction for knowledge files."""

from __future__ import annotations

from html.parser import HTMLParser
from io import BytesIO
import posixpath
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
import zlib

from .material_processing import _run_bounded_stdout


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 256
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_XML_ENTRY_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_TEXT_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 20
PDF_TEXT_TIMEOUT_SECONDS = 15
DOC_TEXT_TIMEOUT_SECONDS = 15

KNOWLEDGE_FILE_SUFFIXES = frozenset({
    ".txt", ".md", ".csv", ".json", ".html", ".htm", ".docx", ".xlsx", ".pdf", ".doc",
})
_TEXT_SUFFIXES = frozenset({".txt", ".md", ".csv", ".json"})
_HTML_BLOCKS = frozenset({
    "address", "article", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption",
    "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
    "li", "main", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul",
})
_HTML_IGNORED = frozenset({"script", "style", "noscript", "template"})
_HTML_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
})
_DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_SHEET_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


class KnowledgeFormatUnavailable(ValueError):
    """A recognized document format has no safely bounded local parser."""


class _VisibleHtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored: list[str] = []
        self.open_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self.ignored:
            if tag in _HTML_IGNORED:
                self.ignored.append(tag)
            return
        if tag in _HTML_IGNORED:
            self.ignored.append(tag)
        elif tag in _HTML_BLOCKS:
            self.parts.append("\n")
        if tag not in _HTML_IGNORED and tag not in _HTML_VOID:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag in _HTML_VOID or not self.open_tags or self.open_tags[-1] != tag:
            raise ValueError("malformed or unbalanced HTML tags")
        self.open_tags.pop()
        if tag in _HTML_BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def validate(self) -> None:
        if self.ignored or self.open_tags:
            raise ValueError("malformed or unbalanced HTML tags")


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\t\f\v ]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _read_xml_member(
    archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo], name: str,
    remaining_bytes: list[int],
) -> bytes:
    info = members.get(name)
    if info is None or info.is_dir():
        raise ValueError(f"missing package member: {name}")
    if info.file_size > MAX_XML_ENTRY_BYTES or info.file_size > remaining_bytes[0]:
        raise ValueError("XML package member exceeds the extraction limit")
    with archive.open(info, "r") as source:
        data = source.read(min(info.file_size, remaining_bytes[0]) + 1)
    if len(data) > remaining_bytes[0] or len(data) != info.file_size:
        raise ValueError("XML package member size is invalid")
    remaining_bytes[0] -= len(data)
    return data


def _parse_xml(data: bytes) -> ET.Element:
    try:
        xml_text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("XML package members must use UTF-8 encoding") from exc
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", xml_text, re.IGNORECASE):
        raise ValueError("XML DTD and entity declarations are unsupported")
    try:
        return ET.fromstring(data)
    except (ET.ParseError, RecursionError) as exc:
        raise ValueError("malformed XML package member") from exc


def _package_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ValueError("archive entry count is outside the supported limit")
    members: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if (not name or "\\" in name or path.is_absolute() or ".." in path.parts
                or name in members or info.flag_bits & 0x1):
            raise ValueError("archive contains an unsafe or unsupported member")
        if info.file_size < 0:
            raise ValueError("archive member size is invalid")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ValueError("archive compression method is unsupported")
        total_size += info.file_size
        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ValueError("archive exceeds the extraction limit")
        members[name] = info
    return members


def _open_package(data: bytes) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    try:
        archive = zipfile.ZipFile(BytesIO(data), "r")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("malformed ZIP document package") from exc
    try:
        members = _package_members(archive)
    except Exception:
        archive.close()
        raise
    return archive, members


def _extract_docx(data: bytes) -> str:
    archive, members = _open_package(data)
    remaining_bytes = [MAX_ARCHIVE_UNCOMPRESSED_BYTES]
    try:
        _parse_xml(_read_xml_member(archive, members, "[Content_Types].xml", remaining_bytes))
        root = _parse_xml(_read_xml_member(archive, members, "word/document.xml", remaining_bytes))
        if root.tag != f"{{{_DOCX_NS}}}document":
            raise ValueError("DOCX main document root is invalid")
        body = root.find(f"{{{_DOCX_NS}}}body")
        if body is None:
            raise ValueError("DOCX main document body is missing")
        paragraphs: list[str] = []
        for paragraph in body.iter(f"{{{_DOCX_NS}}}p"):
            parts: list[str] = []
            for item in paragraph.iter():
                if item.tag == f"{{{_DOCX_NS}}}t":
                    parts.append(item.text or "")
                elif item.tag == f"{{{_DOCX_NS}}}tab":
                    parts.append(" ")
                elif item.tag in {f"{{{_DOCX_NS}}}br", f"{{{_DOCX_NS}}}cr"}:
                    parts.append("\n")
            text = "".join(parts).strip()
            if text:
                paragraphs.append(text)
        return "\n".join(paragraphs)
    except (OSError, EOFError, RuntimeError, NotImplementedError, zlib.error,
            zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("malformed DOCX package") from exc
    finally:
        archive.close()


def _relationship_target(target: str) -> str:
    if not target or "\\" in target or "?" in target or "#" in target:
        raise ValueError("XLSX worksheet relationship target is invalid")
    path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
    if not path.startswith("xl/") or ".." in PurePosixPath(path).parts:
        raise ValueError("XLSX worksheet relationship leaves the workbook directory")
    return path


def _extract_shared_strings(
    archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo], remaining_bytes: list[int],
) -> list[str]:
    name = "xl/sharedStrings.xml"
    if name not in members:
        return []
    root = _parse_xml(_read_xml_member(archive, members, name, remaining_bytes))
    if root.tag != f"{{{_SHEET_NS}}}sst":
        raise ValueError("XLSX shared strings root is invalid")
    return [
        "".join(item.text or "" for item in shared.iter(f"{{{_SHEET_NS}}}t"))
        for shared in root.findall(f"{{{_SHEET_NS}}}si")
    ]


def _extract_worksheet(
    archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo],
    name: str, shared_strings: list[str], remaining_bytes: list[int],
    remaining_text_bytes: list[int], has_output: list[bool],
) -> list[str]:
    root = _parse_xml(_read_xml_member(archive, members, name, remaining_bytes))
    if root.tag != f"{{{_SHEET_NS}}}worksheet":
        raise ValueError("XLSX worksheet root is invalid")
    sheet_data = root.find(f"{{{_SHEET_NS}}}sheetData")
    if sheet_data is None:
        raise ValueError("XLSX worksheet data is missing")
    lines: list[str] = []
    for row in sheet_data.findall(f"{{{_SHEET_NS}}}row"):
        values: list[str] = []
        for cell in row.findall(f"{{{_SHEET_NS}}}c"):
            cell_type = cell.get("t", "n")
            value = cell.find(f"{{{_SHEET_NS}}}v")
            if cell_type == "inlineStr":
                inline = cell.find(f"{{{_SHEET_NS}}}is")
                text = "" if inline is None else "".join(
                    item.text or "" for item in inline.iter(f"{{{_SHEET_NS}}}t")
                )
            elif cell_type == "s":
                if value is None or value.text is None or not value.text.isdigit():
                    raise ValueError("XLSX shared string reference is invalid")
                index = int(value.text)
                if index >= len(shared_strings):
                    raise ValueError("XLSX shared string reference is out of range")
                text = shared_strings[index]
            elif cell_type in {"n", "b", "e", "str", "d"}:
                text = "" if value is None or value.text is None else value.text
            else:
                raise ValueError("XLSX cell type is unsupported")
            if text:
                extra_bytes = len(text.encode("utf-8")) + (2 if values else 0)
                if extra_bytes > remaining_text_bytes[0]:
                    raise ValueError("extracted document text exceeds the 8 MB limit")
                remaining_text_bytes[0] -= extra_bytes
                values.append(text)
        if values:
            if has_output[0]:
                if remaining_text_bytes[0] == 0:
                    raise ValueError("extracted document text exceeds the 8 MB limit")
                remaining_text_bytes[0] -= 1
            lines.append(" | ".join(values))
            has_output[0] = True
    return lines


def _extract_xlsx(data: bytes) -> str:
    archive, members = _open_package(data)
    remaining_bytes = [MAX_ARCHIVE_UNCOMPRESSED_BYTES]
    remaining_text_bytes = [MAX_EXTRACTED_TEXT_BYTES]
    has_output = [False]
    try:
        _parse_xml(_read_xml_member(archive, members, "[Content_Types].xml", remaining_bytes))
        workbook = _parse_xml(_read_xml_member(archive, members, "xl/workbook.xml", remaining_bytes))
        relationships = _parse_xml(_read_xml_member(
            archive, members, "xl/_rels/workbook.xml.rels", remaining_bytes,
        ))
        if workbook.tag != f"{{{_SHEET_NS}}}workbook":
            raise ValueError("XLSX workbook root is invalid")
        if relationships.tag != f"{{{_PACKAGE_REL_NS}}}Relationships":
            raise ValueError("XLSX workbook relationships root is invalid")
        targets = {
            relationship.get("Id"): relationship.get("Target")
            for relationship in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
            if relationship.get("TargetMode") != "External"
        }
        sheets = workbook.find(f"{{{_SHEET_NS}}}sheets")
        if sheets is None:
            raise ValueError("XLSX workbook has no sheets")
        shared_strings = _extract_shared_strings(archive, members, remaining_bytes)
        lines: list[str] = []
        sheet_count = 0
        for sheet in sheets.findall(f"{{{_SHEET_NS}}}sheet"):
            relation_id = sheet.get(f"{{{_SHEET_REL_NS}}}id")
            target = targets.get(relation_id)
            if target is None:
                raise ValueError("XLSX worksheet relationship is missing")
            name = _relationship_target(target)
            lines.extend(_extract_worksheet(
                archive, members, name, shared_strings, remaining_bytes,
                remaining_text_bytes, has_output,
            ))
            sheet_count += 1
        if sheet_count == 0:
            raise ValueError("XLSX workbook has no sheets")
        return "\n".join(lines)
    except (OSError, EOFError, RuntimeError, NotImplementedError, zlib.error,
            zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("malformed XLSX package") from exc
    finally:
        archive.close()


def _extract_pdf(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise ValueError("malformed PDF document")
    binary = shutil.which("pdftotext")
    if not binary:
        raise KnowledgeFormatUnavailable("本机未安装 pdftotext；PDF 文本无法解析")
    try:
        with tempfile.TemporaryDirectory(prefix="loomrise-knowledge-pdf-") as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(data)
            extracted = _run_bounded_stdout(
                [binary, "-enc", "UTF-8", "-f", "1", "-l", str(MAX_PDF_PAGES), str(source), "-"],
                timeout=PDF_TEXT_TIMEOUT_SECONDS,
                output_limit=MAX_EXTRACTED_TEXT_BYTES,
            )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("PDF text extraction timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError("malformed or unsupported PDF document") from exc
    except ValueError as exc:
        if str(exc) == "processing_output_limit":
            raise ValueError("extracted document text exceeds the 8 MB limit") from exc
        raise
    try:
        text = _normalize_text(extracted.decode("utf-8"))
    except UnicodeError as exc:
        raise ValueError("PDF text is not valid UTF-8") from exc
    if not text:
        raise KnowledgeFormatUnavailable("PDF 未包含可提取文本；扫描 PDF OCR 暂不可用")
    return text


def _extract_doc(data: bytes) -> str:
    binary = shutil.which("textutil")
    if not binary:
        raise KnowledgeFormatUnavailable("本机未安装 macOS textutil；DOC 文本无法解析")
    try:
        with tempfile.TemporaryDirectory(prefix="loomrise-knowledge-doc-") as directory:
            source = Path(directory) / "source.doc"
            source.write_bytes(data)
            extracted = _run_bounded_stdout(
                [binary, "-convert", "txt", "-encoding", "UTF-8", "-stdout", str(source)],
                timeout=DOC_TEXT_TIMEOUT_SECONDS,
                output_limit=MAX_EXTRACTED_TEXT_BYTES,
            )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("DOC text extraction timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError("malformed or unsupported DOC document") from exc
    except ValueError as exc:
        if str(exc) == "processing_output_limit":
            raise ValueError("extracted document text exceeds the 8 MB limit") from exc
        raise
    try:
        text = _normalize_text(extracted.decode("utf-8-sig"))
    except UnicodeError as exc:
        raise ValueError("DOC text is not valid UTF-8") from exc
    if not text:
        raise KnowledgeFormatUnavailable("DOC 未包含可提取文本")
    return text


def extract_knowledge_file_text(filename: str, data: bytes) -> str:
    """Extract UTF-8 text from supported files without unbounded archive expansion."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("文件超过 5 MB")
    suffix = Path(filename).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ValueError("文本文件必须使用 UTF-8 编码") from exc
    elif suffix in {".html", ".htm"}:
        try:
            source = data.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ValueError("HTML 文件必须使用 UTF-8 编码") from exc
        parser = _VisibleHtmlText()
        try:
            parser.feed(source)
            parser.close()
            parser.validate()
        except Exception as exc:
            raise ValueError("malformed HTML document") from exc
        text = _normalize_text("".join(parser.parts))
    elif suffix == ".docx":
        text = _normalize_text(_extract_docx(data))
    elif suffix == ".xlsx":
        text = _normalize_text(_extract_xlsx(data))
    elif suffix == ".pdf":
        text = _extract_pdf(data)
    elif suffix == ".doc":
        text = _extract_doc(data)
    else:
        raise ValueError(f"unsupported knowledge file format: {suffix or '(no extension)'}")
    if len(text.encode("utf-8")) > MAX_EXTRACTED_TEXT_BYTES:
        raise ValueError("extracted document text exceeds the 8 MB limit")
    return text
