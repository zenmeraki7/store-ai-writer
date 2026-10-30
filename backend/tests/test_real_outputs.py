"""Replays real qwen2.5:3b outputs seen in testing, to make sure invented content is removed for any store type."""
from typing import Any

from app.schemas import ProductInput
from app.service import basic_description, facts_text
from app.validators import strip_unsupported


def run(product: ProductInput, category: str, out: dict[str, Any]):
    return strip_unsupported(out, facts_text(product), category, basic_description(product))


def test_book_with_only_a_title_gets_a_plain_grounded_description():
    p = ProductInput(title="The Lost River Paperback Novel")
    out: dict[str, Any] = {
        "description": "The Lost River is a paperback novel that follows the mysterious disappearance of a river and the search for itstruth. "
                       "The story delves into the lives of the people affected by the river's disappearance, exploring themes ofloss, resilience, and the power of human connection.",
        "tags": ["the-lost-river", "paperback", "novel", "river-disappearance", "resilience", "human-connection", "mystery", "disappearance"],
    }
    cleaned, notes = run(p, "books", out)
    assert cleaned["description"] == "The Lost River Paperback Novel."
    assert cleaned["tags"] == ["the-lost-river", "paperback", "novel"]
    assert notes


def test_kadai_leaked_tags_list_removed_but_good_sentence_kept():
    p = ProductInput(title="Stainless Steel Kadai", attributes={"material": "stainless steel", "capacity": "2 litre"})
    out: dict[str, Any] = {"description": "Stainless Steel Kadai is a 2 litre stainless steel pot suitable for cooking. Tags: stainless steel, 2 litre, kadai.",
           "tags": ["stainless steel", "2 litre", "kadai"]}
    cleaned, _ = run(p, "kitchen", out)
    assert cleaned["description"] == "Stainless Steel Kadai is a 2 litre stainless steel pot suitable for cooking."
    assert cleaned["tags"] == ["stainless steel", "2 litre", "kadai"]


def test_toy_good_sentence_kept_invented_removed():
    p = ProductInput(title="Wooden Building Blocks Toy", attributes={"material": "wood", "pieces": "50"})
    out: dict[str, Any] = {"description": "50 wooden building blocks are perfect for play. Made from sustainable wood, these blocks are for use and come in a variety of shapes and sizes to encourage creativity and problem-solving skills.",
           "tags": ["wooden", "building", "blocks", "toys"]}
    cleaned, _ = run(p, "toys", out)
    assert cleaned["description"] == "50 wooden building blocks are perfect for play."
    assert cleaned["tags"] == ["wooden", "building", "blocks", "toys"]


def test_dress_harmless_sentence_kept():
    p = ProductInput(title="Women Red Maxi Dress", attributes={"color": "red", "length": "full length"})
    out: dict[str, Any] = {"description": "This women's maxi dress is a striking full-length red garment suitable for special occasions.",
           "tags": ["maxi-dress", "red-dress", "women-dress"]}
    cleaned, notes = run(p, "fashion", out)
    assert cleaned["description"] == out["description"] and cleaned["tags"] == out["tags"] and notes == []


def test_rich_data_allows_richer_text():
    p = ProductInput(title="The Lost River", product_type="Paperback Novel",
                     existing_description="A mystery about a village whose river vanishes overnight and the search for the cause.")
    out: dict[str, Any] = {"description": "A mystery about a village whose river vanishes overnight, and the search for the cause.", "tags": ["mystery", "paperback"]}
    cleaned, notes = run(p, "books", out)
    assert cleaned["description"] == out["description"] and notes == []


def test_book_meta_sentence_is_replaced_by_grounded_fallback():
    p = ProductInput(title="The Lost River Paperback Novel")
    out: dict[str, Any] = {"description": "No other details are provided in the product data.", "tags": ["lost-river", "novel", "paperback"]}
    cleaned, notes = run(p, "books", out)
    assert cleaned["description"] == "The Lost River Paperback Novel." and notes


def test_toy_invented_variety_removed_good_kept():
    p = ProductInput(title="Wooden Building Blocks Toy", attributes={"material": "wood", "pieces": "50"})
    out: dict[str, Any] = {"description": "50 wooden building blocks are part of a set designed for play. The blocks are made of wood and come in various shapes and sizes.",
           "tags": ["wooden", "building", "blocks", "toys"]}
    cleaned, _ = run(p, "toys", out)
    assert cleaned["description"] == "50 wooden building blocks are part of a set designed for play."


def test_kadai_and_dress_real_outputs_stay_untouched():
    k = ProductInput(title="Stainless Steel Kadai", attributes={"material": "stainless steel", "capacity": "2 litre"})
    k_out: dict[str, Any] = {"description": "This stainless steel Kadai has a capacity of 2 litres.", "tags": ["stainless-steel", "kadai", "2-litre"]}
    cleaned, notes = run(k, "kitchen", k_out)
    assert cleaned["description"] == "This stainless steel Kadai has a capacity of 2 litres." and notes == []
    d = ProductInput(title="Women Red Maxi Dress", attributes={"color": "red", "length": "full length"})
    d_out: dict[str, Any] = {"description": "This women's maxi dress features a full length design and a striking red color.", "tags": ["maxi-dress", "red-dress", "women-dress"]}
    cleaned, notes = run(d, "fashion", d_out)
    assert notes == []