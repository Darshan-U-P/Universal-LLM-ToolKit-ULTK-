from __future__ import annotations

from pathlib import Path

import pytest

from ultk.builtins.media import (
    _image_info,
    _image_resize,
    _path,
    create_media_tools,
)
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


def test_media_pack_registers_image_tools_and_optional_ffmpeg_tools(tmp_path: Path) -> None:
    image_only = create_media_tools(root_dir=tmp_path / "images")
    assert {tool.spec.name for tool in image_only} == {
        "media.image_info",
        "media.image_resize",
        "media.image_convert",
    }

    full = create_media_tools(
        root_dir=tmp_path / "full",
        ffmpeg_binary="/trusted/bin/ffmpeg",
        ffprobe_binary="/trusted/bin/ffprobe",
    )
    names = {tool.spec.name for tool in full}
    assert {
        "media.probe",
        "media.transcode_audio",
        "media.transcode_video",
        "media.create_thumbnail",
    } <= names


def test_media_paths_are_confined_and_output_is_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / "source.bin").write_bytes(b"source")
    with pytest.raises(Exception, match="escapes"):
        _path(tmp_path, "../outside.bin", max_bytes=100, must_exist=True)
    with pytest.raises(Exception, match="already exists"):
        _path(tmp_path, "source.bin", max_bytes=100, must_exist=False)


def test_image_tools_respect_pixel_limits_and_resize_to_png(tmp_path: Path) -> None:
    Image = pytest.importorskip("PIL.Image")
    source = tmp_path / "source.png"
    Image.new("RGBA", (100, 50), (255, 0, 0, 128)).save(source)

    info = _image_info(tmp_path, "source.png", 10000, 10000)
    assert info["width"] == 100
    assert info["height"] == 50

    result = _image_resize(tmp_path, "source.png", "resized.png", 50, 50,
                           10000, 10000, 10000)
    assert result["width"] == 50
    assert result["height"] == 25
    with pytest.raises(Exception, match="pixel limit"):
        _image_info(tmp_path, "source.png", 10000, 100)


def test_engine_installs_media_pack(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"media.image_info"}))
    engine.install_media_tools(root_dir=tmp_path)
    assert "media.image_info" in {tool.spec.name for tool in engine.registry.list()}
