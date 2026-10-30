from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

Field_ = Literal["title", "description", "seo_title", "seo_description", "tags"]
Tone = Literal["professional", "friendly", "luxury", "playful", "formal", "casual", "persuasive", "simple"]


class ProductInput(BaseModel):
    title: str
    product_type: str = ""
    vendor: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)  # e.g. {"color": "red", "pieces": 50}
    tags: list[str] = Field(default_factory=list)
    image_caption: Optional[str] = None  # from a vision model later
    existing_description: Optional[str] = None


class Options(BaseModel):
    category: str = "auto"  # auto, or: general, fashion, toys, books, electronics, kitchen, food, beauty, home, jewelry, sports
    tone: Tone = "professional"
    paragraphs: int = Field(2, ge=1, le=3)
    detail: Literal["concise", "detailed"] = "detailed"
    language: str = "English"
    brand_voice: Optional[str] = None  # a short sample or style note from the merchant


class GenerateRequest(BaseModel):
    product: ProductInput
    options: Options = Field(default_factory=lambda: Options(paragraphs=2))
    fields: list[Field_] = ["description"]


class GenerateResponse(BaseModel):
    result: dict[str, Any]
    provider: str
    warnings: list[str] = []
