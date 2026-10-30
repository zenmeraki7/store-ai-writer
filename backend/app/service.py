import re
from typing import Any, cast

from .categories import CATEGORIES, detect_category
from .config import settings
from .llm import chat
from .prompts import build_messages
from .schemas import GenerateRequest, ProductInput
from .validators import force_limits, parse_json, strip_unsupported, validate  # type: ignore[reportUnknownVariableType]


def facts_text(p: ProductInput) -> str:
    """Everything the merchant actually told us, as plain text (values only, no JSON keys)."""
    parts = [p.title, p.product_type, p.vendor, p.existing_description or "", p.image_caption or "", " ".join(p.tags)]
    for k, v in p.attributes.items():
        parts += [str(k).replace("_", " "), str(v)]
    return " ".join(x for x in parts if x)


def basic_description(p: ProductInput) -> str:
    """A boring but 100% grounded description, used when the model only produces invented text."""
    if p.existing_description and p.existing_description.strip():
        return p.existing_description.strip()
    text = p.title.strip().rstrip(".") + "."
    extras = [f"{str(k).replace('_', ' ').capitalize()}: {v}" for k, v in p.attributes.items()]
    return text + (" " + "; ".join(extras) + "." if extras else "")


def basic_tags(p: ProductInput, category: str = "general") -> list[str]:
    """Generate 100% grounded fallback tags from product title, attributes, and tags when model omits them."""
    if p.tags:
        valid_existing = [t.strip().lower() for t in p.tags if t.strip()]
        if valid_existing:
            return valid_existing[:8]
    source = (p.title + " " + p.product_type + " " + p.vendor + " " + " ".join(str(v) for v in p.attributes.values())).lower()
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", source)
    stop = {"the", "a", "an", "and", "or", "for", "with", "in", "on", "at", "by", "is", "it", "to", "of", "from"}
    seen: set[str] = set()
    tags: list[str] = []
    for w in words:
        if w not in stop and len(w) > 1 and w not in seen:
            seen.add(w)
            tags.append(w)
            if len(tags) >= 8:
                break
    return tags


def resolve_category(req: GenerateRequest) -> str:
    c = (req.options.category or "auto").strip().lower()
    if c == "auto":
        p = req.product
        return detect_category(" ".join([p.title, p.product_type, " ".join(p.tags)]))
    return c if c in CATEGORIES else "general"


def ensure_requested_fields(
    data: dict[str, Any],
    req: GenerateRequest,
    fallback_desc: str,
    fallback_tags: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Fill in any requested fields that the model omitted or that were stripped."""
    notes: list[str] = []
    for f in req.fields:
        val = data.get(f)
        if val is None or val == "" or val == []:
            if f == "description":
                data[f] = fallback_desc
                notes.append("Generated grounded description from product data (missing from model output).")
            elif f == "tags":
                data[f] = fallback_tags
                notes.append("Generated grounded tags from product data.")
            elif f == "title":
                data[f] = req.product.title
                notes.append("Used product title as fallback title.")
            elif f == "seo_title":
                data[f] = req.product.title[:60]
                notes.append("Used product title as fallback SEO title.")
            elif f == "seo_description":
                data[f] = fallback_desc[:160]
                notes.append("Used grounded description as fallback SEO description.")
    return data, notes


def generate_content(req: GenerateRequest) -> tuple[dict[str, Any], str, list[str]]:
    category = resolve_category(req)
    messages = build_messages(req, category)
    facts = facts_text(req.product)
    fallback = basic_description(req.product)
    fallback_tags = basic_tags(req.product, category)
    result: dict[str, Any] = {}
    problems: list[str] = []
    provider: str = ""
    last_valid_result: dict[str, Any] = {}

    for _ in range(settings.max_retries + 1):
        text, provider = chat(cast(Any, messages), temperature=0.2)
        try:
            parsed = cast(dict[str, Any], parse_json(text))
            validated_result, problems = cast(
                tuple[dict[str, Any], list[str]],
                validate(parsed, cast(list[str], req.fields), req.options.paragraphs, facts, category),
            )
            result = validated_result
            last_valid_result = parsed
        except ValueError as e:
            problems = [str(e)]
            result = last_valid_result

        if not problems:
            cleaned, notes = cast(
                tuple[dict[str, Any], list[str]],
                strip_unsupported(result, facts, category, fallback, fallback_tags),
            )
            cleaned, fill_notes = ensure_requested_fields(cleaned, req, fallback, fallback_tags)
            return cleaned, provider, notes + fill_notes

        # Tell the model exactly what was wrong and ask again.
        messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "Fix these problems and return the full JSON again: " + "; ".join(problems)},
        ]

    if not result and last_valid_result:
        result = last_valid_result

    if result:
        cleaned, notes = cast(
            tuple[dict[str, Any], list[str]],
            strip_unsupported(result, facts, category, fallback, fallback_tags),
        )
        cleaned, fill_notes = ensure_requested_fields(cleaned, req, fallback, fallback_tags)
        _, remaining = cast(
            tuple[dict[str, Any], list[str]],
            validate(cleaned, cast(list[str], req.fields), None, facts, category),
        )
        limited = cast(dict[str, Any], force_limits(cleaned))
        return limited, provider, notes + fill_notes + remaining  # safe text + notes for the review screen

    raise ValueError("Model never returned valid JSON: " + "; ".join(problems))
