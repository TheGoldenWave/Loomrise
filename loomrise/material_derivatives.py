"""Bounded local media transforms. No network inputs or generated scripts."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_DURATION = 300
PROCESSOR_VERSION = 'local-media-v1'
SOURCE_TYPES = {
    'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp',
    'video/mp4': '.mp4', 'video/webm': '.webm',
}
DEMUXERS = {'image/png': 'png_pipe', 'image/jpeg': 'jpeg_pipe', 'image/webp': 'webp_pipe',
            'video/mp4': 'mov', 'video/webm': 'matroska'}


@dataclass(frozen=True)
class Derivative:
    kind: str
    filename: str
    media_type: str
    content: bytes
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MediaProcessingResult:
    status: str
    reason: str = ''
    artifacts: list[Derivative] = field(default_factory=list)


def _run(arguments: list[str], *, timeout: int = 25) -> bytes:
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=timeout, check=True)
    if len(result.stdout) > 64_000:
        raise ValueError('processor_output_limit')
    return result.stdout


def _probe(binary: str, source: Path, *, demuxer: str | None = None) -> dict[str, Any]:
    value = json.loads(_run([binary, '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-select_streams', 'v:0', '-show_entries', 'stream=width,height,codec_type:format=duration',
        '-of', 'json', *(['-f', demuxer] if demuxer else []), str(source)], timeout=10))
    streams = value.get('streams', [])
    if len(streams) != 1:
        raise ValueError('missing_visual_stream')
    width, height = streams[0].get('width'), streams[0].get('height')
    if type(width) is not int or type(height) is not int or min(width, height) < 1 or width * height > MAX_PIXELS:
        raise ValueError('image_dimensions_limit')
    result = {'width': width, 'height': height}
    duration = value.get('format', {}).get('duration')
    if duration is not None:
        duration = float(duration)
        if not math.isfinite(duration) or duration <= 0 or duration > MAX_DURATION:
            raise ValueError('video_duration_limit')
        result['duration_seconds'] = duration
    return result


def process_media(*, media_type: str, content: bytes) -> MediaProcessingResult:
    if media_type not in SOURCE_TYPES:
        return MediaProcessingResult('not_applicable')
    if not content or len(content) > MAX_BYTES:
        return MediaProcessingResult('failed', 'source_size_limit')
    encoder, probe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not encoder or not probe:
        return MediaProcessingResult('unavailable', 'ffmpeg_required')
    try:
        version = _run([encoder, '-version'], timeout=5).decode().splitlines()[0]
        with tempfile.TemporaryDirectory(prefix='loomrise-media-') as directory:
            root = Path(directory)
            source = root / ('source' + SOURCE_TYPES[media_type])
            source.write_bytes(content)
            original = _probe(probe, source, demuxer=DEMUXERS[media_type])
            video = media_type.startswith('video/')
            if video and 'duration_seconds' not in original:
                raise ValueError('video_duration_unknown')
            base = [encoder, '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror', '-y',
                    '-protocol_whitelist', 'file,pipe', '-threads', '1', '-f', DEMUXERS[media_type], '-i', str(source),
                    '-map_metadata', '-1', '-threads', '1']
            outputs = []
            preview = root / 'preview.png'
            _run([*base, '-map', '0:v:0', '-frames:v', '1', '-vf',
                  "scale=w='min(1024,iw)':h='min(1024,ih)':force_original_aspect_ratio=decrease",
                  '-c:v', 'png', '-compression_level', '9', '-fs', str(MAX_BYTES), str(preview)])
            outputs.append(('cover' if video else 'image_preview', preview, 'image/png'))
            if video:
                output = root / 'optimized.mp4'
                _run([*base, '-map', '0:v:0', '-map', '0:a:0?', '-vf',
                      "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                      '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p',
                      '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart',
                      '-fs', str(MAX_BYTES), str(output)])
                outputs.append(('video_optimized', output, 'video/mp4'))
            artifacts = []
            for kind, output, output_type in outputs:
                data = output.read_bytes()
                if not data or len(data) >= MAX_BYTES:
                    raise ValueError('derivative_size_limit')
                observed = _probe(probe, output)
                if output_type == 'video/mp4':
                    tolerance = min(0.1, original['duration_seconds'] * 0.02)
                    if abs(observed.get('duration_seconds', 0) - original['duration_seconds']) > tolerance:
                        raise ValueError('incomplete_video_output')
                metadata = {**observed, 'processor': PROCESSOR_VERSION, 'tool_version': version,
                    'source_hash': hashlib.sha256(content).hexdigest(), 'source_bytes': len(content),
                    'output_bytes': len(data), 'content_hash': hashlib.sha256(data).hexdigest(),
                    'smaller_than_source': len(data) < len(content)}
                artifacts.append(Derivative(kind, output.name, output_type, data, metadata))
            return MediaProcessingResult('ready', artifacts=artifacts)
    except subprocess.TimeoutExpired:
        return MediaProcessingResult('failed', 'processing_timeout')
    except subprocess.CalledProcessError:
        return MediaProcessingResult('failed', 'media_decode_or_encode_failed')
    except (OSError, ValueError, KeyError, TypeError):
        return MediaProcessingResult('failed', 'invalid_or_unsupported_media')
