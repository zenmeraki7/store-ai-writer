import json
import re
from typing import Any

from .categories import risky_terms

LIMITS = {"title": 150, "seo_title": 60, "seo_description": 160}

def parse_json(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in ``` fences or add chatter; extract the first object."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("JSON output is not an object")
    return data


def count_paragraphs(text: str) -> int:
    return len([p for p in re.split(r"\n+", text.strip()) if p.strip()])


def _norm(s: str) -> str:
    return s.lower().replace("-", " ").replace("_", " ")


META_PHRASES = [
    "no additional", "not provided", "not specified", "not available", "no information", "n/a",
    "tags:", "product data", "as an ai", "i cannot", "i can't", "unavailable", "no tags", "none provided", "no further",
]


META_RE = re.compile(r"\b(no|not|none|without)\b[^.]{0,40}\b(provid\w*|specif\w*|avail\w*|given|mention\w*)\b")


def _meta_hits(t: str) -> list[str]:
    hits = [m for m in META_PHRASES if m in t]
    m = META_RE.search(t)
    if m:
        hits.append(m.group(0))
    return hits


def check_meta(result: dict[str, Any]) -> list[str]:
    """Catch the model talking about the task ('No additional tags provided') inside the content."""
    blob = _norm(" ".join(" ".join(v) if isinstance(v, list) else str(v) for v in result.values()))
    hits = _meta_hits(blob)
    if not hits:
        return []
    return ["Remove comments about missing data (" + ", ".join(hits) + "); write only the product content"]


def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", s))


def check_grounding(result: dict[str, Any], facts: str, category: str = "general") -> list[str]:
    """Flag risky terms and numbers that appear in the output but not in the product data."""
    facts_n = _norm(facts)
    blob = _norm(" ".join(" ".join(v) if isinstance(v, list) else str(v) for v in result.values()))
    found = []
    for t in dict.fromkeys(risky_terms(category)):
        pat = rf"\b{re.escape(_norm(t))}"
        if re.search(pat, blob) and not re.search(pat, facts_n):
            found.append(t)
    problems = []
    if found:
        problems.append(
            "These details are NOT in the product data, remove them from every field (including tags): " + ", ".join(found)
        )
    invented = sorted(_numbers(blob) - _numbers(facts_n))
    if invented:
        problems.append("These numbers are NOT in the product data, remove them: " + ", ".join(invented))
    return problems


def validate(data: dict[str, Any], fields: list[str], paragraphs: int | None = None, facts: str | None = None, category: str = "general") -> tuple[dict[str, Any], list[str]]:
    problems, out = [], {}
    for f in fields:
        v = data.get(f)
        if v is None or v == "" or v == []:
            problems.append(f"Missing field: {f}")
            continue
        if f == "tags":
            if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
                problems.append("tags must be an array of strings")
                continue
            v = [t.strip().lower() for t in v if t.strip()][:10]
        elif not isinstance(v, str):
            problems.append(f"{f} must be a string")
            continue
        else:
            v = v.strip()
            if f in LIMITS and len(v) > LIMITS[f]:
                problems.append(f"{f} is {len(v)} characters; max is {LIMITS[f]}")
        out[f] = v
    if paragraphs and isinstance(out.get("description"), str):
        n = count_paragraphs(out["description"])
        if n != paragraphs:
            problems.append(
                f"description has {n} paragraph(s) but needs exactly {paragraphs}; separate paragraphs with a blank line"
            )
    if facts is not None:
        problems += check_grounding(out, facts, category)
        problems += check_meta(out)
    return out, problems


STOP = set("""this that these those with from have has had were was been being their there they them then than
into onto your yours about above after also and are but can for not you all any each every more most much only other
over some such very what when where which while who will would could should its out our own same too just like both
here through between during using make get gets one two""".split())
GENERIC = set("""perfect great ideal suitable designed design features feature featuring offers offer product item items
piece pieces sets made makes come comes provide provides enjoy easy simple style stylish look looks""".split())
NOVEL_MIN, NOVEL_RATIO = 4, 0.5


def _stem(w: str) -> str:
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ss"):
        return w
    if w.endswith("s") and len(w) > 3:
        return w[:-1]
    return w


def _words(text: str, min_len: int = 4) -> list[str]:
    t = text.lower().replace("\u2019", "'")
    t = re.sub(r"'s\b", "", t).replace("-", " ")
    return [w for w in re.findall(rf"[a-z]{{{min_len},}}", t) if w not in STOP]


def _stems(facts: str) -> set[str]:
    # short words (toy, red, bed) count as known facts too, so plurals like "toys" match
    return {_stem(w) for w in _words(facts, 3)}


def _mostly_new(text: str, stems: set[str]) -> bool:
    """General invention detector: a sentence made mostly of words that are not in the product data."""
    words = _words(text)
    novel = [w for w in words if _stem(w) not in stems and w not in GENERIC]
    return len(novel) >= NOVEL_MIN and len(novel) / len(words) >= NOVEL_RATIO


def _has_new_word(text: str, stems: set[str]) -> bool:
    return any(_stem(w) not in stems and w not in GENERIC for w in _words(text, 3))


def _is_unsupported(text: str, facts_n: str, category: str, stems: set[str] | None = None, kind: str = "sentence") -> bool:
    t = _norm(text)
    for term in dict.fromkeys(risky_terms(category)):
        pat = rf"\b{re.escape(_norm(term))}"
        if re.search(pat, t) and not re.search(pat, facts_n):
            return True
    if _numbers(t) - _numbers(facts_n):
        return True
    if _meta_hits(t):
        return True
    stems = stems if stems is not None else _stems(facts_n)
    return _has_new_word(text, stems) if kind == "tag" else _mostly_new(text, stems)


def strip_unsupported(
    result: dict[str, Any],
    facts: str,
    category: str = "general",
    fallback: str | None = None,
    fallback_tags: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Drop invented sentences and tags. If nothing in the description survives, use `fallback`
    (a plain description built only from the product data). Returns the result plus notes of what changed."""
    facts_n = _norm(facts)
    stems = _stems(facts_n)
    cleaned, notes = {}, []
    for k, v in result.items():
        if k == "tags" and isinstance(v, list):
            keep = [t for t in v if not _is_unsupported(t, facts_n, category, stems, "tag")]
            if len(keep) != len(v):
                notes.append("Removed unsupported tags: " + ", ".join(t for t in v if t not in keep))
            if not keep and fallback_tags:
                keep = fallback_tags
                notes.append("Generated grounded tags from product data.")
            cleaned[k] = keep
        elif k in ("title", "seo_title", "seo_description") and isinstance(v, str):
            if _is_unsupported(v, facts_n, category, stems):
                notes.append(f"Model generated unsupported claim in {k}; reverted to grounded value.")
                base_title = fallback.split(".")[0].strip() if fallback else v
                cleaned[k] = base_title if k != "seo_description" else base_title + "."
            else:
                cleaned[k] = v
        elif k == "description" and isinstance(v, str):
            paras, removed = [], []
            for para in re.split(r"\n+", v):
                sentences = re.split(r"(?<=[.!?])\s+", para.strip())
                good = [x for x in sentences if x and not _is_unsupported(x, facts_n, category, stems)]
                removed += [x for x in sentences if x and x not in good]
                if good:
                    paras.append(" ".join(good))
            if removed and paras:
                notes.append("Removed unsupported sentence(s): " + " | ".join(removed))
                cleaned[k] = "\n\n".join(paras)
            elif removed and fallback:
                notes.append("The model invented details, so a basic description was built from the product data. "
                             "Add more product details (attributes, features) for richer text. Removed: " + " | ".join(removed))
                cleaned[k] = fallback
            else:
                if removed:
                    notes.append("Whole description looked unsupported; review it manually")
                cleaned[k] = v
        else:
            cleaned[k] = v
    return cleaned, notes


def truncate_words(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")


def force_limits(result: dict[str, Any]) -> dict[str, Any]:
    """Last resort after retries: hard-trim over-length fields."""
    return {k: truncate_words(v, LIMITS[k]) if k in LIMITS and isinstance(v, str) else v for k, v in result.items()}
