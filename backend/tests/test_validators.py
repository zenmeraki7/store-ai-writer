import pytest
from app.validators import check_grounding, count_paragraphs, force_limits, parse_json, validate


def test_parse_json_strips_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_with_chatter():
    assert parse_json('Sure! Here you go: {"a": "b"} Hope it helps') == {"a": "b"}


def test_parse_json_fails():
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_validate_flags_long_seo_title_and_missing():
    _, problems = validate({"seo_title": "x" * 70}, ["seo_title", "description"])
    assert any("seo_title" in p for p in problems)
    assert "Missing field: description" in problems


def test_validate_tags_normalised():
    out, problems = validate({"tags": [" Red ", "DRESS"]}, ["tags"])
    assert out["tags"] == ["red", "dress"] and not problems


def test_force_limits_trims_on_word_boundary():
    out = force_limits({"seo_title": "word " * 20})
    assert len(out["seo_title"]) <= 60 and not out["seo_title"].endswith(" ")


def test_grounding_flags_invented_and_allows_supplied():
    facts = "women red maxi dress cotton full length"
    out = {"description": "Soft cotton. Lightweight, breathable fabric. Hand wash.", "tags": ["hand-wash"]}
    msg = check_grounding(out, facts, "fashion")[0]
    assert "breathable" in msg and "wash" in msg and "cotton" not in msg


def test_paragraph_count_checked():
    _, problems = validate({"description": "One paragraph only."}, ["description"], paragraphs=2)
    assert any("paragraph" in p for p in problems)
    assert count_paragraphs("A\n\nB") == 2


def test_grounding_toys_books_and_numbers():
    toy = check_grounding({"description": "Suitable for ages 3 and up, made of non-toxic plastic."}, "wooden train toy", "toys")
    assert "age" in toy[0] and any("3" in p for p in toy)
    book = check_grounding({"description": "A bestselling novel written by a famous author."}, "the lost river book", "books")
    assert "author" in book[0]
    num = check_grounding({"description": "Holds 500 ml and 2 cups."}, "steel bottle 750 ml", "kitchen")
    assert any("500" in p and "750" not in p for p in num)


def test_detect_category():
    from app.categories import detect_category
    assert detect_category("Harry Potter Hardcover Edition") == "books"
    assert detect_category("Wooden Building Blocks Toy") == "toys"
    assert detect_category("Stainless Steel Kadai") == "kitchen"
    assert detect_category("Women Red Maxi Dress") == "fashion"
    assert detect_category("Widget 3000") == "general"


def test_replay_real_toy_output_is_flagged():
    facts = '{"title": "Wooden Building Blocks Toy", "attributes": {"material": "wood", "pieces": "50"}}'
    out = {
        "description": "Perfect for developing fine motor skills. Crafted from high-quality wood, a set of 50 pieces. No additional tags provided.",
        "tags": ["toys", "wooden", "children", "development"],
    }
    _, problems = validate(out, ["description", "tags"], 1, facts, "toys")
    text = " ".join(problems)
    assert "motor skills" in text and "high quality" in text and "child" in text and "No additional" not in text and "no additional" in text
    assert "50" not in text and "wood" not in text.replace("wooden", "")  # supplied facts stay allowed


def test_strip_unsupported_removes_sentences_and_tags():
    from app.validators import strip_unsupported
    facts = '{"title": "Wooden Building Blocks Toy", "attributes": {"material": "wood", "pieces": "50"}}'
    out = {"description": "50 wooden blocks for play. Perfect for children to build.", "tags": ["toys", "children", "wooden"]}
    cleaned, notes = strip_unsupported(out, facts, "toys")
    assert cleaned["description"] == "50 wooden blocks for play."
    assert cleaned["tags"] == ["toys", "wooden"]
    assert len(notes) == 2


def test_short_word_novel_tag_detected():
    from app.validators import _has_new_word, _stems
    facts = "women red maxi dress"
    stems = _stems(facts)
    # 'box' is not in facts and not in STOP/GENERIC
    assert _has_new_word("box", stems)
    # 'red' is in facts
    assert not _has_new_word("red", stems)


def test_basic_description_preserves_existing_description():
    from app.schemas import ProductInput
    from app.service import basic_description
    p = ProductInput(title="Sample Book", existing_description="A verified existing merchant description.")
    assert basic_description(p) == "A verified existing merchant description."


def test_basic_tags_grounded():
    from app.schemas import ProductInput
    from app.service import basic_tags
    p = ProductInput(title="Stainless Steel Kadai", attributes={"capacity": "2 litre"})
    tags = basic_tags(p, "kitchen")
    assert "stainless" in tags and "steel" in tags and "kadai" in tags


def test_strip_unsupported_cleans_hallucinated_seo_fields():
    from app.validators import strip_unsupported
    facts = "women red dress"
    out = {
        "title": "Red Dress With 10 Year Warranty",
        "seo_title": "Red Dress 100% Organic Silk",
        "description": "A red dress."
    }
    cleaned, notes = strip_unsupported(out, facts, "fashion", fallback="Red Dress.")
    assert "Warranty" not in cleaned["title"]
    assert "Organic" not in cleaned["seo_title"]
    assert any("seo_title" in n for n in notes)
