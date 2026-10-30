"""Per-category rules. To support a new kind of store, add one entry to CATEGORIES.
 rule     -> tells the model what it must never invent for this kind of product
 risky    -> words that, if they appear in the output but not in the product data, are treated as invented
 keywords -> used to auto-detect the category from title / product type / tags
Unknown or unlisted products fall back to 'general' (universal rules + the numbers check)."""
import re
from typing import TypedDict


class CategoryConfig(TypedDict):
    rule: str
    risky: list[str]
    keywords: list[str]


# Claims that are risky for ANY product type.
UNIVERSAL_RISKY = [
    "warranty", "guarantee", "certified", "certification", "organic", "vegan", "hypoallergenic",
    "waterproof", "bpa free", "non toxic", "eco friendly", "handmade", "award", "patented",
    "clinically", "fda approved", "made in", "best seller", "bestselling",
    # quality / marketing claims
    "high quality", "premium", "durable", "long lasting", "top quality", "superior",
    # target audience not given in the data
    "child", "kids", "toddler", "baby", "babies", "girls", "boys", "adults", "teen",
    # benefit / skill claims
    "motor skills", "cognitive", "develop", "creativity", "imaginative", "natural",
    # invented variety / specs
    "various", "variety", "assorted", "shapes", "sizes", "colors", "colours",
]

CATEGORIES: dict[str, CategoryConfig] = {
    "general": {
        "rule": "Describe only what the product data supports. Do not invent materials, sizes, ages, quantities, brands or uses.",
        "risky": [],
        "keywords": [],
    },
    "fashion": {
        "rule": "Do NOT mention fabric, material, washing or care instructions, fit, stretch, pockets or sizes unless given.",
        "risky": ["fabric", "material", "cotton", "polyester", "linen", "silk", "wool", "denim", "leather", "viscose",
                  "rayon", "satin", "chiffon", "nylon", "breathable", "lightweight", "stretch", "wash", "iron",
                  "dry clean", "pocket", "lined", "zipper", "button", "neckline", "collar", "sleeve"],
        "keywords": ["dress", "shirt", "t-shirt", "tshirt", "kurta", "saree", "jeans", "top", "skirt", "jacket",
                     "hoodie", "shoe", "sandal", "footwear", "apparel", "trouser", "shorts", "legging", "lehenga"],
    },
    "toys": {
        "rule": "Do NOT invent age range, safety standards or certifications, materials, battery needs, number of pieces, or educational/learning claims unless given.",
        "risky": ["age", "years old", "safe", "safety", "choking", "battery", "batteries", "pieces", "educational",
                  "stem", "learning", "washable", "plastic", "wooden", "plush", "remote control"],
        "keywords": ["toy", "doll", "puzzle", "lego", "board game", "action figure", "plush", "teddy", "rc car",
                     "building blocks", "playset", "game"],
    },
    "books": {
        "rule": "Do NOT invent the author, publisher, plot, characters, themes, page count, edition, language, ISBN, awards, reviews or target readers unless given.",
        "risky": ["author", "written by", "publisher", "isbn", "edition", "hardcover", "paperback", "pages",
                  "chapters", "translated", "sequel", "series", "novel", "readers", "reviews"],
        "keywords": ["book", "novel", "paperback", "hardcover", "textbook", "comic", "magazine", "workbook", "guide"],
    },
    "electronics": {
        "rule": "Focus on the given specs. Do NOT invent specifications, battery life, compatibility, connectivity, warranty or certifications.",
        "risky": ["battery", "mah", "wireless", "bluetooth", "usb", "hdmi", "compatible", "resolution", "processor",
                  "ram", "storage", "gb", "watt", "fast charging", "noise cancel", "display"],
        "keywords": ["phone", "laptop", "headphone", "earbud", "charger", "cable", "camera", "tv", "speaker",
                     "smartwatch", "power bank", "tablet", "router", "mouse", "keyboard"],
    },
    "kitchen": {
        "rule": "Do NOT invent material, capacity, power, dishwasher/microwave/induction suitability, food-safety claims or included accessories unless given.",
        "risky": ["stainless steel", "steel", "aluminium", "aluminum", "non stick", "nonstick", "dishwasher",
                  "microwave", "induction", "food grade", "capacity", "litre", "liter", "ml", "watt",
                  "heat resistant", "oven safe", "gas stove"],
        "keywords": ["kitchen", "cookware", "pan", "pot", "kadai", "cooker", "mixer", "grinder", "knife", "utensil",
                     "bottle", "lunch box", "tiffin", "container", "blender", "kettle"],
    },
    "food": {
        "rule": "Do NOT invent ingredients, allergens, nutrition values, shelf life, dietary or health claims unless given.",
        "risky": ["ingredient", "allergen", "gluten", "sugar free", "calories", "protein", "preservative",
                  "shelf life", "fssai", "nutrition", "natural", "fresh", "healthy"],
        "keywords": ["snack", "tea", "coffee", "spice", "masala", "rice", "oil", "chocolate", "biscuit", "juice",
                     "honey", "flour", "pickle", "sauce"],
    },
    "beauty": {
        "rule": "Do NOT invent ingredients, skin-type suitability, results, or medical/therapeutic claims unless given.",
        "risky": ["skin type", "dermatologist", "paraben", "sulphate", "sulfate", "spf", "cruelty free", "ayurvedic",
                  "natural", "anti aging", "acne", "fragrance", "glow", "moisturi"],
        "keywords": ["cream", "serum", "shampoo", "lotion", "lipstick", "perfume", "makeup", "skincare", "soap",
                     "face wash", "conditioner"],
    },
    "home": {
        "rule": "Do NOT invent materials, dimensions, weight or load capacity, assembly details or room suitability unless given.",
        "risky": ["wood", "teak", "sheesham", "metal", "foam", "assembly", "dimensions", "cm", "inches",
                  "load capacity", "weight capacity", "fabric"],
        "keywords": ["sofa", "bed", "chair", "table", "curtain", "bedsheet", "pillow", "lamp", "decor", "mattress",
                     "shelf", "cushion"],
    },
    "jewelry": {
        "rule": "Do NOT invent metal, purity, stones, plating, hallmark or weight unless given.",
        "risky": ["gold", "silver", "sterling", "diamond", "gemstone", "plated", "hallmark", "platinum", "pearl",
                  "stone", "nickel free", "18k", "22k"],
        "keywords": ["ring", "necklace", "earring", "bracelet", "pendant", "jewel", "bangle", "anklet"],
    },
    "sports": {
        "rule": "Do NOT invent materials, sizes, weight, skill level or performance claims unless given.",
        "risky": ["professional", "beginner", "material", "durable", "grip", "weight", "size"],
        "keywords": ["cricket", "football", "yoga", "dumbbell", "gym", "bat", "racket", "cycling", "badminton"],
    },
}


def category_rule(category: str) -> str:
    return CATEGORIES.get(category, CATEGORIES["general"])["rule"]


def risky_terms(category: str) -> list[str]:
    return UNIVERSAL_RISKY + CATEGORIES.get(category, CATEGORIES["general"])["risky"]


def detect_category(text: str) -> str:
    text = text.lower().replace("-", " ")
    best, best_score = "general", 0
    for name, c in CATEGORIES.items():
        score = sum(1 for kw in c["keywords"] if re.search(rf"\b{re.escape(kw.replace('-', ' '))}s?\b", text))
        if score > best_score:
            best, best_score = name, score
    return best
