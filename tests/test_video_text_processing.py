import base64
import hashlib
import json
import os
import shutil
import subprocess
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from loomrise.material_processing import make_candidate
from loomrise.material_derivatives import MAX_PIXELS
from tests.test_material_processing import _FakeProcess


PROBE = {
    'format': {'duration': '3.000000'},
    'streams': [
        {'index': 0, 'codec_type': 'video', 'codec_name': 'h264', 'width': 1280, 'height': 720},
        {'index': 1, 'codec_type': 'subtitle', 'codec_name': 'subrip',
         'disposition': {'default': 0}, 'tags': {'language': 'eng'}},
        {'index': 2, 'codec_type': 'subtitle', 'codec_name': 'mov_text',
         'disposition': {'default': 1}, 'tags': {'language': 'zho'}},
    ],
}
AUDIO_PROBE = {
    'format': {'duration': '3.000000'},
    'streams': [
        {'index': 0, 'codec_type': 'video', 'codec_name': 'h264', 'width': 1280, 'height': 720},
        {'index': 1, 'codec_type': 'audio', 'codec_name': 'aac', 'channels': 1,
         'sample_rate': '44100', 'disposition': {'default': 0}, 'tags': {'language': 'eng'}},
        {'index': 2, 'codec_type': 'audio', 'codec_name': 'opus', 'channels': 2,
         'sample_rate': '48000', 'disposition': {'default': 1}, 'tags': {'language': 'zho'}},
    ],
}
SUBTITLES = '1\n00:00:00,100 --> 00:00:00,900\n虚构课程介绍\n\n2\n00:00:01,100 --> 00:00:02,000\n请联系 hello@example.test\n\n'.encode()


class VideoTextProcessingTests(unittest.TestCase):
    original = b'fictional embedded subtitle video'

    def candidate(self, **kwargs):
        return make_candidate(asset_id='video-asset', version_id='video-v1', filename='untrusted.mp4',
                              media_type=kwargs.pop('media_type', 'video/mp4'),
                              content=kwargs.pop('content', self.original), **kwargs)

    def run_candidate(self, probe=PROBE, subtitles=SUBTITLES, *, tesseract=True):
        calls = []
        processes = [_FakeProcess(stdout=json.dumps(probe).encode()), _FakeProcess(stdout=subtitles)]

        def launch(arguments, **kwargs):
            calls.append((arguments, kwargs))
            if len(calls) == 1:
                self.assertEqual(Path(arguments[-1]).read_bytes(), self.original)
            return processes[len(calls) - 1]

        with patch('loomrise.material_processing.shutil.which',
                   side_effect=lambda name: None if name == 'tesseract' and not tesseract else '/tools/' + name), \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=launch):
            candidate = self.candidate()
        return candidate, calls, processes

    def run_frame_ocr_candidate(self, *, duration='300.000000', texts=None, language_output=b'chi_sim\neng\n'):
        probe = {
            'format': {'duration': duration},
            'streams': [{'index': 0, 'codec_type': 'video', 'codec_name': 'h264',
                         'width': 1280, 'height': 720}],
        }
        frame = (b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR'
                 + struct.pack('>II', 640, 360) + b'\x08\x02\x00\x00\x00x')
        texts = texts or [f'R3-FRAME-{index}'.encode() for index in range(1, 6)]
        processes = [_FakeProcess(stdout=json.dumps(probe).encode()),
                     _FakeProcess(stdout=language_output)]
        for text in texts:
            processes.extend([_FakeProcess(stdout=frame), _FakeProcess(stdout=text)])
        calls = []

        def launch(arguments, **kwargs):
            calls.append((arguments, kwargs))
            if len(calls) == 1:
                self.assertEqual(Path(arguments[-1]).read_bytes(), self.original)
            return processes[len(calls) - 1]

        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: '/tools/' + name), \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=launch):
            candidate = self.candidate()
        return candidate, calls, processes

    def test_selected_text_stream_is_extracted_in_order_as_a_pending_summary(self):
        candidate, calls, processes = self.run_candidate()
        self.assertEqual(candidate.status, 'ready')
        self.assertEqual(candidate.kind, 'summary')
        self.assertEqual(candidate.review_state, 'pending')
        self.assertEqual(candidate.source_hash, hashlib.sha256(self.original).hexdigest())
        self.assertIn('仅流 2', candidate.summary)
        self.assertIn('zho', candidate.summary)
        self.assertIn('需人工核对', candidate.summary)
        self.assertIn('虚构课程介绍 请联系 hello@example.test', candidate.summary)
        self.assertNotIn('00:00:', candidate.summary)
        self.assertEqual(len(calls), 2)
        probe, extraction = calls[0][0], calls[1][0]
        self.assertEqual(probe[0], '/tools/ffprobe')
        self.assertEqual(extraction[0], '/tools/ffmpeg')
        self.assertEqual(extraction[extraction.index('-map') + 1], '0:2')
        self.assertEqual(extraction[extraction.index('-f') + 1], 'mov')
        self.assertIn('file,pipe', probe)
        self.assertIn('file,pipe', extraction)
        self.assertNotIn('untrusted.mp4', probe)
        self.assertTrue(all(process.stdout.closed for process in processes))
        self.assertFalse(Path(probe[-1]).exists())

    def test_no_text_subtitle_is_unavailable_without_local_ocr(self):
        for streams in [PROBE['streams'][:1], [PROBE['streams'][0], {
                'index': 1, 'codec_type': 'subtitle', 'codec_name': 'hdmv_pgs_subtitle'}]]:
            with self.subTest(streams=streams):
                candidate, calls, _ = self.run_candidate(
                    probe={**PROBE, 'streams': streams}, tesseract=False)
                self.assertEqual(candidate.status, 'unavailable')
                self.assertIn('未找到支持的内嵌文本字幕', candidate.summary)
                self.assertIn('关键帧 OCR', candidate.summary)
                self.assertEqual(len(calls), 1)

    def test_audio_metadata_is_an_explicit_unavailable_transcript_candidate(self):
        candidate, calls, _ = self.run_candidate(probe=AUDIO_PROBE, tesseract=False)
        self.assertEqual(candidate.status, 'unavailable')
        self.assertEqual(candidate.review_state, 'pending')
        self.assertIn('音频轨元数据候选', candidate.summary)
        self.assertIn('仅流 2', candidate.summary)
        self.assertIn('opus', candidate.summary)
        self.assertIn('2 声道', candidate.summary)
        self.assertIn('48000 Hz', candidate.summary)
        self.assertIn('zho', candidate.summary)
        self.assertIn('未进行语音转写', candidate.summary)
        self.assertIn('需人工核对', candidate.summary)
        self.assertIn('关键帧 OCR', candidate.summary)
        self.assertEqual(len(calls), 1)

    def test_audio_metadata_limits_and_invalid_values_fail_closed(self):
        for field, value in (
            ('channels', 33),
            ('sample_rate', '7999'),
            ('sample_rate', '192001'),
            ('sample_rate', '48k'),
        ):
            with self.subTest(field=field, value=value):
                stream = {**AUDIO_PROBE['streams'][2], field: value}
                probe = {**AUDIO_PROBE, 'streams': [AUDIO_PROBE['streams'][0], stream]}
                candidate, calls, _ = self.run_candidate(probe=probe, tesseract=False)
                self.assertEqual(candidate.status, 'failed')
                self.assertIn('无效', candidate.summary)
                self.assertEqual(len(calls), 1)

    def test_subtitle_summary_records_audio_metadata_without_claiming_transcription(self):
        audio = {**AUDIO_PROBE['streams'][2], 'index': 3}
        probe = {**PROBE, 'streams': [*PROBE['streams'], audio]}
        candidate, _, _ = self.run_candidate(probe=probe)
        self.assertEqual(candidate.status, 'ready')
        self.assertIn('虚构课程介绍 请联系 hello@example.test', candidate.summary)
        self.assertIn('音频轨元数据候选', candidate.summary)
        self.assertIn('未进行语音转写', candidate.summary)
        self.assertNotIn('转写完成', candidate.summary)
        self.assertLessEqual(len(candidate.summary), 500)

    def test_no_text_track_uses_at_most_five_scaled_keyframes_for_pending_ocr(self):
        candidate, calls, processes = self.run_frame_ocr_candidate()
        self.assertEqual(candidate.status, 'ready')
        self.assertEqual(candidate.review_state, 'pending')
        self.assertIn('关键帧 OCR 节选候选', candidate.summary)
        self.assertIn('chi_sim+eng', candidate.summary)
        self.assertIn('需人工核对', candidate.summary)
        self.assertIn('R3-FRAME-1', candidate.summary)
        self.assertEqual(len([call for call in calls if call[0][0] == '/tools/ffmpeg']), 5)
        self.assertEqual(len([call for call in calls if call[0][0] == '/tools/tesseract']), 6)
        frame_calls = [call[0] for call in calls if call[0][0] == '/tools/ffmpeg']
        timestamps = [float(arguments[arguments.index('-ss') + 1]) for arguments in frame_calls]
        self.assertEqual(timestamps, [50.0, 100.0, 150.0, 200.0, 250.0])
        for arguments in frame_calls:
            self.assertEqual(arguments[arguments.index('-frames:v') + 1], '1')
            self.assertEqual(arguments[arguments.index('-vf') + 1],
                             'scale=640:360:force_original_aspect_ratio=decrease')
            self.assertEqual(arguments[-1], 'pipe:1')
        self.assertTrue(all(process.stdout.closed for process in processes))

    def test_video_frame_ocr_missing_tool_or_language_is_unavailable(self):
        with patch('loomrise.material_processing.shutil.which',
                   side_effect=lambda name: None if name == 'tesseract' else '/tools/' + name), \
                patch('loomrise.material_processing.subprocess.Popen',
                      return_value=_FakeProcess(stdout=json.dumps({
                          'format': {'duration': '3'}, 'streams': [PROBE['streams'][0]]}).encode())) as launch:
            missing = self.candidate()
        self.assertEqual(missing.status, 'unavailable')
        self.assertIn('关键帧 OCR', missing.summary)
        launch.assert_called_once()

        no_language, calls, _ = self.run_frame_ocr_candidate(language_output=b'List of available languages:\n')
        self.assertEqual(no_language.status, 'unavailable')
        self.assertIn('语言包', no_language.summary)
        self.assertEqual(len(calls), 2)

    def test_video_frame_ocr_invalid_frame_and_output_overflow_fail_closed(self):
        probe = {'format': {'duration': '3'}, 'streams': [PROBE['streams'][0]]}
        bad_frame = b'not a PNG'
        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: '/tools/' + name), \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=[
                    _FakeProcess(stdout=json.dumps(probe).encode()),
                    _FakeProcess(stdout=b'chi_sim\n'), _FakeProcess(stdout=bad_frame)]):
            invalid = self.candidate()
        self.assertEqual(invalid.status, 'failed')
        self.assertIn('输入/输出无效', invalid.summary)

        frame = (b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR'
                 + struct.pack('>II', 640, 360) + b'\x08\x02\x00\x00\x00x')
        processes = [_FakeProcess(stdout=json.dumps(probe).encode()), _FakeProcess(stdout=b'eng\n'),
                     _FakeProcess(stdout=frame), _FakeProcess(stdout=b'x' * 64_001)]
        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: '/tools/' + name), \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=processes):
            overflow = self.candidate()
        self.assertEqual(overflow.status, 'failed')
        self.assertIn('超过长度上限', overflow.summary)
        self.assertTrue(processes[-1].killed)

    def test_missing_tools_and_unhandled_container_do_not_start_a_process(self):
        for missing in ['ffmpeg', 'ffprobe']:
            with self.subTest(missing=missing), \
                    patch('loomrise.material_processing.shutil.which', side_effect=lambda name: None if name == missing else '/tools/' + name), \
                    patch('loomrise.material_processing.subprocess.Popen') as launch:
                result = self.candidate()
                self.assertEqual(result.status, 'unavailable')
                self.assertIn('FFmpeg', result.summary)
                launch.assert_not_called()
        with patch('loomrise.material_processing.subprocess.Popen') as launch:
            result = self.candidate(media_type='video/quicktime')
        self.assertEqual(result.status, 'unsupported')
        launch.assert_not_called()

    def test_bad_or_unknown_duration_and_malformed_stream_metadata_fail_closed(self):
        invalid = [None, [], {'streams': []}]
        invalid += [{**PROBE, 'format': {'duration': value}} for value in
                    [None, True, 'N/A', 'NaN', 'inf', '-1', '0', '300.1']]
        invalid += [{**PROBE, 'streams': value} for value in [
            None, {}, [None], PROBE['streams'][1:],
            [PROBE['streams'][0], {**PROBE['streams'][1], 'index': True}],
            [PROBE['streams'][0], {**PROBE['streams'][1], 'index': 0}],
            [PROBE['streams'][0], {**PROBE['streams'][1], 'tags': []}],
            [PROBE['streams'][0], {**PROBE['streams'][1], 'disposition': {'default': '1'}}],
        ]]
        for probe in invalid:
            with self.subTest(probe=probe):
                candidate, calls, _ = self.run_candidate(probe=probe)
                self.assertEqual(candidate.status, 'failed')
                self.assertIn('无效', candidate.summary)
                self.assertEqual(candidate.review_state, 'pending')
                self.assertEqual(len(calls), 1)

        for dimensions in [(True, 720), (1280, 0), (MAX_PIXELS, 2)]:
            with self.subTest(dimensions=dimensions):
                video = {**PROBE['streams'][0], 'width': dimensions[0], 'height': dimensions[1]}
                candidate, calls, _ = self.run_candidate(probe={**PROBE, 'streams': [video]})
                self.assertEqual(candidate.status, 'failed')
                self.assertIn('尺寸', candidate.summary)
                self.assertEqual(len(calls), 1)

    def test_source_and_stdout_limits_fail_without_a_truncated_ready_candidate(self):
        with patch('loomrise.material_processing.MAX_BYTES', 4), \
                patch('loomrise.material_processing.subprocess.Popen') as launch:
            candidate = self.candidate()
        self.assertEqual(candidate.status, 'failed')
        self.assertIn('10 MiB', candidate.summary)
        launch.assert_not_called()

        processes = [_FakeProcess(stdout=json.dumps(PROBE).encode()),
                     _FakeProcess(stdout=b'x' * 64_001)]
        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: '/tools/' + name), \
                patch('loomrise.material_processing.subprocess.Popen', side_effect=processes):
            candidate = self.candidate()
        self.assertEqual(candidate.status, 'failed')
        self.assertIn('超过长度上限', candidate.summary)
        self.assertEqual(processes[1].stdout.bytes_read, 64_001)
        self.assertTrue(processes[1].killed)
        self.assertTrue(processes[1].stdout.closed)

    def test_subprocess_failure_timeout_and_total_deadline_never_return_ready(self):
        for failed, expected in [(_FakeProcess(timeout=True), '超时'),
                                 (_FakeProcess(returncode=1), '失败')]:
            with self.subTest(expected=expected), \
                    patch('loomrise.material_processing.shutil.which', side_effect=lambda name: '/tools/' + name), \
                    patch('loomrise.material_processing.subprocess.Popen', side_effect=[
                        _FakeProcess(stdout=json.dumps(PROBE).encode()), failed]):
                candidate = self.candidate()
                self.assertEqual(candidate.status, 'failed')
                self.assertIn(expected, candidate.summary)
                self.assertTrue(failed.stdout.closed)

        with patch('loomrise.material_processing.shutil.which', side_effect=lambda name: '/tools/' + name), \
                patch('loomrise.material_processing.subprocess.Popen', return_value=_FakeProcess(stdout=json.dumps(PROBE).encode())) as launch, \
                patch('loomrise.material_processing.time.monotonic', side_effect=[10, 10.5, 40.1]):
            candidate = self.candidate()
        self.assertEqual(candidate.status, 'failed')
        self.assertIn('超时', candidate.summary)
        self.assertEqual(launch.call_count, 1)

    def test_invalid_subtitle_output_does_not_become_a_summary(self):
        for subtitles in [b'', b'not subtitles', b'\xff',
                          b'1\n00:00:01,100 --> 00:00:00,000\nwrong\n\n',
                          b'1\n00:00:00,100 --> 00:00:05,000\noutside duration\n\n']:
            with self.subTest(subtitles=subtitles):
                candidate, _, _ = self.run_candidate(subtitles=subtitles)
                self.assertEqual(candidate.status, 'failed')
                self.assertIn('无效', candidate.summary)

    def test_long_summary_is_explicitly_an_excerpt_with_a_fixed_bound(self):
        subtitles = ('1\n00:00:00,100 --> 00:00:02,000\n' + '虚构课程 ' * 200 + '\n\n').encode()
        candidate, _, _ = self.run_candidate(subtitles=subtitles)
        self.assertEqual(candidate.status, 'ready')
        self.assertEqual(len(candidate.summary), 500)
        self.assertIn('节选', candidate.summary)

    def test_subtitle_candidate_requires_manual_review_before_material_search(self):
        from loomrise.durable_store import SqliteStore

        candidate, _, _ = self.run_candidate()
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'video.db'))
            try:
                material = store.save_material(tenant_id='t', agent_id='a', asset_id='video-asset',
                    version_id='video-v1', display_name='虚构课程视频', filename='guide.mp4',
                    media_type='video/mp4', authorization='owned', expires_at=None, content=self.original)
                store.save_material_processing_candidate(candidate_id='video-candidate', tenant_id='t',
                    agent_id='a', asset_id=candidate.asset_id, version_id=candidate.version_id,
                    kind=candidate.kind, status=candidate.status, summary=candidate.summary,
                    source_hash=candidate.source_hash)
                query = {'tenant_id': 't', 'agent_id': 'a', 'query': '课程', 'limit': 10}
                self.assertEqual(store.search_material_summaries(**query), [])
                reviewed = store.review_material_processing_candidate(tenant_id='t', agent_id='a',
                    candidate_id='video-candidate', review_state='approved')
                self.assertEqual(reviewed['review_state'], 'approved')
                self.assertEqual(store.search_material_summaries(**query)[0]['source_hash'], material['content_hash'])
                self.assertEqual(store.material_version(tenant_id='t', agent_id='a', asset_id='video-asset')['content'], self.original)
            finally:
                store.close()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'optional FFmpeg is unavailable')
class RealVideoTextProcessingTests(unittest.TestCase):
    def test_original_mp4_and_webm_text_tracks_are_actually_decoded(self):
        from loomrise.configuration import ConfigurationPrincipal, ConfigurationService
        from loomrise.customer_service import CustomerService, CustomerServiceApplication
        from loomrise.durable_store import SqliteStore

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            english, chinese = root / 'english.srt', root / 'chinese.srt'
            english.write_text('1\n00:00:00,100 --> 00:00:02,000\nR3-VIDEO-EN-7319\n\n', encoding='utf-8')
            chinese.write_text('1\n00:00:00,100 --> 00:00:00,900\n虚构课程 R3-VIDEO-ZH-7319\n\n'
                               '2\n00:00:01,100 --> 00:00:02,000\n请联系 hello@example.test\n\n', encoding='utf-8')
            for extension, video_codec, subtitle_codec in [('mp4', 'libx264', 'mov_text'),
                                                           ('webm', 'libvpx-vp9', 'webvtt')]:
                with self.subTest(container=extension):
                    source = root / ('sample.' + extension)
                    subprocess.run([shutil.which('ffmpeg'), '-nostdin', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:d=3:r=5', '-i', str(english), '-i', str(chinese),
                        '-map', '0:v:0', '-map', '1:s:0', '-map', '2:s:0', '-c:v', video_codec,
                        '-pix_fmt', 'yuv420p', '-c:s', subtitle_codec, '-metadata:s:s:0', 'language=eng',
                        '-metadata:s:s:1', 'language=zho', '-disposition:s:0', '0', '-disposition:s:1', 'default', str(source)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=True, timeout=20)
                    original = source.read_bytes()
                    candidate = make_candidate(asset_id='original-synthetic-video', version_id='v1',
                        filename=source.name, media_type='video/' + extension, content=original)
                    self.assertEqual(candidate.status, 'ready', candidate)
                    self.assertEqual(candidate.review_state, 'pending')
                    self.assertIn('仅流 2', candidate.summary)
                    self.assertIn('虚构课程 R3-VIDEO-ZH-7319 请联系 hello@example.test', candidate.summary)
                    self.assertNotIn('R3-VIDEO-EN-7319', candidate.summary)
                    self.assertEqual(candidate.source_hash, hashlib.sha256(original).hexdigest())
                    self.assertEqual(source.read_bytes(), original)
                    store = SqliteStore(str(root / (extension + '.db')))
                    try:
                        principal = ConfigurationPrincipal('t', 'owner', 'owner', ('a',))
                        service = CustomerService(store, ConfigurationService(store))
                        app = CustomerServiceApplication(service)
                        material = service.create_material(principal=principal, agent_id='a',
                            filename=source.name, display_name='原创虚构课程视频', authorization='owned',
                            content_base64=base64.b64encode(original).decode())
                        response = app.execute(principal=principal, action='material.process',
                            payload={'agent_id': 'a', 'asset_id': material['asset_id']})
                        self.assertTrue(response['ok'], response)
                        result = response['result']
                        self.assertEqual((result['status'], result['review_state']), ('ready', 'pending'))
                        self.assertFalse(result['is_downloadable_derivative'])
                        self.assertEqual(result['source_hash'], material['content_hash'])
                        query = {'tenant_id': 't', 'agent_id': 'a', 'query': 'R3-VIDEO-ZH-7319', 'limit': 10}
                        self.assertEqual(store.search_material_summaries(**query), [])
                        service.review_processing_candidate(principal=principal, agent_id='a',
                            candidate_id=result['candidate_id'], review_state='approved')
                        self.assertEqual(len(store.search_material_summaries(**query)), 1)
                        self.assertEqual(store.material_version(tenant_id='t', agent_id='a',
                            asset_id=material['asset_id'])['content'], original)
                    finally:
                        store.close()

    def test_original_mp4_and_webm_keyframes_are_decoded_with_bounded_dimensions(self):
        real_which = shutil.which
        ffmpeg = real_which('ffmpeg')
        self.assertTrue(ffmpeg)
        real_popen = subprocess.Popen

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extension, video_codec in [('mp4', 'libx264'), ('webm', 'libvpx-vp9')]:
                with self.subTest(container=extension):
                    source = root / ('no-text-track.' + extension)
                    subprocess.run([ffmpeg, '-nostdin', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', 'color=c=white:s=1280x720:d=3:r=2', '-an', '-c:v', video_codec,
                        '-pix_fmt', 'yuv420p', str(source)], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20)
                    original = source.read_bytes()
                    frames = []

                    def launch(arguments, **kwargs):
                        if arguments[0] == '/tools/tesseract':
                            if arguments[1] == '--list-langs':
                                return _FakeProcess(stdout=b'chi_sim\neng\n')
                            frame_bytes = Path(arguments[1]).read_bytes()
                            self.assertLessEqual(len(frame_bytes), 2_000_000)
                            self.assertEqual(frame_bytes[:8], b'\x89PNG\r\n\x1a\n')
                            self.assertEqual(frame_bytes[12:16], b'IHDR')
                            width, height = struct.unpack('>II', frame_bytes[16:24])
                            self.assertLessEqual(width, 640)
                            self.assertLessEqual(height, 360)
                            frames.append(frame_bytes)
                            return _FakeProcess(stdout=f'R3-{extension}-frame-{len(frames)}'.encode())
                        return real_popen(arguments, **kwargs)

                    def which(name):
                        return '/tools/tesseract' if name == 'tesseract' else real_which(name)

                    with patch('loomrise.material_processing.shutil.which', side_effect=which), \
                            patch('loomrise.material_processing.subprocess.Popen', side_effect=launch):
                        candidate = make_candidate(asset_id='keyframe-video', version_id='v1',
                            filename=source.name, media_type='video/' + extension, content=original)
                    self.assertEqual(candidate.status, 'ready', candidate)
                    self.assertEqual(candidate.review_state, 'pending')
                    self.assertIn('R3-' + extension + '-frame-1', candidate.summary)
                    self.assertEqual(len(frames), 5)
                    self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
