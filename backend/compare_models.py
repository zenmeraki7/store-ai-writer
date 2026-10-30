"""Compare local Ollama models on the same products, for different store types.

Usage (from the backend folder, Ollama running):
    python compare_models.py qwen2.5:3b gemma3:4b

Prints every result with time and warnings, and saves compare_report.md.
"""
import importlib
import sys
import time
from typing import Any

import app.llm as llm
from app.config import settings
from app.schemas import GenerateRequest, Options, ProductInput
from app.service import generate_content

PRODUCTS: list[dict[str, Any]] = [
    {"title": "Wooden Building Blocks Toy", "attributes": {"material": "wood", "pieces": "50"}},
    {"title": "The Lost River Paperback Novel", "attributes": {}},
    {"title": "Stainless Steel Kadai", "attributes": {"material": "stainless steel", "capacity": "2 litre"}},
    {"title": "Women Red Maxi Dress", "attributes": {"color": "red", "length": "full length"}},
    # richer data: lets you see how much better the text gets when the merchant supplies details
    {"title": "The Lost River", "product_type": "Paperback Novel",
     "existing_description": "A mystery about a village whose river vanishes overnight and the search for the cause.",
     "attributes": {"language": "English", "pages": "320"}},
]


def run_one(product: dict[str, Any]) -> tuple[dict[str, Any], list[str], float]:
    req = GenerateRequest(
        product=ProductInput(**product),
        options=Options(category="auto", paragraphs=1),
        fields=["description", "tags"],
    )
    start = time.time()
    try:
        result, _provider, warnings = generate_content(req)
    except Exception as e:  # keep going so one failure doesn't hide the rest
        result, warnings = {}, [f"ERROR: {e}"]
    return result, warnings, time.time() - start


def main(models: list[str]) -> None:
    lines = ["# Model comparison\n"]
    totals: dict[str, float] = {}
    for m in models:
        settings.provider_order, settings.ollama_model = "ollama", m
        importlib.reload(llm)  # rebuild the provider for this model
        print(f"\n############ MODEL: {m}")
        lines.append(f"\n## {m}\n")
        total = 0.0
        for p in PRODUCTS:
            result, warnings, secs = run_one(p)
            total += secs
            tags = ", ".join(result.get("tags", []))
            print(f"\n=== {p['title']}  ({secs:.1f} s)\n{result.get('description', '')}\nTAGS: {tags}\nWARNINGS: {' | '.join(warnings) or '-'}")
            lines.append(f"**{p['title']}** ({secs:.1f} s)\n\n{result.get('description', '')}\n\nTags: {tags}\n\nWarnings: {' | '.join(warnings) or '-'}\n")
        totals[m] = total
        print(f"\n--- {m}: total {total:.1f} s, average {total / len(PRODUCTS):.1f} s per product")
    lines.append("\n## Totals\n" + "\n".join(f"- {m}: {t:.1f} s" for m, t in totals.items()))
    open("compare_report.md", "w", encoding="utf-8").write("\n".join(lines))
    print("\nSaved compare_report.md")


if __name__ == "__main__":
    main(sys.argv[1:] or [settings.ollama_model])
