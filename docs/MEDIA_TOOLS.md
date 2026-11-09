# Media Processing Tools

The media pack provides bounded image inspection/conversion/resizing and optional FFmpeg-based audio/video operations.

## Install

```bash
pip install -e ".[media]"
```

Pillow powers image tools. FFmpeg and ffprobe are separate host-installed executables; they are not downloaded or installed by ULTK.

```python
engine.install_media_tools(
    root_dir="./workspace/media",
    ffmpeg_binary="/trusted/bin/ffmpeg",
    ffprobe_binary="/trusted/bin/ffprobe",
    max_input_bytes=1_000_000_000,
    max_output_bytes=1_000_000_000,
    max_pixels=40_000_000,
)
```

Image tools:
- `media.image_info`
- `media.image_resize` (PNG output)
- `media.image_convert` (PNG/JPEG/WEBP/BMP)

When both FFmpeg and ffprobe are configured:
- `media.probe`
- `media.transcode_audio` (WAV/MP3/M4A/OPUS)
- `media.transcode_video` (MP4/MKV/WEBM with fixed codec mappings)
- `media.create_thumbnail`

Commands use argument arrays with `shell=False`; the model cannot supply arbitrary FFmpeg arguments, filters or executable paths. Input/output paths are confined to the host-configured media root. Output files are not overwritten. Processing time, dimensions, input/output sizes and supported codecs are bounded.

## Not implemented

- Speech recognition, diarization, translation, voice cloning and text-to-speech.
- AI image/video generation or semantic editing.
- OCR, subtitles, timeline editing, multitrack mixing and streaming.
- Hardware encoder discovery/selection and GPU scheduling.
- Full sandboxing of native parsers/codecs. Treat untrusted media as hostile and run processing in a restricted worker/container for production use.

Validate installed codec availability, Pillow decompression-bomb behavior, FFmpeg cancellation/partial-output cleanup, cross-platform paths and large-file resource limits in the deferred test campaign.
