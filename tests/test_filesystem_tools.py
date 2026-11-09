from pathlib import Path

import pytest

from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


@pytest.fixture
def engine(tmp_path: Path) -> ToolEngine:
    toolkit = ToolEngine(
        policy=AllowListPolicy({
            "filesystem.read_file",
            "filesystem.write_file",
            "filesystem.list_directory",
            "filesystem.create_directory",
            "filesystem.stat",
        })
    )
    toolkit.install_filesystem_tools(tmp_path)
    return toolkit


@pytest.mark.asyncio
async def test_write_then_read_file(engine: ToolEngine, tmp_path: Path) -> None:
    write_result = await engine.execute(
        "filesystem.write_file",
        {"path": "notes/hello.txt", "content": "Hello ULTK"},
        granted_capabilities=frozenset({"filesystem:write"}),
    )
    assert write_result.is_error
    assert "Parent directory does not exist" in write_result.content

    directory_result = await engine.execute(
        "filesystem.create_directory",
        {"path": "notes"},
        granted_capabilities=frozenset({"filesystem:write"}),
    )
    assert not directory_result.is_error

    write_result = await engine.execute(
        "filesystem.write_file",
        {"path": "notes/hello.txt", "content": "Hello ULTK"},
        granted_capabilities=frozenset({"filesystem:write"}),
    )
    assert not write_result.is_error
    assert (tmp_path / "notes" / "hello.txt").read_text(encoding="utf-8") == "Hello ULTK"

    read_result = await engine.execute(
        "filesystem.read_file",
        {"path": "notes/hello.txt"},
        granted_capabilities=frozenset({"filesystem:read"}),
    )
    assert not read_result.is_error
    assert read_result.content == "Hello ULTK"


@pytest.mark.asyncio
async def test_directory_listing_and_stat(engine: ToolEngine, tmp_path: Path) -> None:
    (tmp_path / "sample.txt").write_text("data", encoding="utf-8")

    listing = await engine.execute(
        "filesystem.list_directory",
        {},
        granted_capabilities=frozenset({"filesystem:read"}),
    )
    assert not listing.is_error
    assert '"sample.txt"' in listing.content

    metadata = await engine.execute(
        "filesystem.stat",
        {"path": "sample.txt"},
        granted_capabilities=frozenset({"filesystem:read"}),
    )
    assert not metadata.is_error
    assert '"size_bytes": 4' in metadata.content


@pytest.mark.asyncio
async def test_path_traversal_is_rejected(engine: ToolEngine, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = await engine.execute(
        "filesystem.read_file",
        {"path": "../outside.txt"},
        granted_capabilities=frozenset({"filesystem:read"}),
    )
    assert result.is_error
    assert "escapes" in result.content


@pytest.mark.asyncio
async def test_capability_is_required(engine: ToolEngine) -> None:
    result = await engine.execute(
        "filesystem.write_file",
        {"path": "blocked.txt", "content": "no"},
    )
    assert result.is_error
    assert "denied" in result.content.lower()
