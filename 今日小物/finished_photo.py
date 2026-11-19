"""Validate a local photo and produce a bounded JPEG for the daily canvas."""
from pathlib import Path
import re
import subprocess

from local_store import Problem

MAX_PHOTO_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 64_000_000


def prepare_photo(directory, raw, media_type):
    expected = {"image/jpeg": ("jpeg", b"\xff\xd8\xff"), "image/png": ("png", b"\x89PNG\r\n\x1a\n")}
    if media_type not in expected or not 0 < len(raw) <= MAX_PHOTO_BYTES:
        raise Problem("请选择 12 MB 以内的 JPG 或 PNG 实物照片。")
    fmt, signature = expected[media_type]
    if not raw.startswith(signature):
        raise Problem("图片内容和所选格式不一致。")
    source = Path(directory) / ("source." + fmt)
    source.write_bytes(raw)
    target = Path(directory) / "finished.jpg"
    try:
        props = subprocess.run(
            ["/usr/bin/sips", "-g", "format", "-g", "pixelWidth", "-g", "pixelHeight", source],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        values = dict(re.findall(r"^\s*(format|pixelWidth|pixelHeight): (\S+)\s*$", props, re.M))
        width, height = int(values["pixelWidth"]), int(values["pixelHeight"])
        if values["format"] != fmt or min(width, height) <= 0 or width * height > MAX_PIXELS:
            raise Problem("照片尺寸或格式不支持，请选择普通 JPG 或 PNG 照片。")
        subprocess.run(
            ["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "88", "-Z", "2400",
             source, "--out", target], capture_output=True, timeout=30, check=True,
        )
        if not target.exists() or target.stat().st_size < 4:
            raise Problem("照片无法解码，请换一张图片。")
    except (KeyError, ValueError, OSError, subprocess.SubprocessError):
        raise Problem("照片无法读取，请使用普通 JPG 或 PNG 照片重试。") from None
    return target
