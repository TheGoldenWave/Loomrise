from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tracemalloc
import unittest
import zipfile
from unittest.mock import patch

from loomrise.configuration import ConfigurationService
from loomrise.durable_store import SqliteStore


MAX_INPUT_BYTES = 5 * 1024 * 1024


def zipped_files(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def xlsx_document(sheet_xml: str, shared_strings: str | None = None) -> bytes:
    files = {
        "[Content_Types].xml": (
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
            "<Default Extension=\"xml\" ContentType=\"application/xml\"/></Types>"
        ),
        "xl/workbook.xml": (
            "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
            "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
            "<sheets><sheet name=\"Courses\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
            "<Relationship Id=\"rId1\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" "
            "Target=\"worksheets/sheet1.xml\"/></Relationships>"
        ),
        "xl/worksheets/sheet1.xml": sheet_xml,
    }
    if shared_strings is not None:
        files["xl/sharedStrings.xml"] = shared_strings
    return zipped_files(files)


def pdf_document(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode("ascii"))
        document.extend(item)
        document.extend(b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        f"trailer\n<< /Root 1 0 R /Size {len(offsets)} >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(document)


class KnowledgeDocumentIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SqliteStore(os.path.join(self.temp.name, "loomrise.db"))
        self.addCleanup(self.store.close)
        self.service = ConfigurationService(self.store)

    def ingest(self, name: str, data: bytes) -> dict:
        path = Path(self.temp.name) / name
        path.write_bytes(data)
        try:
            source = self.service.create_knowledge_source(
                tenant_id="tenant-a", agent_id="expert-a", kind="file",
                locator=str(path), display_name=name, authorization="licensed",
            )
        except ValueError as exc:
            self.fail(f"file source registration rejected {path.suffix}: {exc}")
        return self.service.ingest_knowledge_source(
            tenant_id="tenant-a", agent_id="expert-a", source_id=source["source_id"],
        )

    def search(self, query: str) -> str:
        matches = self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query=query,
        )
        return "\n".join(item["text"] for item in matches)

    def test_existing_utf8_text_formats_remain_supported(self):
        for index, suffix in enumerate((".txt", ".md", ".csv", ".json")):
            with self.subTest(suffix=suffix):
                marker = f"retained-format-{index}"
                result = self.ingest(f"legacy{suffix}", f"{marker}：UTF-8 内容。".encode())
                self.assertEqual(result["state"], "ready")
                self.assertIn(marker, self.search(marker))

    def test_html_ingestion_extracts_visible_text_and_omits_script_content(self):
        for suffix in (".html", ".htm"):
            with self.subTest(suffix=suffix):
                result = self.ingest(
                    f"guide{suffix}",
                    """<!doctype html><html><body><h1>预约须知</h1>
                    <p>请提前一天预约。</p><script>secretKey=123</script></body></html>""".encode(),
                )

                self.assertEqual(result["state"], "ready")
                self.assertIn("请提前一天预约", self.search("请提前一天"))
                self.assertEqual(self.service.search_ingested_knowledge(
                    tenant_id="tenant-a", agent_id="expert-a", query="secretKey",
                ), [])

    def test_unbalanced_html_fails_closed_without_indexing(self):
        result = self.ingest("broken.html", b"<html><body><p>Incomplete document")

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "parse_failed")
        self.assertEqual(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="Incomplete",
        ), [])

    def test_docx_ingestion_extracts_document_paragraphs(self):
        docx = zipped_files({
            "[Content_Types].xml": "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>",
            "word/document.xml": (
                "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                "<w:body><w:p><w:r><w:t>退款规则：开课前可退。</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>开课后按合同处理。</w:t></w:r></w:p></w:body></w:document>"
            ),
        })
        result = self.ingest("policy.docx", docx)

        self.assertEqual(result["state"], "ready")
        self.assertIn("开课前可退", self.search("退款规则"))

    def test_xlsx_ingestion_extracts_shared_and_inline_cell_text(self):
        xlsx = xlsx_document(
            (
                "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>"
                "<row r=\"1\"><c r=\"A1\" t=\"s\"><v>0</v></c><c r=\"B1\" t=\"s\"><v>1</v></c></row>"
                "<row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>课时</t></is></c>"
                "<c r=\"B2\"><v>12</v></c></row></sheetData></worksheet>"
            ),
            (
                "<sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
                "<si><t>课程名称</t></si><si><t>Python 入门</t></si></sst>"
            ),
        )
        result = self.ingest("courses.xlsx", xlsx)

        self.assertEqual(result["state"], "ready")
        text = self.search("Python")
        self.assertIn("课程名称", text)
        self.assertIn("12", text)

    def test_xlsx_uncompressed_xml_member_is_bounded(self):
        repeated_text = "x" * (8 * 1024 * 1024 + 1)
        sheet = (
            "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>"
            "<row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>"
            + repeated_text
            + "</t></is></c></row></sheetData></worksheet>"
        )
        xlsx = xlsx_document(sheet)
        self.assertLess(len(xlsx), MAX_INPUT_BYTES)

        result = self.ingest("expanded.xlsx", xlsx)

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "parse_failed")

    def test_xlsx_shared_string_references_cannot_expand_output_before_budget_check(self):
        shared_text = "overflow-token-" + "x" * (8 * 1024)
        rows = "".join(
            f'<row r="{index}"><c r="A{index}" t="s"><v>0</v></c></row>'
            for index in range(1, 1101)
        )
        xlsx = xlsx_document(
            "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
            f"<sheetData>{rows}</sheetData></worksheet>",
            "<sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
            f"<si><t>{shared_text}</t></si></sst>",
        )
        self.assertLess(len(xlsx), MAX_INPUT_BYTES)

        tracemalloc.start()
        try:
            result = self.ingest("expanded-shared-strings.xlsx", xlsx)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "parse_failed")
        self.assertLess(peak_bytes, 20 * 1024 * 1024)
        self.assertEqual(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="overflow-token",
        ), [])

    def test_text_pdf_is_extracted_into_the_knowledge_index(self):
        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext is optional")

        result = self.ingest("policy.pdf", pdf_document("pdf-knowledge-marker"))

        self.assertEqual(result["state"], "ready")
        self.assertIn("pdf-knowledge-marker", self.search("pdf-knowledge"))

    def test_pdf_text_extraction_uses_bounded_subprocess_limits(self):
        with patch("shutil.which", return_value="/usr/bin/pdftotext"), patch(
            "loomrise.knowledge_documents._run_bounded_stdout",
            return_value=b"bounded-pdf-marker",
        ) as bounded_runner:
            result = self.ingest("bounded.pdf", pdf_document("source-marker"))

        self.assertEqual(result["state"], "ready")
        arguments = bounded_runner.call_args.args[0]
        self.assertEqual(arguments[:7], [
            "/usr/bin/pdftotext", "-enc", "UTF-8", "-f", "1", "-l", "20",
        ])
        self.assertEqual(arguments[-1], "-")
        self.assertEqual(bounded_runner.call_args.kwargs["timeout"], 15)
        self.assertEqual(bounded_runner.call_args.kwargs["output_limit"], 8 * 1024 * 1024)
        self.assertIn("bounded-pdf-marker", self.search("bounded-pdf"))

    def test_malformed_pdf_fails_without_indexing(self):
        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext is optional")

        result = self.ingest("broken.pdf", b"%PDF-1.7\nnot a document")

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "parse_failed")
        self.assertEqual(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="not a document",
        ), [])

    def test_pdf_without_pdftotext_is_explicitly_unavailable(self):
        with patch("shutil.which", return_value=None):
            result = self.ingest("policy.pdf", pdf_document("pdf-knowledge-marker"))

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "format_unavailable")

    def test_scanned_pdf_without_text_layer_is_not_indexed(self):
        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext is optional")

        result = self.ingest("scanned.pdf", pdf_document(""))

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "format_unavailable")
        self.assertIn("扫描 PDF OCR 暂不可用", result["error_message"])
        self.assertEqual(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="pdf-knowledge",
        ), [])

    def test_doc_is_converted_and_indexed_by_native_textutil(self):
        textutil = shutil.which("textutil")
        if not textutil:
            self.skipTest("macOS textutil is optional")

        source = Path(self.temp.name) / "source.rtf"
        source.write_text(
            r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Helvetica;}}\f0\fs24 R3-DOC-REAL-FIXTURE-7319}",
            encoding="ascii",
        )
        document = Path(self.temp.name) / "legacy.doc"
        subprocess.run(
            [textutil, "-convert", "doc", "-output", str(document), str(source)],
            check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=15,
        )

        result = self.ingest("legacy.doc", document.read_bytes())

        self.assertEqual(result["state"], "ready")
        self.assertIn("R3-DOC-REAL-FIXTURE-7319", self.search("R3-DOC-REAL-FIXTURE"))

    def test_doc_without_textutil_is_explicitly_unavailable(self):
        with patch("shutil.which", return_value=None):
            result = self.ingest("manual.doc", b"legacy binary")

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "format_unavailable")

    def test_doc_uses_bounded_conversion_and_indexing(self):
        with patch("shutil.which", return_value="/usr/bin/textutil"), patch(
            "loomrise.knowledge_documents._run_bounded_stdout",
            return_value=b"bounded-doc-marker",
        ) as bounded_runner:
            result = self.ingest("bounded.doc", b"fixture document")

        self.assertEqual(result["state"], "ready")
        self.assertEqual(bounded_runner.call_args.args[0][:6], [
            "/usr/bin/textutil", "-convert", "txt", "-encoding", "UTF-8", "-stdout",
        ])
        self.assertEqual(bounded_runner.call_args.kwargs["timeout"], 15)
        self.assertEqual(bounded_runner.call_args.kwargs["output_limit"], 8 * 1024 * 1024)
        self.assertIn("bounded-doc-marker", self.search("bounded-doc"))

    def test_doc_failure_timeout_and_output_limit_fail_closed(self):
        cases = (
            (subprocess.CalledProcessError(1, "textutil"), "malformed.doc"),
            (subprocess.TimeoutExpired("textutil", 15), "timeout.doc"),
            (ValueError("processing_output_limit"), "large.doc"),
            (b"\xff", "encoding.doc"),
        )
        for failure, filename in cases:
            with self.subTest(filename=filename), patch(
                "shutil.which", return_value="/usr/bin/textutil",
            ):
                with patch(
                    "loomrise.knowledge_documents._run_bounded_stdout", side_effect=[failure],
                ):
                    result = self.ingest(filename, b"fixture document")

                self.assertEqual(result["state"], "failed")
                self.assertEqual(result["error_code"], "parse_failed")
                self.assertEqual(self.service.search_ingested_knowledge(
                    tenant_id="tenant-a", agent_id="expert-a",
                    query=Path(filename).stem,
                ), [])

    def test_malformed_docx_is_failed_without_indexing(self):
        result = self.ingest("broken.docx", b"not a zip package")

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "parse_failed")
        self.assertEqual(self.service.search_ingested_knowledge(
            tenant_id="tenant-a", agent_id="expert-a", query="not a zip",
        ), [])

    def test_malformed_xlsx_xml_is_failed_closed(self):
        xlsx = xlsx_document("<worksheet><sheetData>")

        result = self.ingest("broken.xlsx", xlsx)

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "parse_failed")

    def test_oversized_file_fails_closed_at_the_existing_five_mb_limit(self):
        result = self.ingest("large.html", b"x" * (MAX_INPUT_BYTES + 1))

        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "parse_failed")

    def test_unsupported_extension_is_rejected(self):
        path = Path(self.temp.name) / "payload.exe"
        path.write_bytes(b"binary")

        with self.assertRaisesRegex(ValueError, "仅支持"):
            self.service.create_knowledge_source(
                tenant_id="tenant-a", agent_id="expert-a", kind="file",
                locator=str(path), display_name=path.name, authorization="licensed",
            )


if __name__ == "__main__":
    unittest.main()
