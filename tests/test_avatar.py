from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

from PIL import Image

from hot_graph.avatar import _read_cache, _write_cache, _is_valid_image


def _make_png_bytes() -> bytes:
    img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_write_and_read_cache(tmp_path):
    cache_dir = tmp_path / "avatar_cache"
    data = _make_png_bytes()

    _write_cache(cache_dir, "12345", 100, data)

    cached = _read_cache(cache_dir, "12345", 100, ttl=3600)
    assert cached == data


def test_read_cache_returns_none_when_missing(tmp_path):
    assert _read_cache(tmp_path, "99999", 100, ttl=3600) is None


def test_read_cache_expires(tmp_path):
    cache_dir = tmp_path / "avatar_cache"
    data = _make_png_bytes()
    _write_cache(cache_dir, "12345", 100, data)

    cached = _read_cache(cache_dir, "12345", 100, ttl=0)
    assert cached is None


def test_is_valid_image_jpeg():
    assert _is_valid_image(b"\xff\xd8\xff\xe0" + b"\x00" * 100)


def test_is_valid_image_png():
    assert _is_valid_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)


def test_is_valid_image_rejects_garbage():
    assert not _is_valid_image(b"not-an-image")
    assert not _is_valid_image(b"")
    assert not _is_valid_image(b"short")
