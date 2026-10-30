import json

from .categories import category_rule
from .schemas import GenerateRequest


def field_rules(req: GenerateRequest) -> dict[str, str]:
    o = req.options
    rules = {
        "title": "string, clear product title, max 150 characters, no keyword stuffing",
        "description": f"string, exactly {o.paragraphs} paragraph(s) separated by a blank line, {o.detail} style",
        "seo_title": "string, max 60 characters",
        "seo_description": "string, max 160 characters",
        "tags": "array of 3 to 8 short lowercase strings, only words from the product data",
    }
    return {f: rules[f] for f in req.fields}


def build_messages(req: GenerateRequest, category: str = "general") -> list[dict[str, str]]:
    o = req.options
    facts = req.product.model_dump(exclude_none=True)
    system = (
        "You write e-commerce product content for an online store.\n"
        "RULES:\n"
        "- Use ONLY the facts in the product data. If a detail is not given, leave it out. Never invent features, "
        "materials, numbers, sizes, ages, quantities, certifications, prices or guarantees. "
        "Keep the text shorter rather than adding unsupported details. Tags must also come only from the data. "
        "Never write comments about missing data (like \"no tags provided\"); output only the product content. "
        "Do not add quality claims (high-quality, premium), target audiences or skill/benefit claims unless given.\n"
        "- Use EVERY fact in the product data (size, colour, capacity, material, page count, language, quantity, etc.); "
        "never leave a supplied fact out. If search keywords are given, work them in naturally where they fit.\n"
        "- If existing_description is present, it is what the merchant already wrote: rewrite it into polished copy and keep all its facts. "
        "If image_caption is present, it is what is visible in the photo.\n"
        f"- Product type rule: {category_rule(category)}\n"
        f"- Tone: {o.tone}. Write everything in {o.language}.\n"
        "- Return ONE JSON object and nothing else (no markdown, no commentary).\n"
        f"- JSON keys and formats: {json.dumps(field_rules(req))}"
    )
    if o.brand_voice:
        system += f"\n- Match this brand voice: {o.brand_voice}"
    user = "Product data:\n" + json.dumps(facts, ensure_ascii=False, indent=2)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
