import base64
import hashlib
from io import BytesIO
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from loomrise.material_derivatives import Derivative, MediaProcessingResult
from loomrise.material_processing import make_candidate


class _CountingOutput(BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.bytes_read = 0

    def read(self, size=-1):
        content = super().read(size)
        self.bytes_read += len(content)
        return content


class _FakeProcess:
    def __init__(self, *, stdout=b'', returncode=0, timeout=False):
        self.stdout = _CountingOutput(stdout)
        self.returncode = returncode
        self.timeout = timeout
        self.killed = False
        self.wait_timeouts = []

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        if self.timeout and timeout is not None and not self.killed:
            raise subprocess.TimeoutExpired('pdftotext', timeout)
        return self.returncode

    def poll(self):
        if self.timeout and not self.killed:
            return None
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class _OverflowProcess(_FakeProcess):
    def __init__(self, *, stdout):
        super().__init__(stdout=stdout)
        self.returncode = None
        self.killed_event = threading.Event()

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        if not self.killed_event.wait(timeout):
            raise subprocess.TimeoutExpired('tesseract', timeout)
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        super().kill()
        self.killed_event.set()


class MaterialProcessingTests(unittest.TestCase):
    def test_text_summary_is_a_review_candidate_and_never_a_file_derivative(self):
        candidate = make_candidate(asset_id='a', version_id='v1', filename='guide.txt',
                                   media_type='text/plain', content='  first line\n second line '.encode())
        self.assertEqual(candidate.status, 'ready')
        self.assertEqual(candidate.summary, 'first line second line')
        self.assertEqual(candidate.review_state, 'pending')

    def test_image_without_local_ocr_is_explicitly_unavailable(self):
        original = b'png'
        with patch('loomrise.material_processing.shutil.which', return_value=None), \
                patch('loomrise.material_processing.process_media') as process_media:
            media = make_candidate(asset_id='a', version_id='v1', filename='x.png', media_type='image/png', content=original)
        self.assertEqual(media.status, 'unavailable')
        self.assertIn('未提取图片文字', media.summary)
        self.assertEqual(media.source_hash, hashlib.sha256(original).hexdigest())
        self.assertEqual(media.review_state, 'pending')
        process_media.assert_not_called()

    def test_image_ocr_output_overflow_kills_process_after_limit_plus_one_bytes(self):
        preview = Derivative('image_preview', 'preview.png', 'image/png', b'preview bytes', {})
        languages = _FakeProcess(stdout=b'eng\n')
        overflow = _OverflowProcess(stdout=b'x' * 64_001)
        with patch('loomrise.material_processing.shutil.which', return_value='/usr/bin/tesseract'), \
                patch('loomrise.material_processing.process_media', return_value=MediaProcessingResult('ready', artifacts=[preview])), \
                patch('loomrise.material_processing.subprocess.run', side_effect=[
                    SimpleNamespace(stdout=b'eng\n'), SimpleNamespace(stdout=b'x' * 64_001),
                ]) as legacy_runner, \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=[languages, overflow]) as popen:
            candidate = make_candidate(asset_id='a', version_id='v1', filename='x.png',
                                       media_type='image/png', content=b'png')

        self.assertEqual(candidate.status, 'failed')
        legacy_runner.assert_not_called()
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(languages.wait_timeouts, [5])
        self.assertEqual(overflow.wait_timeouts, [15])
        self.assertTrue(overflow.killed)
        self.assertEqual(overflow.stdout.bytes_read, 64_001)
        self.assertTrue(overflow.stdout.closed)

    def test_image_ocr_uses_only_a_bounded_preview_and_remains_pending_review(self):
        original = b'original image bytes'
        preview = Derivative('image_preview', 'preview.png', 'image/png', b'preview bytes', {})
        languages = _FakeProcess(stdout=b'List of available languages (2):\neng\nchi_sim\n')
        ocr = _FakeProcess(stdout='Course price 199'.encode())
        with patch('loomrise.material_processing.shutil.which', return_value='/usr/bin/tesseract'), \
                patch('loomrise.material_processing.process_media', return_value=MediaProcessingResult('ready', artifacts=[preview])) as process_media, \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=[languages, ocr]) as popen:
            candidate = make_candidate(asset_id='a', version_id='v1', filename='x.png',
                                      media_type='image/png', content=original)
        process_media.assert_called_once_with(media_type='image/png', content=original)
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(popen.call_args_list[0].args[0], ['/usr/bin/tesseract', '--list-langs'])
        self.assertTrue(popen.call_args_list[1].args[0][1].endswith('preview.png'))
        self.assertIn('chi_sim+eng', popen.call_args_list[1].args[0])
        self.assertEqual(languages.wait_timeouts, [5])
        self.assertEqual(ocr.wait_timeouts, [15])
        self.assertEqual(candidate.status, 'ready')
        self.assertIn('OCR 候选', candidate.summary)
        self.assertIn('Course price 199', candidate.summary)
        self.assertEqual(candidate.review_state, 'pending')
        self.assertEqual(candidate.source_hash, hashlib.sha256(original).hexdigest())

    def test_image_ocr_timeout_does_not_create_a_candidate(self):
        preview = Derivative('image_preview', 'preview.png', 'image/png', b'preview bytes', {})
        languages = _FakeProcess(stdout=b'eng\n')
        timeout = _FakeProcess(timeout=True)
        with patch('loomrise.material_processing.shutil.which', return_value='/usr/bin/tesseract'), \
                patch('loomrise.material_processing.process_media', return_value=MediaProcessingResult('ready', artifacts=[preview])), \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=[languages, timeout]):
            candidate = make_candidate(asset_id='a', version_id='v1', filename='x.png',
                                       media_type='image/png', content=b'png')
        self.assertEqual(candidate.status, 'failed')
        self.assertIn('超时', candidate.summary)
        self.assertEqual(languages.wait_timeouts, [5])
        self.assertEqual(timeout.wait_timeouts, [15, None])
        self.assertTrue(timeout.killed)

    def test_unhandled_video_container_is_explicitly_unsupported(self):
        video = make_candidate(asset_id='a', version_id='v1', filename='x.mov',
                               media_type='video/quicktime', content=b'mov')
        self.assertEqual(video.status, 'unsupported')
        self.assertIn('语音转写', video.summary)

    def test_pdf_text_is_a_bounded_review_candidate(self):
        pdf = b'%PDF-1.4\nfixture'
        process = _FakeProcess(stdout=b'Product instructions for setup.')

        def launch(args, **kwargs):
            self.assertEqual(args[0], '/usr/bin/pdftotext')
            self.assertEqual(args[1:7], ['-enc', 'UTF-8', '-f', '1', '-l', '20'])
            self.assertEqual(args[-1], '-')
            self.assertEqual(Path(args[-2]).read_bytes(), pdf)
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertIs(kwargs['stdout'], subprocess.PIPE)
            self.assertIs(kwargs['stderr'], subprocess.DEVNULL)
            return process

        with patch('loomrise.material_processing.shutil.which', return_value='/usr/bin/pdftotext'), \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=launch) as popen:
            candidate = make_candidate(asset_id='a', version_id='v1', filename='guide.pdf',
                                       media_type='application/pdf', content=pdf)
        popen.assert_called_once()
        self.assertEqual(process.wait_timeouts, [15])
        self.assertTrue(process.stdout.closed)
        self.assertFalse(Path(popen.call_args.args[0][-2]).exists())
        self.assertEqual(candidate.status, 'ready')
        self.assertEqual(candidate.kind, 'summary')
        self.assertIn('PDF 文本候选（前 20 页，需人工核对）', candidate.summary)
        self.assertIn('Product instructions for setup.', candidate.summary)
        self.assertEqual(candidate.review_state, 'pending')
        self.assertEqual(candidate.source_hash, hashlib.sha256(pdf).hexdigest())

    def test_pdf_without_pdftotext_is_explicitly_unavailable(self):
        with patch('loomrise.material_processing.shutil.which', return_value=None), \
                patch('loomrise.material_processing.subprocess.Popen') as popen:
            candidate = make_candidate(asset_id='a', version_id='v1', filename='guide.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4\nfixture')
        self.assertEqual(candidate.status, 'unavailable')
        self.assertIn('pdftotext', candidate.summary)
        self.assertEqual(candidate.review_state, 'pending')
        popen.assert_not_called()

    def test_scanned_pdf_uses_review_gated_page_ocr_fallback(self):
        pdf = b'%PDF-1.4 scanned fixture'
        outputs = iter((b' \n', b'Pages: 2\n', b'eng\nchi_sim\n',
                        '退款政策'.encode(), '退款申请流程'.encode()))

        def bounded_stdout(arguments, *, timeout, output_limit, env=None):
            if arguments[0] == '/usr/bin/tesseract' and arguments[1] != '--list-langs':
                self.assertEqual(arguments[3:7], ['--psm', '6', '-l', 'chi_sim+eng'])
                self.assertLessEqual(output_limit, 64_000)
                self.assertEqual(env['OMP_THREAD_LIMIT'], '1')
            return next(outputs)

        rendered = []

        def render(arguments, **kwargs):
            self.assertEqual(arguments[0], '/usr/bin/pdftoppm')
            self.assertEqual(arguments[arguments.index('-scale-to') + 1], '2000')
            self.assertIs(kwargs['stdin'], subprocess.DEVNULL)
            self.assertIs(kwargs['stdout'], subprocess.DEVNULL)
            page = int(arguments[arguments.index('-f') + 1])
            self.assertEqual(arguments[arguments.index('-l') + 1], str(page))
            header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
            Path(arguments[-1] + '.png').write_bytes(
                header + (100).to_bytes(4, 'big') * 2 + b'png')
            rendered.append(page)
            return SimpleNamespace(returncode=0)

        def find(binary):
            return {'pdftotext': '/usr/bin/pdftotext', 'pdfinfo': '/usr/bin/pdfinfo',
                    'pdftoppm': '/usr/bin/pdftoppm', 'tesseract': '/usr/bin/tesseract'}.get(binary)

        with patch('loomrise.material_processing.shutil.which', side_effect=find), \
                patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                patch('loomrise.material_processing.subprocess.run', side_effect=render):
            candidate = make_candidate(asset_id='a', version_id='v1', filename='scan.pdf',
                                      media_type='application/pdf', content=pdf)

        self.assertEqual(rendered, [1, 2])
        self.assertEqual(candidate.status, 'ready')
        self.assertEqual(candidate.review_state, 'pending')
        self.assertIn('PDF 扫描件 OCR 候选', candidate.summary)
        self.assertIn('需人工核对', candidate.summary)
        self.assertIn('退款政策', candidate.summary)
        self.assertIn('退款申请流程', candidate.summary)
        self.assertEqual(candidate.source_hash, hashlib.sha256(pdf).hexdigest())

    def test_native_pdf_with_page_separators_does_not_require_ocr(self):
        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: '/usr/bin/pdftotext' if name == 'pdftotext' else None), \
                patch('loomrise.material_processing._run_bounded_stdout', return_value=b'Native first page\fNative second page\f'), \
                patch('loomrise.material_processing.subprocess.run') as run:
            candidate = make_candidate(asset_id='a', version_id='v1', filename='native.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4 fixture')
        self.assertEqual(candidate.status, 'ready')
        self.assertIn('PDF 文本候选', candidate.summary)
        run.assert_not_called()

    def test_mixed_pdf_only_ocrs_empty_pages_and_preserves_page_order(self):
        for native, pages, expected, rendered_pages in (
            (b'First page\f\fLast page\f', 3, 'First page scanned page 2 Last page', [2]),
            (b'First page\f\f', 2, 'First page scanned page 2', [2]),
        ):
            with self.subTest(native=native):
                rendered = []

                def bounded_stdout(arguments, **kwargs):
                    if arguments[0] == '/usr/bin/pdftotext': return native
                    if arguments[0] == '/usr/bin/pdfinfo': return f'Pages: {pages}\n'.encode()
                    if arguments[1] == '--list-langs': return b'eng\n'
                    return f'scanned page {rendered[-1]}'.encode()

                def render(arguments, **kwargs):
                    rendered.append(int(arguments[arguments.index('-f') + 1]))
                    header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
                    Path(arguments[-1] + '.png').write_bytes(header + (100).to_bytes(4, 'big') * 2 + b'png')
                    return SimpleNamespace(returncode=0)

                original = b'%PDF-1.4 mixed fixture'
                with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: f'/usr/bin/{name}'), \
                        patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                        patch('loomrise.material_processing.subprocess.run', side_effect=render):
                    candidate = make_candidate(asset_id='a', version_id='v1', filename='mixed.pdf',
                                               media_type='application/pdf', content=original)
                self.assertEqual(rendered, rendered_pages)
                self.assertEqual(candidate.status, 'ready')
                self.assertEqual(candidate.review_state, 'pending')
                self.assertIn('PDF 混合文本/OCR 候选', candidate.summary)
                self.assertIn(expected, candidate.summary)
                self.assertEqual(candidate.source_hash, hashlib.sha256(original).hexdigest())

    def test_mixed_pdf_missing_ocr_fails_closed_instead_of_returning_native_subset(self):
        for missing in ('tools', 'languages'):
            with self.subTest(missing=missing):
                def bounded_stdout(arguments, **kwargs):
                    if arguments[0] == '/usr/bin/pdftotext': return b'Native text\f\f'
                    if arguments[0] == '/usr/bin/pdfinfo': return b'Pages: 2\n'
                    return b'fra\n'

                def find(name):
                    return None if missing == 'tools' and name == 'tesseract' else f'/usr/bin/{name}'

                with patch('loomrise.material_processing.shutil.which', side_effect=find), \
                        patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                        patch('loomrise.material_processing.subprocess.run') as render:
                    candidate = make_candidate(asset_id='a', version_id='v1', filename='mixed.pdf',
                                               media_type='application/pdf', content=b'%PDF-1.4 fixture')
                self.assertEqual(candidate.status, 'unavailable')
                self.assertEqual(candidate.review_state, 'pending')
                self.assertNotIn('Native text', candidate.summary)
                render.assert_not_called()

    def test_mixed_pdf_reserves_native_text_before_ocr_output_budget(self):
        budgets = []

        def bounded_stdout(arguments, *, output_limit, **kwargs):
            if arguments[0] == '/usr/bin/pdftotext': return b'First\f\fLast\f'
            if arguments[0] == '/usr/bin/pdfinfo': return b'Pages: 3\n'
            if arguments[1] == '--list-langs': return b'eng\n'
            budgets.append(output_limit)
            return b'OCR'

        with patch('loomrise.material_processing._OCR_OUTPUT_LIMIT', 16), \
                patch('loomrise.material_processing.shutil.which', side_effect=lambda name: f'/usr/bin/{name}'), \
                patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                patch('loomrise.material_processing._check_rendered_page'), \
                patch('loomrise.material_processing.subprocess.run', return_value=SimpleNamespace(returncode=0)):
            candidate = make_candidate(asset_id='a', version_id='v1', filename='mixed.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4 fixture')
        self.assertEqual(budgets, [5])
        self.assertEqual(candidate.status, 'ready')
        self.assertIn('First OCR Last', candidate.summary)

    def test_scan_pdf_ocr_missing_renderer_is_unavailable(self):
        calls = []

        def find(binary):
            calls.append(binary)
            return '/usr/bin/pdftotext' if binary == 'pdftotext' else None

        with patch('loomrise.material_processing.shutil.which', side_effect=find), \
                patch('loomrise.material_processing._run_bounded_stdout', return_value=b''), \
                patch('loomrise.material_processing.subprocess.run') as run:
            candidate = make_candidate(asset_id='a', version_id='v1', filename='scan.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4 fixture')
        self.assertEqual(candidate.status, 'unavailable')
        self.assertIn('扫描 PDF', candidate.summary)
        self.assertEqual(candidate.review_state, 'pending')
        run.assert_not_called()

    def test_scan_pdf_ocr_is_limited_to_twenty_pages(self):
        rendered = []

        def bounded_stdout(arguments, **kwargs):
            if arguments[0] == '/usr/bin/pdftotext': return b''
            if arguments[0] == '/usr/bin/pdfinfo': return b'Pages: 50\n'
            if arguments[1] == '--list-langs': return b'eng\n'
            return b''

        def render(arguments, **kwargs):
            page = int(arguments[arguments.index('-f') + 1])
            header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
            Path(arguments[-1] + '.png').write_bytes(header + (100).to_bytes(4, 'big') * 2 + b'png')
            rendered.append(page)
            return SimpleNamespace(returncode=0)

        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: f'/usr/bin/{name}'), \
                patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                patch('loomrise.material_processing.subprocess.run', side_effect=render):
            candidate = make_candidate(asset_id='a', version_id='v1', filename='scan.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4 fixture')
        self.assertEqual(rendered, list(range(1, 21)))
        self.assertEqual(candidate.status, 'failed')
        self.assertIn('未识别到可用文字', candidate.summary)

    def test_scan_pdf_ocr_caps_aggregate_text_and_rejects_incomplete_prefix(self):
        rendered = []

        def bounded_stdout(arguments, *, timeout, output_limit, env=None):
            if arguments[0] == '/usr/bin/pdftotext': return b''
            if arguments[0] == '/usr/bin/pdfinfo': return b'Pages: 2\n'
            if arguments[1] == '--list-langs': return b'eng\n'
            self.assertEqual(output_limit, 4)
            return b'abcd'

        def render(arguments, **kwargs):
            page = int(arguments[arguments.index('-f') + 1])
            header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
            Path(arguments[-1] + '.png').write_bytes(header + (100).to_bytes(4, 'big') * 2 + b'png')
            rendered.append(page)
            return SimpleNamespace(returncode=0)

        with patch('loomrise.material_processing._OCR_OUTPUT_LIMIT', 4), \
                patch('loomrise.material_processing.shutil.which', side_effect=lambda name: f'/usr/bin/{name}'), \
                patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                patch('loomrise.material_processing.subprocess.run', side_effect=render):
            candidate = make_candidate(asset_id='a', version_id='v1', filename='scan.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4 fixture')
        self.assertEqual(rendered, [1])
        self.assertEqual(candidate.status, 'failed')
        self.assertIn('超过长度上限', candidate.summary)

    def test_scan_pdf_ocr_rejects_rendered_pixel_and_byte_overflow(self):
        for size, width, expected in ((27, 2001, '渲染尺寸'), (26, 100, '渲染结果')):
            with self.subTest(size=size, width=width):
                def bounded_stdout(arguments, **kwargs):
                    if arguments[0] == '/usr/bin/pdftotext': return b''
                    if arguments[0] == '/usr/bin/pdfinfo': return b'Pages: 1\n'
                    if arguments[1] == '--list-langs': return b'eng\n'
                    return b'OCR text'

                def render(arguments, **kwargs):
                    header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
                    data = header + width.to_bytes(4, 'big') + (100).to_bytes(4, 'big') + b'x' * (size - 24)
                    Path(arguments[-1] + '.png').write_bytes(data)
                    return SimpleNamespace(returncode=0)

                with patch('loomrise.material_processing._PDF_RENDER_BYTES_LIMIT', 25 if expected == '渲染结果' else 100), \
                        patch('loomrise.material_processing.shutil.which', side_effect=lambda name: f'/usr/bin/{name}'), \
                        patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                        patch('loomrise.material_processing.subprocess.run', side_effect=render) as run:
                    candidate = make_candidate(asset_id='a', version_id='v1', filename='scan.pdf',
                                               media_type='application/pdf', content=b'%PDF-1.4 fixture')
                self.assertEqual(candidate.status, 'failed')
                self.assertIn(expected, candidate.summary)
                self.assertEqual(run.call_count, 1)

    def test_scan_pdf_ocr_timeout_is_a_failed_pending_candidate(self):
        def bounded_stdout(arguments, **kwargs):
            if arguments[0] == '/usr/bin/pdftotext': return b''
            if arguments[0] == '/usr/bin/pdfinfo': return b'Pages: 1\n'
            if arguments[1] == '--list-langs': return b'eng\n'
            raise subprocess.TimeoutExpired(arguments[0], kwargs['timeout'])

        def render(arguments, **kwargs):
            header = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR'
            Path(arguments[-1] + '.png').write_bytes(header + (100).to_bytes(4, 'big') * 2 + b'png')
            return SimpleNamespace(returncode=0)

        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: f'/usr/bin/{name}'), \
                patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                patch('loomrise.material_processing.subprocess.run', side_effect=render):
            candidate = make_candidate(asset_id='a', version_id='v1', filename='scan.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4 fixture')
        self.assertEqual(candidate.status, 'failed')
        self.assertIn('超时', candidate.summary)
        self.assertEqual(candidate.review_state, 'pending')

    def test_scan_pdf_ocr_missing_languages_is_unavailable(self):
        def bounded_stdout(arguments, **kwargs):
            if arguments[0] == '/usr/bin/pdftotext': return b''
            if arguments[0] == '/usr/bin/pdfinfo': return b'Pages: 1\n'
            return b'fra\n'

        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: f'/usr/bin/{name}'), \
                patch('loomrise.material_processing._run_bounded_stdout', side_effect=bounded_stdout), \
                patch('loomrise.material_processing.subprocess.run') as run:
            candidate = make_candidate(asset_id='a', version_id='v1', filename='scan.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4 fixture')
        self.assertEqual(candidate.status, 'unavailable')
        self.assertIn('语言包', candidate.summary)
        run.assert_not_called()

    def test_pdf_timeout_nonzero_and_empty_output_fail_closed(self):
        failures = (
            (_FakeProcess(timeout=True), '超时'),
            (_FakeProcess(returncode=1), '提取失败'),
        )
        for process, expected in failures:
            with self.subTest(expected=expected), \
                    patch('loomrise.material_processing.shutil.which', return_value='/usr/bin/pdftotext'), \
                    patch('loomrise.material_processing.subprocess.Popen', return_value=process):
                candidate = make_candidate(asset_id='a', version_id='v1', filename='guide.pdf',
                                           media_type='application/pdf', content=b'%PDF-1.4\nfixture')
            self.assertEqual(candidate.status, 'failed')
            self.assertIn(expected, candidate.summary)
            self.assertEqual(candidate.review_state, 'pending')
            self.assertTrue(process.stdout.closed)
        self.assertTrue(failures[0][0].killed)
        self.assertEqual(failures[0][0].wait_timeouts, [15, None])

    def test_pdf_input_and_extractor_output_limits_fail_closed(self):
        with patch('loomrise.material_processing.MAX_BYTES', 5), \
                patch('loomrise.material_processing.shutil.which', return_value='/usr/bin/pdftotext'), \
                patch('loomrise.material_processing.subprocess.Popen') as popen:
            oversized = make_candidate(asset_id='a', version_id='v1', filename='guide.pdf',
                                       media_type='application/pdf', content=b'%PDF-1.4')
        self.assertEqual(oversized.status, 'failed')
        self.assertIn('10 MiB', oversized.summary)
        popen.assert_not_called()

        process = _FakeProcess(stdout=b'too long')
        with patch('loomrise.material_processing._OCR_OUTPUT_LIMIT', 4), \
                patch('loomrise.material_processing.shutil.which', return_value='/usr/bin/pdftotext'), \
                patch('loomrise.material_processing.subprocess.Popen', return_value=process):
            over_output = make_candidate(asset_id='a', version_id='v1', filename='guide.pdf',
                                         media_type='application/pdf', content=b'%PDF-1.4\nfixture')
        self.assertEqual(over_output.status, 'failed')
        self.assertIn('超过长度上限', over_output.summary)
        self.assertTrue(process.killed)
        self.assertEqual(process.stdout.bytes_read, 5)
        self.assertTrue(process.stdout.closed)

    def test_unknown_formats_are_explicitly_not_fake_processed(self):
        unknown = make_candidate(asset_id='a', version_id='v1', filename='x.bin', media_type='application/octet-stream', content=b'data')
        self.assertEqual(unknown.status, 'unsupported')

    def test_review_state_is_persisted_and_separate_from_processing_status(self):
        from loomrise.durable_store import SqliteStore
        import os, tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'material.db'))
            try:
                material = store.save_material(tenant_id='t', agent_id='a', asset_id='asset', version_id='v1',
                    display_name='文本', filename='text.txt', media_type='text/plain', authorization='owned',
                    expires_at=None, content=b'text')
                row = store.save_material_processing_candidate(candidate_id='c1', tenant_id='t', agent_id='a',
                    asset_id='asset', version_id='v1', kind='summary', status='ready', summary='候选', source_hash=material['content_hash'])
                self.assertEqual(row['review_state'], 'pending')
                reviewed = store.review_material_processing_candidate(tenant_id='t', agent_id='a', candidate_id='c1', review_state='approved')
                self.assertEqual(reviewed['review_state'], 'approved')
            finally: store.close()


if __name__ == '__main__': unittest.main()
