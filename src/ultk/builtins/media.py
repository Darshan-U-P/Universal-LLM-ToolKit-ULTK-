"""Bounded image processing and host-configured FFmpeg media operations."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


_IMAGE_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "BMP": "bmp"}
_AUDIO_CODECS = {"wav": "pcm_s16le", "mp3": "libmp3lame", "m4a": "aac", "opus": "libopus"}
_VIDEO_CODECS = {"mp4": "libx264", "mkv": "libx265", "webm": "libvpx-vp9"}
_BITRATES = {"64k", "96k", "128k", "160k", "192k", "256k", "320k"}


def _path(root: Path, relative_path: str, *, max_bytes: int, must_exist: bool) -> Path:
    if not relative_path or len(relative_path) > 500:
        raise ToolExecutionError("A relative media path of at most 500 characters is required.")
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute media paths are not allowed.")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ToolExecutionError("Media path escapes the configured root.")
    if must_exist:
        if not resolved.is_file():
            raise ToolExecutionError("Input media file does not exist.")
        if resolved.stat().st_size > max_bytes:
            raise ToolExecutionError("Input media file exceeds the configured size limit.")
    elif resolved.exists():
        raise ToolExecutionError("Output media file already exists; choose a new path.")
    else:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _image_open(root: Path, relative_path: str, max_bytes: int, max_pixels: int):
    try:
        from PIL import Image
    except ImportError as exc:
        raise ToolExecutionError("Install the 'media' extra to use image tools.") from exc
    path = _path(root, relative_path, max_bytes=max_bytes, must_exist=True)
    try:
        image = Image.open(path)
        if image.width * image.height > max_pixels:
            image.close()
            raise ToolExecutionError("Image dimensions exceed the configured pixel limit.")
        image.load()
    except ToolExecutionError:
        raise
    except Exception as exc:
        raise ToolExecutionError(
            f"Image could not be decoded ({type(exc).__name__})."
        ) from exc
    return image


def _image_info(root: Path, relative_path: str, max_bytes: int,
                max_pixels: int) -> dict[str, Any]:
    image = _image_open(root, relative_path, max_bytes, max_pixels)
    try:
        return {
            "path": relative_path,
            "format": image.format,
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
            "has_transparency": "A" in image.getbands(),
        }
    finally:
        image.close()


def _save_image(image, target: Path, image_format: str, quality: int) -> int:
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=".ultk-image-",
            suffix=target.suffix, delete=False,
        ) as handle:
            temporary_path = handle.name
        save_options: dict[str, Any] = {}
        if image_format in {"JPEG", "WEBP"}:
            save_options["quality"] = quality
        if image_format == "JPEG" and "A" in image.getbands():
            from PIL import Image
            flattened = Image.new("RGB", image.size, (255, 255, 255))
            alpha_image = image.convert("RGBA")
            flattened.paste(alpha_image, mask=alpha_image.getchannel("A"))
            flattened.save(temporary_path, format=image_format, optimize=True, **save_options)
            alpha_image.close()
            flattened.close()
        else:
            image.save(temporary_path, format=image_format, **save_options)
        size = Path(temporary_path).stat().st_size
        os.replace(temporary_path, target)
        return size
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _image_resize(root: Path, source: str, destination: str, width: int, height: int,
                  max_bytes: int, max_pixels: int, max_output_bytes: int) -> dict[str, Any]:
    if not 1 <= width <= 8192 or not 1 <= height <= 8192:
        raise ToolExecutionError("Image dimensions must be between 1 and 8192 pixels.")
    target = _path(root, destination, max_bytes=max_output_bytes, must_exist=False)
    if target.suffix.casefold() != ".png":
        raise ToolExecutionError("Resized image output must use a .png extension.")
    image = _image_open(root, source, max_bytes, max_pixels)
    try:
        image.thumbnail((width, height))
        output_width, output_height = image.size
        size = _save_image(image, target, "PNG", 90)
    finally:
        image.close()
    if size > max_output_bytes:
        target.unlink(missing_ok=True)
        raise ToolExecutionError("Resized image exceeds the configured output limit.")
    return {"path": destination, "width": output_width, "height": output_height,
            "bytes_written": size, "format": "PNG"}


def _image_convert(root: Path, source: str, destination: str, output_format: str,
                   quality: int, max_bytes: int, max_pixels: int,
                   max_output_bytes: int) -> dict[str, Any]:
    image_format = output_format.upper()
    if image_format not in _IMAGE_FORMATS or not 1 <= quality <= 100:
        raise ToolExecutionError("Unsupported image format or quality value.")
    target = _path(root, destination, max_bytes=max_output_bytes, must_exist=False)
    expected_extension = _IMAGE_FORMATS[image_format]
    accepted_extensions = {expected_extension}
    if image_format == "JPEG":
        accepted_extensions.add("jpeg")
    if target.suffix.casefold().lstrip(".") not in accepted_extensions:
        raise ToolExecutionError("Output file extension does not match the selected image format.")
    image = _image_open(root, source, max_bytes, max_pixels)
    try:
        size = _save_image(image, target, image_format, quality)
        width, height = image.size
    finally:
        image.close()
    if size > max_output_bytes:
        target.unlink(missing_ok=True)
        raise ToolExecutionError("Converted image exceeds the configured output limit.")
    return {"path": destination, "format": image_format, "width": width,
            "height": height, "bytes_written": size}


def _run_ffmpeg(binary: str, arguments: list[str], *, root: Path,
                output_path: Path | None, final_path: Path | None = None,
                timeout_seconds: int, max_output_bytes: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [binary, *arguments],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        raise ToolExecutionError("Media operation exceeded its time limit.") from exc
    except OSError as exc:
        raise ToolExecutionError(
            f"Media executable could not start ({type(exc).__name__})."
        ) from exc
    if completed.returncode != 0:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        raise ToolExecutionError(
            f"Media operation failed with exit code {completed.returncode}."
        )
    size = None
    if output_path is not None:
        if not output_path.is_file():
            raise ToolExecutionError("Media operation completed without creating its output.")
        size = output_path.stat().st_size
        if size > max_output_bytes:
            output_path.unlink(missing_ok=True)
            raise ToolExecutionError("Generated media exceeds the configured output limit.")
        if final_path is not None:
            os.replace(output_path, final_path)
    return {"return_code": completed.returncode, "bytes_written": size}


def _probe(root: Path, relative_path: str, ffprobe: str, max_input_bytes: int,
           timeout_seconds: int) -> dict[str, Any]:
    source = _path(root, relative_path, max_bytes=max_input_bytes, must_exist=True)
    try:
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json",
             str(source)],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise ToolExecutionError("ffprobe could not inspect the media file.")
        if len(completed.stdout.encode("utf-8")) > 90_000:
            raise ToolExecutionError("ffprobe metadata exceeds the output limit.")
        return json.loads(completed.stdout)
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError("ffprobe exceeded its time limit.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolExecutionError(f"ffprobe failed ({type(exc).__name__}).") from exc


def _transcode_audio(root: Path, source: str, destination: str, output_format: str,
                     bitrate: str, ffmpeg: str, max_input_bytes: int,
                     max_output_bytes: int, timeout_seconds: int) -> dict[str, Any]:
    output_format = output_format.casefold()
    if output_format not in _AUDIO_CODECS or bitrate not in _BITRATES:
        raise ToolExecutionError("Unsupported audio format or bitrate.")
    input_path = _path(root, source, max_bytes=max_input_bytes, must_exist=True)
    output_path = _path(root, destination, max_bytes=max_output_bytes, must_exist=False)
    if output_path.suffix.casefold().lstrip(".") != output_format:
        raise ToolExecutionError("Output extension must match the selected audio format.")
    temporary_path = output_path.with_name(
        f".ultk-{uuid.uuid4().hex}{output_path.suffix}"
    )
    result = _run_ffmpeg(
        ffmpeg,
        ["-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(input_path),
         "-vn", "-c:a", _AUDIO_CODECS[output_format], "-b:a", bitrate, str(temporary_path)],
        root=root, output_path=temporary_path, final_path=output_path,
        timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
    )
    return {"path": destination, "format": output_format, **result}


def _transcode_video(root: Path, source: str, destination: str, output_format: str,
                     ffmpeg: str, max_input_bytes: int, max_output_bytes: int,
                     timeout_seconds: int) -> dict[str, Any]:
    output_format = output_format.casefold()
    if output_format not in _VIDEO_CODECS:
        raise ToolExecutionError("Unsupported video container format.")
    input_path = _path(root, source, max_bytes=max_input_bytes, must_exist=True)
    output_path = _path(root, destination, max_bytes=max_output_bytes, must_exist=False)
    if output_path.suffix.casefold().lstrip(".") != output_format:
        raise ToolExecutionError("Output extension must match the selected video format.")
    temporary_path = output_path.with_name(
        f".ultk-{uuid.uuid4().hex}{output_path.suffix}"
    )
    result = _run_ffmpeg(
        ffmpeg,
        ["-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(input_path),
         "-c:v", _VIDEO_CODECS[output_format], "-c:a", "aac", str(temporary_path)],
        root=root, output_path=temporary_path, final_path=output_path,
        timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
    )
    return {"path": destination, "format": output_format, **result}


def _thumbnail(root: Path, source: str, destination: str, at_seconds: float,
               width: int, height: int, ffmpeg: str, max_input_bytes: int,
               max_output_bytes: int, timeout_seconds: int) -> dict[str, Any]:
    if not 0 <= at_seconds <= 86_400 or not 64 <= width <= 2048 or not 64 <= height <= 2048:
        raise ToolExecutionError("Thumbnail timestamp or dimensions are outside allowed bounds.")
    input_path = _path(root, source, max_bytes=max_input_bytes, must_exist=True)
    output_path = _path(root, destination, max_bytes=max_output_bytes, must_exist=False)
    if output_path.suffix.casefold() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ToolExecutionError("Thumbnail output must be JPG, PNG or WEBP.")
    temporary_path = output_path.with_name(
        f".ultk-{uuid.uuid4().hex}{output_path.suffix}"
    )
    result = _run_ffmpeg(
        ffmpeg,
        ["-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-ss", str(at_seconds),
         "-i", str(input_path), "-frames:v", "1", "-vf",
         f"scale={width}:{height}:force_original_aspect_ratio=decrease",
         str(temporary_path)],
        root=root, output_path=temporary_path, final_path=output_path,
        timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
    )
    return {"path": destination, **result}


def create_media_tools(
    *,
    root_dir: str | Path,
    ffmpeg_binary: str | None = None,
    ffprobe_binary: str | None = None,
    max_input_bytes: int = 1_000_000_000,
    max_output_bytes: int = 1_000_000_000,
    max_pixels: int = 40_000_000,
) -> tuple[FunctionTool, ...]:
    root = Path(root_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not 1 <= max_input_bytes <= 20_000_000_000:
        raise ValueError("max_input_bytes must be between 1 byte and 20 GB.")
    if not 1 <= max_output_bytes <= 20_000_000_000:
        raise ValueError("max_output_bytes must be between 1 byte and 20 GB.")
    if not 1 <= max_pixels <= 200_000_000:
        raise ValueError("max_pixels must be between 1 and 200 million.")
    tools: list[FunctionTool] = [
        FunctionTool(
            "media.image_info", "Inspect dimensions and format of an image file.",
            object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 500}},
                          ["path"]),
            "media:image:read",
            lambda path: _image_info(root, path, max_input_bytes, max_pixels),
        ),
        FunctionTool(
            "media.image_resize", "Resize an image while preserving its aspect ratio; output is PNG.",
            object_schema({
                "source": {"type": "string", "minLength": 1, "maxLength": 500},
                "destination": {"type": "string", "minLength": 1, "maxLength": 500},
                "width": {"type": "integer", "minimum": 1, "maximum": 8192},
                "height": {"type": "integer", "minimum": 1, "maximum": 8192},
            }, ["source", "destination", "width", "height"]),
            "media:image:write",
            lambda source, destination, width, height: _image_resize(
                root, source, destination, width, height,
                max_input_bytes, max_pixels, max_output_bytes,
            ),
        ),
        FunctionTool(
            "media.image_convert", "Convert an image to PNG, JPEG, WEBP or BMP.",
            object_schema({
                "source": {"type": "string", "minLength": 1, "maxLength": 500},
                "destination": {"type": "string", "minLength": 1, "maxLength": 500},
                "format": {"type": "string", "enum": ["PNG", "JPEG", "WEBP", "BMP"]},
                "quality": {"type": "integer", "minimum": 1, "maximum": 100},
            }, ["source", "destination", "format"]),
            "media:image:write",
            lambda source, destination, format, quality=90: _image_convert(
                root, source, destination, format, quality,
                max_input_bytes, max_pixels, max_output_bytes,
            ),
        ),
    ]
    if ffmpeg_binary and ffprobe_binary:
        tools.extend([
            FunctionTool(
                "media.probe", "Inspect audio/video streams and container metadata using ffprobe.",
                object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 500}},
                              ["path"]),
                "media:read",
                lambda path: _probe(root, path, ffprobe_binary, max_input_bytes, 30),
                timeout=35,
                output_limit=100_000,
            ),
            FunctionTool(
                "media.transcode_audio", "Transcode an audio track to WAV, MP3, M4A or OPUS.",
                object_schema({
                    "source": {"type": "string", "minLength": 1, "maxLength": 500},
                    "destination": {"type": "string", "minLength": 1, "maxLength": 500},
                    "format": {"type": "string", "enum": sorted(_AUDIO_CODECS)},
                    "bitrate": {"type": "string", "enum": sorted(_BITRATES)},
                }, ["source", "destination", "format"]),
                "media:transcode",
                lambda source, destination, format, bitrate="192k": _transcode_audio(
                    root, source, destination, format, bitrate, ffmpeg_binary,
                    max_input_bytes, max_output_bytes, 3600,
                ),
                timeout=3605,
            ),
            FunctionTool(
                "media.transcode_video", "Transcode video to MP4, MKV or WEBM with fixed codecs.",
                object_schema({
                    "source": {"type": "string", "minLength": 1, "maxLength": 500},
                    "destination": {"type": "string", "minLength": 1, "maxLength": 500},
                    "format": {"type": "string", "enum": sorted(_VIDEO_CODECS)},
                }, ["source", "destination", "format"]),
                "media:transcode",
                lambda source, destination, format: _transcode_video(
                    root, source, destination, format, ffmpeg_binary,
                    max_input_bytes, max_output_bytes, 3600,
                ),
                timeout=3605,
            ),
            FunctionTool(
                "media.create_thumbnail", "Extract one bounded video frame as an image.",
                object_schema({
                    "source": {"type": "string", "minLength": 1, "maxLength": 500},
                    "destination": {"type": "string", "minLength": 1, "maxLength": 500},
                    "at_seconds": {"type": "number", "minimum": 0, "maximum": 86400},
                    "width": {"type": "integer", "minimum": 64, "maximum": 2048},
                    "height": {"type": "integer", "minimum": 64, "maximum": 2048},
                }, ["source", "destination"]),
                "media:write",
                lambda source, destination, at_seconds=0, width=640, height=360: _thumbnail(
                    root, source, destination, at_seconds, width, height, ffmpeg_binary,
                    max_input_bytes, max_output_bytes, 120,
                ),
                timeout=125,
            ),
        ])
    return tuple(tools)
