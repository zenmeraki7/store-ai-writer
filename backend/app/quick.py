"""Quick write: describe a product in plain words (and optionally add a photo), get product text back.

Same safety net as the store flow: everything goes through generate_content, so invented details are removed.
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .categories import detect_category
from .linkreader import LinkError, read_link
from .llm import LLMError
from .schemas import Field_, GenerateRequest, Options, ProductInput
from .service import generate_content
from .vision import VisionError, caption_bytes, decode_image

router = APIRouter(prefix="/quick", tags=["quick"])


class QuickRequest(BaseModel):
    description: str = Field("", max_length=2000)
    name: str = Field("", max_length=150)
    keywords: str = Field("", max_length=200)
    image: Optional[str] = Field(None, max_length=12_000_000)  # data URL or base64 of a (resized) photo
    options: Options = Field(default_factory=lambda: Options(paragraphs=1, detail="concise"))
    fields: list[Field_] = ["description"]


class QuickResponse(BaseModel):
    result: dict
    provider: str
    warnings: list[str] = []
    photo_note: str = ""   # what the model saw in the photo
    photo_error: str = ""  # set when a photo was sent but could not be read


def derive_title(name: str, description: str, caption: str) -> str:
    if name.strip():
        return name.strip()
    src = (description.strip() or caption.strip())
    first = re.split(r"(?<=[.!?])\s|\n", src, maxsplit=1)[0].strip().rstrip(".")
    if len(first) > 90:
        first = first[:90].rsplit(" ", 1)[0]
    return first or "Product"


def build_request(req: QuickRequest, caption: str) -> GenerateRequest:
    attrs = {"search keywords": req.keywords.strip()} if req.keywords.strip() else {}
    product = ProductInput(
        title=derive_title(req.name, req.description, caption),
        attributes=attrs,
        existing_description=req.description.strip() or None,
        image_caption=caption or None,
    )
    options = req.options
    if (options.category or "auto").lower() == "auto":
        options = options.model_copy(update={"category": detect_category(f"{req.name} {req.description[:400]} {caption}")})
    return GenerateRequest(product=product, options=options, fields=req.fields or ["description"])


def _run(req: QuickRequest) -> QuickResponse:
    if not (req.description.strip() or req.name.strip() or req.image):
        raise ValueError("Describe your product or add a photo first.")
    caption = photo_error = ""
    if req.image:
        try:
            caption = caption_bytes(decode_image(req.image))
        except VisionError as e:
            photo_error = str(e)
            if not (req.description.strip() or req.name.strip()):
                raise ValueError(photo_error) from e
    result, provider, warnings = generate_content(build_request(req, caption))
    return QuickResponse(result=result, provider=provider, warnings=warnings, photo_note=caption, photo_error=photo_error)


@router.post("/generate", response_model=QuickResponse)
def quick_generate(req: QuickRequest):  # plain def: FastAPI runs the slow model call in a worker thread
    try:
        return _run(req)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class LinkRequest(BaseModel):
    url: str = Field(..., max_length=2000)


@router.post("/link")
def quick_link(req: LinkRequest):
    """Reads a product page and returns its name, details and photo so the page can fill in the form."""
    try:
        return read_link(req.url)
    except LinkError as e:
        raise HTTPException(status_code=422, detail=str(e))
