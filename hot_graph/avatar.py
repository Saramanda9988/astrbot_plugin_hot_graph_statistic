from __future__ import annotations

import logging
import time
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

_USER_AVATAR_TEMPLATE = "https://q1.qlogo.cn/g?b=qq&nk={user_id}&s={size}"
_AVAILABLE_SIZES = (40, 100, 140, 160, 640)
_DEFAULT_CACHE_TTL = 86400.0  # 24 小时


def _nearest_size(requested: int) -> int:
    return min(_AVAILABLE_SIZES, key=lambda x: abs(x - requested))


def _cache_path(cache_dir: Path, user_id: str, size: int) -> Path:
    return cache_dir / f"{user_id}_{size}.img"


def _read_cache(cache_dir: Path, user_id: str, size: int, ttl: float) -> bytes | None:
    path = _cache_path(cache_dir, user_id, size)
    if not path.is_file():
        return None
    if time.time() - path.stat().st_mtime > ttl:
        path.unlink(missing_ok=True)
        return None
    try:
        data = path.read_bytes()
        if _is_valid_image(data):
            return data
    except Exception:
        pass
    return None


def _write_cache(cache_dir: Path, user_id: str, size: int, data: bytes) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_path(cache_dir, user_id, size).write_bytes(data)
    except Exception as e:
        logger.debug("avatar cache write failed for %s: %s", user_id, e)


async def fetch_qq_avatar(
    user_id: str,
    size: int = 100,
    timeout: float = 5.0,
    cache_dir: Path | None = None,
    cache_ttl: float = _DEFAULT_CACHE_TTL,
) -> bytes | None:
    """
    通过 QQ 头像服务下载用户头像。

    Args:
        user_id: QQ 号
        size: 期望的头像尺寸像素
        timeout: 下载超时（秒）
        cache_dir: 磁盘缓存目录，为 None 时不缓存
        cache_ttl: 缓存过期时间（秒），默认 24 小时

    Returns:
        头像图片字节数据，失败返回 None
    """
    if not user_id or not user_id.isdigit():
        return None

    actual_size = _nearest_size(size)

    if cache_dir is not None:
        cached = _read_cache(cache_dir, user_id, actual_size, cache_ttl)
        if cached is not None:
            return cached

    url = _USER_AVATAR_TEMPLATE.format(user_id=user_id, size=actual_size)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    logger.debug("QQ avatar download failed for %s: HTTP %s", user_id, resp.status)
                    return None
                data = await resp.read()
                if _is_valid_image(data):
                    if cache_dir is not None:
                        _write_cache(cache_dir, user_id, actual_size, data)
                    return data
                logger.debug("QQ avatar data for %s is not a valid image", user_id)
    except Exception as e:
        logger.debug("QQ avatar download error for %s: %s", user_id, e)
    return None


def _is_valid_image(data: bytes) -> bool:
    if not data or len(data) < 8:
        return False
    return (
        data[:2] == b"\xff\xd8"  # JPEG
        or data[:4] == b"\x89PNG"  # PNG
        or data[:4] == b"GIF8"  # GIF
        or (data[:4] == b"RIFF" and b"WEBP" in data[8:16])  # WebP
    )
