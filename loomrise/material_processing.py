"""Deterministic, review-gated material processing candidates."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .material_derivatives import DEMUXERS, MAX_BYTES, MAX_DURATION, MAX_PIXELS, SOURCE_TYPES, process_media

_OCR_MEDIA_TYPES = {'image/png', 'image/jpeg', 'image/webp'}
_OCR_LANGUAGES = ('chi_sim', 'eng')
_OCR_OUTPUT_LIMIT = 64_000
_PDF_PAGE_LIMIT = 20
_PDF_OCR_TIMEOUT = 30
_PDF_RENDER_SCALE = 2000
_PDF_RENDER_PIXEL_LIMIT = _PDF_RENDER_SCALE * _PDF_RENDER_SCALE
_PDF_RENDER_BYTES_LIMIT = 12_500_000
_VIDEO_TEXT_CODECS = {'mov_text', 'subrip', 'ass', 'ssa', 'webvtt', 'text'}
_VIDEO_TEXT_TIMEOUT = 30
_VIDEO_TEXT_OUTPUT_LIMIT = 64_000
_VIDEO_AUDIO_CHANNEL_LIMIT = 32
_VIDEO_AUDIO_SAMPLE_RATE_MIN = 8_000
_VIDEO_AUDIO_SAMPLE_RATE_MAX = 192_000
_VIDEO_OCR_FRAME_COUNT = 5
_VIDEO_OCR_FRAME_BYTES_LIMIT = 2_000_000
_VIDEO_OCR_FRAME_WIDTH = 640
_VIDEO_OCR_FRAME_HEIGHT = 360


def _pdf_remaining(deadline: float, *, limit: float | None = None) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired('pdf_processing', _PDF_OCR_TIMEOUT)
    return min(remaining, limit) if limit is not None else remaining


def _check_rendered_page(path: Path) -> None:
    size = path.stat().st_size
    if size <= 24 or size > _PDF_RENDER_BYTES_LIMIT:
        raise ValueError('pdf_render_output_limit')
    with path.open('rb') as image:
        header = image.read(24)
    if header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise ValueError('pdf_render_invalid')
    width, height = struct.unpack('>II', header[16:24])
    if (not width or not height or width > _PDF_RENDER_SCALE or height > _PDF_RENDER_SCALE
            or width * height > _PDF_RENDER_PIXEL_LIMIT):
        raise ValueError('pdf_render_pixel_limit')


def _run_bounded_stdout(arguments: list[str], *, timeout: float, output_limit: int,
                        env: dict[str, str] | None = None) -> bytes:
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=env)
    output = bytearray()
    output_exceeded = False
    read_errors: list[OSError] = []

    def terminate() -> None:
        try:
            process.kill()
        except ProcessLookupError:
            pass

    def drain_stdout() -> None:
        nonlocal output_exceeded
        if process.stdout is None:
            read_errors.append(OSError('subprocess stdout unavailable'))
            terminate()
            return
        try:
            while True:
                remaining = output_limit + 1 - len(output)
                chunk = process.stdout.read(min(8192, remaining))
                if not chunk:
                    return
                output.extend(chunk)
                if len(output) > output_limit:
                    output_exceeded = True
                    terminate()
                    return
        except OSError as exc:
            read_errors.append(exc)
            terminate()

    reader = threading.Thread(target=drain_stdout, daemon=True)
    started = False
    try:
        reader.start()
        started = True
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate()
        process.wait()
        raise
    finally:
        if process.poll() is None:
            terminate()
            process.wait()
        if started:
            reader.join()
        if process.stdout is not None:
            process.stdout.close()

    if output_exceeded:
        raise ValueError('processing_output_limit')
    if read_errors:
        raise read_errors[0]
    if returncode:
        raise subprocess.CalledProcessError(returncode, arguments)
    return bytes(output)


@dataclass(frozen=True)
class ProcessingCandidate:
    asset_id: str
    version_id: str
    kind: str
    status: str
    summary: str
    source_hash: str
    review_state: str = 'pending'


def _ocr_image(*, asset_id: str, version_id: str, media_type: str,
               content: bytes, source_hash: str) -> ProcessingCandidate:
    binary = shutil.which('tesseract')
    if not binary:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'unavailable',
                                   '本机未安装 Tesseract；未提取图片文字，原件保留。', source_hash)

    preview = process_media(media_type=media_type, content=content)
    if preview.status != 'ready':
        reasons = {
            'ffmpeg_required': '需要安装图片处理组件',
            'processing_timeout': '图片预处理超时',
            'source_size_limit': '原始图片超过处理上限',
            'invalid_or_unsupported_media': '图片格式、尺寸不受支持或文件已损坏',
        }
        return ProcessingCandidate(asset_id, version_id, 'summary', preview.status,
                                   f"未生成 OCR 文字：{reasons.get(preview.reason, '图片预处理未完成')}；原件保留。",
                                   source_hash)
    image = next((item for item in preview.artifacts if item.kind == 'image_preview'), None)
    if image is None:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   '未生成 OCR 文字：没有可用的安全预览；原件保留。', source_hash)

    try:
        with tempfile.TemporaryDirectory(prefix='loomrise-ocr-') as directory:
            preview_path = Path(directory) / 'preview.png'
            preview_path.write_bytes(image.content)
            env = {key: os.environ[key] for key in ('PATH', 'TESSDATA_PREFIX') if key in os.environ}
            env['OMP_THREAD_LIMIT'] = '1'
            languages_output = _run_bounded_stdout(
                [binary, '--list-langs'], timeout=5, output_limit=_OCR_OUTPUT_LIMIT, env=env,
            )
            available = set(languages_output.decode('utf-8', errors='replace').splitlines())
            languages = [language for language in _OCR_LANGUAGES if language in available]
            if not languages:
                return ProcessingCandidate(asset_id, version_id, 'summary', 'unavailable',
                    '本机未安装简体中文或英文 OCR 语言包；未提取图片文字，原件保留。', source_hash)
            result = _run_bounded_stdout(
                [binary, str(preview_path), 'stdout', '--psm', '6', '-l', '+'.join(languages)],
                timeout=15, output_limit=_OCR_OUTPUT_LIMIT, env=env,
            )
            text = ' '.join(result.decode('utf-8').split())
            if not text:
                return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                    'OCR 未识别到可用文字；没有生成内容候选，原件保留。', source_hash)
            label = f"OCR 候选（{'+'.join(languages)}，需人工核对）："
            return ProcessingCandidate(asset_id, version_id, 'summary', 'ready',
                                       f'{label} {text}'[:500], source_hash)
    except subprocess.TimeoutExpired:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   'OCR 处理超时；没有生成内容候选，原件保留。', source_hash)
    except subprocess.CalledProcessError:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   'OCR 处理失败；没有生成内容候选，原件保留。', source_hash)
    except (OSError, UnicodeDecodeError, ValueError):
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   'OCR 输入或输出无效；没有生成内容候选，原件保留。', source_hash)


def _extract_pdf_text(*, asset_id: str, version_id: str,
                      content: bytes, source_hash: str) -> ProcessingCandidate:
    binary = shutil.which('pdftotext')
    if not binary:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'unavailable',
                                   '本机未安装 pdftotext；未提取 PDF 文字，原件保留。', source_hash)
    if not content.startswith(b'%PDF-') or len(content) > MAX_BYTES:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   'PDF 输入无效或超过 10 MiB 处理上限；原件保留。', source_hash)

    deadline = time.monotonic() + _PDF_OCR_TIMEOUT
    try:
        with tempfile.TemporaryDirectory(prefix='loomrise-pdf-') as directory:
            source_path = Path(directory) / 'source.pdf'
            source_path.write_bytes(content)
            text_bytes = _run_bounded_stdout(
                [binary, '-enc', 'UTF-8', '-f', '1', '-l', str(_PDF_PAGE_LIMIT),
                 str(source_path), '-'],
                timeout=_pdf_remaining(deadline, limit=15), output_limit=_OCR_OUTPUT_LIMIT,
            )
            pages = text_bytes.decode('utf-8').split('\f')
            if text_bytes.endswith(b'\f'):
                pages.pop()  # The last separator ends a page; preceding empty pages still need OCR.
            page_texts = [' '.join(page.split()).encode('utf-8') for page in pages[:_PDF_PAGE_LIMIT]]
            native_text = b' '.join(page for page in page_texts if page).decode('utf-8')
            if native_text and all(page_texts):
                summary = f'PDF 文本候选（前 {_PDF_PAGE_LIMIT} 页，需人工核对）：{native_text}'[:500]
                return ProcessingCandidate(asset_id, version_id, 'summary', 'ready', summary, source_hash)

            info = shutil.which('pdfinfo')
            renderer = shutil.which('pdftoppm')
            tesseract = shutil.which('tesseract')
            if not info or not renderer or not tesseract:
                return ProcessingCandidate(asset_id, version_id, 'summary', 'unavailable',
                    '扫描 PDF OCR 需要 Poppler pdfinfo/pdftoppm、Tesseract 与中文或英文语言包；原件保留。',
                    source_hash)

            env = {key: os.environ[key] for key in ('PATH', 'TESSDATA_PREFIX') if key in os.environ}
            env['LC_ALL'] = 'C'
            env['OMP_THREAD_LIMIT'] = '1'
            info_bytes = _run_bounded_stdout(
                [info, str(source_path)], timeout=_pdf_remaining(deadline, limit=5),
                output_limit=_OCR_OUTPUT_LIMIT, env=env,
            )
            match = re.search(rb'(?m)^Pages:\s*(\d+)\s*$', info_bytes)
            if not match or int(match.group(1)) < 1:
                return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                    'PDF 页数信息无效；没有生成内容候选，原件保留。', source_hash)
            page_count = min(int(match.group(1)), _PDF_PAGE_LIMIT)
            if len(page_texts) > page_count:
                raise ValueError('pdf_page_count_mismatch')
            page_texts.extend([b''] * (page_count - len(page_texts)))

            language_bytes = _run_bounded_stdout(
                [tesseract, '--list-langs'], timeout=_pdf_remaining(deadline, limit=5),
                output_limit=_OCR_OUTPUT_LIMIT, env=env,
            )
            available = set(language_bytes.decode('utf-8', errors='replace').splitlines())
            languages = [language for language in _OCR_LANGUAGES if language in available]
            if not languages:
                return ProcessingCandidate(asset_id, version_id, 'summary', 'unavailable',
                    '本机未安装简体中文或英文 OCR 语言包；未提取扫描 PDF 文字，原件保留。', source_hash)

            nonempty_pages = sum(bool(page) for page in page_texts)
            output_size = sum(map(len, page_texts)) + max(0, nonempty_pages - 1)
            for page, native_page in enumerate(page_texts, 1):
                if native_page:
                    continue
                _pdf_remaining(deadline)
                remaining_output = _OCR_OUTPUT_LIMIT - output_size - (1 if nonempty_pages else 0)
                if remaining_output <= 0:
                    raise ValueError('pdf_output_limit')
                prefix = Path(directory) / f'page-{page}'
                subprocess.run(
                    [renderer, '-f', str(page), '-l', str(page), '-singlefile',
                     '-scale-to', str(_PDF_RENDER_SCALE), '-png', str(source_path), str(prefix)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=_pdf_remaining(deadline), check=True,
                )
                image_path = prefix.with_suffix('.png')
                _check_rendered_page(image_path)
                page_text = _run_bounded_stdout(
                    [tesseract, str(image_path), 'stdout', '--psm', '6', '-l', '+'.join(languages)],
                    timeout=_pdf_remaining(deadline), output_limit=remaining_output, env=env,
                )
                page_text = ' '.join(page_text.decode('utf-8').split()).encode('utf-8')
                if page_text:
                    page_texts[page - 1] = page_text
                    output_size += len(page_text) + (1 if nonempty_pages else 0)
                    nonempty_pages += 1
                image_path.unlink(missing_ok=True)

        text = b' '.join(page for page in page_texts if page).decode('utf-8')
        if not text:
            return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                       'PDF OCR 未识别到可用文字；没有生成内容候选，原件保留。', source_hash)
        kind = '混合文本/OCR' if native_text else '扫描件 OCR'
        summary = f'PDF {kind} 候选（前 {page_count} 页，需人工核对）：{text}'[:500]
        return ProcessingCandidate(asset_id, version_id, 'summary', 'ready', summary, source_hash)
    except subprocess.TimeoutExpired:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   'PDF 文本/OCR 处理超时；没有生成内容候选，原件保留。', source_hash)
    except subprocess.CalledProcessError:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   'PDF 文本提取失败；没有生成内容候选，原件保留。', source_hash)
    except ValueError as exc:
        if str(exc) in {'pdf_output_limit', 'processing_output_limit'}:
            return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                       'PDF 提取结果超过长度上限；没有生成内容候选，原件保留。', source_hash)
        if str(exc) == 'pdf_render_output_limit':
            return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                       'PDF 单页渲染结果超过安全上限；没有生成内容候选，原件保留。', source_hash)
        if str(exc) == 'pdf_render_pixel_limit':
            return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                       'PDF 单页渲染尺寸超过安全上限；没有生成内容候选，原件保留。', source_hash)
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   'PDF 输入或提取结果无效；没有生成内容候选，原件保留。', source_hash)
    except (OSError, UnicodeDecodeError):
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
                                   'PDF 输入或提取结果无效；没有生成内容候选，原件保留。', source_hash)


def _video_remaining(deadline: float, *, limit: float | None = None) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired('video_subtitles', _VIDEO_TEXT_TIMEOUT)
    return min(remaining, limit) if limit is not None else remaining


def _subtitle_text(output: bytes, duration: float) -> str:
    text = output.decode('utf-8-sig').replace('\r\n', '\n').strip()
    if not text or any(ord(char) < 32 and char not in '\n\r\t' for char in text):
        raise ValueError('subtitle_text_invalid')
    parts = []
    previous_start = -1.0
    timestamp = r'(\d{2}):([0-5]\d):([0-5]\d),(\d{3})'
    for number, block in enumerate(re.split(r'\n\s*\n', text), 1):
        lines = block.splitlines()
        match = re.fullmatch(timestamp + ' --> ' + timestamp, lines[1]) if len(lines) >= 3 else None
        if not match or lines[0] != str(number):
            raise ValueError('subtitle_cue_invalid')
        values = list(map(int, match.groups()))
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        if start < previous_start or end <= start or end > duration + .1:
            raise ValueError('subtitle_time_invalid')
        body = ' '.join(' '.join(lines[2:]).split())
        if not body:
            raise ValueError('subtitle_text_empty')
        parts.append(body)
        previous_start = start
    return ' '.join(parts)


def _check_video_ocr_frame(output: bytes) -> None:
    if len(output) <= 24 or len(output) > _VIDEO_OCR_FRAME_BYTES_LIMIT:
        raise ValueError('video_frame_output_limit')
    if output[:8] != b'\x89PNG\r\n\x1a\n' or output[12:16] != b'IHDR':
        raise ValueError('video_frame_invalid')
    width, height = struct.unpack('>II', output[16:24])
    if (not width or not height or width > _VIDEO_OCR_FRAME_WIDTH
            or height > _VIDEO_OCR_FRAME_HEIGHT
            or width * height > _VIDEO_OCR_FRAME_WIDTH * _VIDEO_OCR_FRAME_HEIGHT):
        raise ValueError('video_frame_pixel_limit')


def _check_video_ocr_source(stream: dict[str, Any]) -> None:
    width, height = stream.get('width'), stream.get('height')
    if (type(width) is not int or type(height) is not int or width < 1 or height < 1
            or width * height > MAX_PIXELS):
        raise ValueError('video_frame_source_pixel_limit')


def _audio_track_summary(track: tuple[bool, int, str, str, int | None, int | None]) -> str:
    """Return bounded, non-transcript evidence for one selected audio stream."""
    _, index, language, codec, channels, sample_rate = track
    channel_text = f'{channels} 声道' if channels is not None else '声道未知'
    rate_text = f'{sample_rate} Hz' if sample_rate is not None else '采样率未知'
    return (f'音频轨元数据候选（仅流 {index}，{codec}，{channel_text}，{rate_text}，{language}；'
            '未进行语音转写，需人工核对）')


def _video_timestamp(seconds: float) -> str:
    whole = int(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def _extract_video_frame_ocr(*, asset_id: str, version_id: str, source: Path,
                             source_hash: str, duration: float, encoder: str,
                             demuxer: str, deadline: float,
                             audio_summary: str | None = None) -> ProcessingCandidate:
    tesseract = shutil.which('tesseract')
    if not tesseract:
        prefix = f'{audio_summary}；' if audio_summary else ''
        return ProcessingCandidate(asset_id, version_id, 'summary', 'unavailable',
            f'{prefix}未找到支持的内嵌文本字幕；关键帧 OCR 需要本机 Tesseract，原件保留。', source_hash)

    env = {key: os.environ[key] for key in ('PATH', 'TESSDATA_PREFIX') if key in os.environ}
    env['LC_ALL'] = 'C'
    env['OMP_THREAD_LIMIT'] = '1'
    language_output = _run_bounded_stdout(
        [tesseract, '--list-langs'], timeout=_video_remaining(deadline, limit=5),
        output_limit=_VIDEO_TEXT_OUTPUT_LIMIT, env=env,
    )
    available = set(language_output.decode('utf-8', errors='replace').splitlines())
    languages = [language for language in _OCR_LANGUAGES if language in available]
    if not languages:
        prefix = f'{audio_summary}；' if audio_summary else ''
        return ProcessingCandidate(asset_id, version_id, 'summary', 'unavailable',
            f'{prefix}未找到支持的内嵌文本字幕；本机没有简体中文或英文 OCR 语言包，原件保留。',
            source_hash)

    extracted = []
    output_size = 0
    with tempfile.TemporaryDirectory(prefix='loomrise-video-ocr-') as directory:
        for index in range(_VIDEO_OCR_FRAME_COUNT):
            timestamp = duration * (index + 1) / (_VIDEO_OCR_FRAME_COUNT + 1)
            frame = _run_bounded_stdout(
                [encoder, '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror',
                 '-protocol_whitelist', 'file,pipe', '-threads', '1', '-ss', f'{timestamp:.3f}',
                 '-f', demuxer, '-i', str(source), '-map', '0:v:0', '-frames:v', '1',
                 '-vf', f'scale={_VIDEO_OCR_FRAME_WIDTH}:{_VIDEO_OCR_FRAME_HEIGHT}:'
                        'force_original_aspect_ratio=decrease',
                 '-an', '-sn', '-dn', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'],
                timeout=_video_remaining(deadline), output_limit=_VIDEO_OCR_FRAME_BYTES_LIMIT,
                env=env,
            )
            _check_video_ocr_frame(frame)
            frame_path = Path(directory) / f'frame-{index + 1}.png'
            frame_path.write_bytes(frame)
            remaining_output = _VIDEO_TEXT_OUTPUT_LIMIT - output_size
            if remaining_output <= 0:
                raise ValueError('processing_output_limit')
            recognized = _run_bounded_stdout(
                [tesseract, str(frame_path), 'stdout', '--psm', '6', '-l', '+'.join(languages)],
                timeout=_video_remaining(deadline), output_limit=remaining_output, env=env,
            )
            output_size += len(recognized)
            text = ' '.join(recognized.decode('utf-8').split())
            if any(ord(char) < 32 for char in text):
                raise ValueError('video_ocr_text_invalid')
            if text:
                extracted.append(f'[{_video_timestamp(timestamp)}] {text}')

    if not extracted:
        prefix = f'{audio_summary}；' if audio_summary else ''
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
            f'{prefix}关键帧 OCR 未识别到可用文字；没有生成内容候选，原件保留。', source_hash)
    summary = (f"视频关键帧 OCR 节选候选（最多 {_VIDEO_OCR_FRAME_COUNT} 帧，"
               f"{'+'.join(languages)}，需人工核对）：{' '.join(extracted)}")[:500]
    if audio_summary:
        summary = f'{audio_summary}；{summary}'[:500]
    return ProcessingCandidate(asset_id, version_id, 'summary', 'ready', summary, source_hash)


def _extract_video_subtitles(*, asset_id: str, version_id: str, media_type: str,
                             content: bytes, source_hash: str) -> ProcessingCandidate:
    if media_type not in {'video/mp4', 'video/webm'}:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'unsupported',
            '此视频容器尚未接入字幕提取或语音转写；未生成文字内容，原件保留。', source_hash)
    if not content or len(content) > MAX_BYTES:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'failed',
            '视频输入无效或超过 10 MiB 处理上限；原件保留。', source_hash)
    encoder, probe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not encoder or not probe:
        return ProcessingCandidate(asset_id, version_id, 'summary', 'unavailable',
            '内嵌字幕提取需要 FFmpeg 与 ffprobe；没有生成文字候选，不包含语音转写，原件保留。', source_hash)
    deadline = time.monotonic() + _VIDEO_TEXT_TIMEOUT
    try:
        with tempfile.TemporaryDirectory(prefix='loomrise-subtitles-') as directory:
            source = Path(directory) / ('source' + SOURCE_TYPES[media_type])
            source.write_bytes(content)
            metadata = json.loads(_run_bounded_stdout(
                [probe, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries',
                 'stream=index,codec_type,codec_name,width,height,channels,sample_rate:stream_disposition=default:'
                 'stream_tags=language:format=duration',
                 '-of', 'json', '-f', DEMUXERS[media_type], str(source)],
                timeout=_video_remaining(deadline, limit=10), output_limit=_VIDEO_TEXT_OUTPUT_LIMIT,
            ))
            if not isinstance(metadata, dict) or not isinstance(metadata.get('format'), dict):
                raise ValueError('video_metadata_invalid')
            raw_duration = metadata['format'].get('duration')
            if type(raw_duration) not in {str, int, float}:
                raise ValueError('video_duration_invalid')
            duration = float(raw_duration)
            if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
                raise ValueError('video_duration_invalid')
            streams = metadata.get('streams')
            if not isinstance(streams, list) or not 1 <= len(streams) <= 32:
                raise ValueError('video_streams_invalid')
            indices, subtitles, audio_tracks = set(), [], []
            for stream in streams:
                if not isinstance(stream, dict) or type(stream.get('index')) is not int:
                    raise ValueError('video_stream_invalid')
                index = stream['index']
                if not 0 <= index < 32 or index in indices or not isinstance(stream.get('codec_type'), str):
                    raise ValueError('video_stream_invalid')
                indices.add(index)
                codec_type = stream['codec_type']
                if codec_type == 'audio':
                    tags, disposition = stream.get('tags', {}), stream.get('disposition', {})
                    if not isinstance(tags, dict) or not isinstance(disposition, dict):
                        raise ValueError('video_audio_metadata_invalid')
                    language = tags.get('language', 'und')
                    default = disposition.get('default', 0)
                    codec = stream.get('codec_name', 'unknown')
                    channels = stream.get('channels')
                    sample_rate = stream.get('sample_rate')
                    if (not isinstance(language, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', language)
                            or type(default) is not int or default not in {0, 1}
                            or not isinstance(codec, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', codec)):
                        raise ValueError('video_audio_metadata_invalid')
                    if channels is not None and (type(channels) is not int
                            or not 1 <= channels <= _VIDEO_AUDIO_CHANNEL_LIMIT):
                        raise ValueError('video_audio_metadata_invalid')
                    if sample_rate is not None:
                        if type(sample_rate) is int:
                            parsed_rate = sample_rate
                        elif isinstance(sample_rate, str) and re.fullmatch(r'[0-9]{1,9}', sample_rate):
                            parsed_rate = int(sample_rate)
                        else:
                            raise ValueError('video_audio_metadata_invalid')
                        if not _VIDEO_AUDIO_SAMPLE_RATE_MIN <= parsed_rate <= _VIDEO_AUDIO_SAMPLE_RATE_MAX:
                            raise ValueError('video_audio_metadata_invalid')
                    else:
                        parsed_rate = None
                    audio_tracks.append((not default, index, language, codec, channels, parsed_rate))
                    continue
                if codec_type != 'subtitle':
                    continue
                tags, disposition = stream.get('tags', {}), stream.get('disposition', {})
                if not isinstance(tags, dict) or not isinstance(disposition, dict):
                    raise ValueError('video_subtitle_metadata_invalid')
                language = tags.get('language', 'und')
                default = disposition.get('default', 0)
                if (not isinstance(language, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', language)
                        or type(default) is not int or default not in {0, 1}):
                    raise ValueError('video_subtitle_metadata_invalid')
                if stream.get('codec_name') in _VIDEO_TEXT_CODECS:
                    subtitles.append((not default, index, language))
            if not any(stream['codec_type'] == 'video' for stream in streams):
                raise ValueError('missing_video_stream')
            if not subtitles:
                video_stream = next(stream for stream in streams if stream['codec_type'] == 'video')
                _check_video_ocr_source(video_stream)
                audio_summary = _audio_track_summary(min(audio_tracks)) if audio_tracks else None
                return _extract_video_frame_ocr(asset_id=asset_id, version_id=version_id,
                    source=source, source_hash=source_hash, duration=duration, encoder=encoder,
                    demuxer=DEMUXERS[media_type], deadline=deadline, audio_summary=audio_summary)
            # ponytail: one default text track (else lowest index); multi-track review needs an explicit selector.
            _, index, language = min(subtitles)
            output = _run_bounded_stdout(
                [encoder, '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror',
                 '-protocol_whitelist', 'file,pipe', '-threads', '1', '-f', DEMUXERS[media_type],
                 '-i', str(source), '-map', f'0:{index}', '-map_metadata', '-1',
                 '-c:s', 'srt', '-f', 'srt', 'pipe:1'],
                timeout=_video_remaining(deadline), output_limit=_VIDEO_TEXT_OUTPUT_LIMIT,
            )
            text = _subtitle_text(output, duration)
        audio_note = _audio_track_summary(min(audio_tracks)) if audio_tracks else ''
        prefix = f'{audio_note}；' if audio_note else ''
        summary = f'{prefix}视频内嵌字幕节选候选（仅流 {index}，{language}，需人工核对）：{text}'[:500]
        return ProcessingCandidate(asset_id, version_id, 'summary', 'ready', summary, source_hash)
    except subprocess.TimeoutExpired:
        message = '视频字幕或关键帧 OCR 处理超时；没有生成文字候选，原件保留。'
    except subprocess.CalledProcessError:
        message = '视频字幕或关键帧 OCR 处理失败；没有生成文字候选，原件保留。'
    except (OSError, ValueError, TypeError) as exc:
        if str(exc) == 'processing_output_limit':
            message = '视频字幕或关键帧 OCR 结果超过长度上限；没有生成文字候选，原件保留。'
        elif str(exc) == 'video_frame_source_pixel_limit':
            message = f'视频画面缺少有效尺寸或超过 {MAX_PIXELS} 像素处理上限；没有生成 OCR 候选，原件保留。'
        else:
            message = '视频、字幕或关键帧 OCR 输入/输出无效；没有生成文字候选，原件保留。'
    return ProcessingCandidate(asset_id, version_id, 'summary', 'failed', message, source_hash)


def make_candidate(*, asset_id: str, version_id: str, filename: str, media_type: str,
                   content: bytes) -> ProcessingCandidate:
    digest = hashlib.sha256(content).hexdigest()
    if media_type in {'text/plain', 'text/markdown'}:
        try:
            text = content.decode('utf-8').strip()
        except UnicodeDecodeError:
            return ProcessingCandidate(asset_id, version_id, 'summary', 'failed', '文件不是有效 UTF-8 文本', digest)
        summary = ' '.join(text.split())[:500]
        return ProcessingCandidate(asset_id, version_id, 'summary', 'ready', summary, digest)
    if media_type in _OCR_MEDIA_TYPES:
        return _ocr_image(asset_id=asset_id, version_id=version_id, media_type=media_type,
                          content=content, source_hash=digest)
    if media_type == 'application/pdf':
        return _extract_pdf_text(asset_id=asset_id, version_id=version_id,
                                 content=content, source_hash=digest)
    if media_type.startswith('video/'):
        return _extract_video_subtitles(asset_id=asset_id, version_id=version_id, media_type=media_type,
                                        content=content, source_hash=digest)
    return ProcessingCandidate(asset_id, version_id, 'summary', 'unsupported', '该格式尚未接入内容理解，原件可继续人工发送。', digest)
