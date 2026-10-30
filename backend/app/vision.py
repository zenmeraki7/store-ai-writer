"""Read a product photo with a local vision model (Ollama's native API). Used by the Quick write screen."""
from __future__ import annotations

import base64
import json
import re
from typing import cast
import urllib.error
import urllib.request

from .config import settings

CAPTION_PROMPT = (
    "Describe only what is clearly visible in this product photo, in one plain sentence: "
    "colours, pattern and style. Do not guess the brand, material, size, fit, price or anything "
    "you cannot see. Reply with the sentence only."
)
MAX_IMAGE_BYTES = 8_000_000


class VisionError(Exception):
    pass


def decode_image(data: str) -> bytes:
    """Accepts a data URL (data:image/jpeg;base64,...) or plain base64."""
    raw = re.sub(r"^data:[^,]*,", "", (data or "").strip())
    try:
        img = base64.b64decode(raw, validate=False)
    except ValueError as e:
        raise VisionError("That photo could not be read.") from e
    if not img:
        raise VisionError("That photo is empty.")
    if len(img) > MAX_IMAGE_BYTES:
        raise VisionError("That photo is too large to read.")
    return img


def caption_bytes(img: bytes) -> str:
    base = re.sub(r"/v1/?$", "", settings.ollama_base_url.rstrip("/"))
    model = settings.ollama_vision_model or settings.ollama_model
    body = json.dumps({
        "model": model, "stream": False,
        "messages": [{"role": "user", "content": CAPTION_PROMPT, "images": [base64.b64encode(img).decode()]}],
    }).encode()
    req = urllib.request.Request(f"{base}/api/chat", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise VisionError(
            f"The writing model could not read the photo ({getattr(e, 'reason', e)}). "
            "It needs a model that understands images, such as gemma3:4b."
        ) from e
    response = json.loads(raw)
    response_dict = cast(dict[str, object], response) if isinstance(response, dict) else {}
    message = response_dict.get("message")
    content = cast(dict[str, object], message).get("content") if isinstance(message, dict) else None
    text = content.strip().replace("\n", " ") if isinstance(content, str) else ""
    return text[:300]
