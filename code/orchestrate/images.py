"""Load, downscale, and base64-encode images for the vision call.

Downscaling to a bounded long edge caps image tokens (the dominant input cost)
while keeping damage visible. The sha256 of the *encoded* bytes is part of the
cache key so a re-run with identical images is free.
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .config import SETTINGS


@dataclass
class EncodedImage:
    image_id: str
    b64: str
    media_type: str
    sha256: str
    width: int
    height: int


def encode_image(path: Path, image_id: str) -> EncodedImage:
    with Image.open(path) as im:
        im = im.convert("RGB")
        max_edge = SETTINGS.image_max_edge
        long_edge = max(im.size)
        if long_edge > max_edge:
            scale = max_edge / long_edge
            new_size = (round(im.width * scale), round(im.height * scale))
            im = im.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=SETTINGS.image_jpeg_quality)
        data = buf.getvalue()
        w, h = im.size

    return EncodedImage(
        image_id=image_id,
        b64=base64.standard_b64encode(data).decode("ascii"),
        media_type="image/jpeg",
        sha256=hashlib.sha256(data).hexdigest(),
        width=w,
        height=h,
    )


def to_content_blocks(images: list[EncodedImage]) -> list[dict]:
    """OpenAI/OpenRouter chat content parts: a label + the image, per image, so
    the model can refer to each by its id. Images are inlined as base64 data
    URIs (``image_url``), which OpenRouter forwards to the underlying provider."""
    blocks: list[dict] = []
    for img in images:
        blocks.append({"type": "text", "text": f"Image id: {img.image_id}"})
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{img.media_type};base64,{img.b64}"},
            }
        )
    return blocks
