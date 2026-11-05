import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from loomrise.material_derivatives import process_media


def png_bytes(width=2048, height=1024):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    pixels = (b'\0' + b'\x23\x74\xa5' * width) * height
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'optional FFmpeg is unavailable')
class MediaProcessorTests(unittest.TestCase):
    def test_image_preview_has_real_bytes_dimensions_and_source_provenance(self):
        original = png_bytes()
        result = process_media(media_type='image/png', content=original)
        self.assertEqual(result.status, 'ready', result)
        preview = result.artifacts[0]
        self.assertEqual((preview.kind, preview.media_type), ('image_preview', 'image/png'))
        self.assertTrue(preview.content.startswith(b'\x89PNG'))
        self.assertEqual((preview.metadata['width'], preview.metadata['height']), (1024, 512))
        self.assertEqual(preview.metadata['source_hash'], hashlib.sha256(original).hexdigest())
        self.assertEqual(preview.metadata['content_hash'], hashlib.sha256(preview.content).hexdigest())
        self.assertEqual(preview.metadata['output_bytes'], len(preview.content))

    def test_video_produces_playable_complete_output_and_a_real_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mp4'
            subprocess.run([shutil.which('ffmpeg'), '-nostdin', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'color=c=blue:s=320x240:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)],
                check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            original = source.read_bytes()
        result = process_media(media_type='video/mp4', content=original)
        self.assertEqual(result.status, 'ready', result)
        self.assertEqual({artifact.kind for artifact in result.artifacts}, {'cover', 'video_optimized'})
        video = next(item for item in result.artifacts if item.kind == 'video_optimized')
        self.assertAlmostEqual(video.metadata['duration_seconds'], 1, delta=0.1)
        self.assertIn(b'ftyp', video.content[:16])
        self.assertEqual(video.metadata['smaller_than_source'], len(video.content) < len(original))

    def test_invalid_source_returns_no_downloadable_artifact(self):
        result = process_media(media_type='image/png', content=b'\x89PNG\r\n\x1a\nbroken')
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.artifacts, [])


class MediaProcessorBoundaryTests(unittest.TestCase):
    def test_missing_dependency_and_timeout_are_explicit_without_artifacts(self):
        with patch('loomrise.material_derivatives.shutil.which', return_value=None):
            result = process_media(media_type='image/png', content=b'png')
            self.assertEqual((result.status, result.reason, result.artifacts), ('unavailable', 'ffmpeg_required', []))
        with patch('loomrise.material_derivatives.shutil.which', return_value='ffmpeg'), \
                patch('loomrise.material_derivatives._run', side_effect=subprocess.TimeoutExpired('ffmpeg', 1)):
            result = process_media(media_type='image/png', content=b'png')
            self.assertEqual((result.status, result.reason, result.artifacts), ('failed', 'processing_timeout', []))
