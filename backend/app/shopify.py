"""Shopify connection: read products from the store, save approved text back.

Works in two modes:
  live  - SHOPIFY_SHOP plus either SHOPIFY_ACCESS_TOKEN, or SHOPIFY_CLIENT_ID and
          SHOPIFY_CLIENT_SECRET (Dev Dashboard apps), are set in .env
  demo  - nothing is set, so a small built-in sample store is used (nothing leaves your machine)

Every save keeps a copy of the old text in backend/data/backups.jsonl so it can be undone.
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

router = APIRouter(prefix="/shopify", tags=["shopify"])

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BACKUP_FILE = DATA_DIR / "backups.jsonl"
PAGE_SIZE = 25


# --------------------------------------------------------------------------- settings
def _dotenv() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def env(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v is None:
        v = _dotenv().get(name, default)
    return (v or "").strip()


def shop_domain() -> str:
    s = env("SHOPIFY_SHOP") or env("SHOPIFY_STORE")
    s = re.sub(r"^https?://", "", s).strip("/")
    if s.endswith(".myshopify.com"):
        s = s[: -len(".myshopify.com")]
    return s


def mode() -> str:
    if env("SHOPIFY_DEMO").lower() in ("1", "true", "yes"):
        return "demo"
    has_auth = env("SHOPIFY_ACCESS_TOKEN") or (env("SHOPIFY_CLIENT_ID") and env("SHOPIFY_CLIENT_SECRET"))
    return "live" if shop_domain() and has_auth else "demo"


def api_version() -> str:
    return env("SHOPIFY_API_VERSION", "2026-07")


class ShopifyError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- http + auth
def _http(url: str, *, data: Optional[bytes] = None, headers: Optional[dict[str, str]] = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise ShopifyError(f"Shopify answered {e.code}. {body}".strip(), status=e.code) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ShopifyError(f"Could not reach the server: {getattr(e, 'reason', e)}") from e


_tok = {"value": "", "expires": 0.0}
_tok_lock = threading.Lock()


def get_token(force: bool = False) -> str:
    static = env("SHOPIFY_ACCESS_TOKEN")
    if static:
        return static
    with _tok_lock:
        if not force and _tok["value"] and time.time() < _tok["expires"] - 60:
            return _tok["value"]
        form = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": env("SHOPIFY_CLIENT_ID"),
            "client_secret": env("SHOPIFY_CLIENT_SECRET"),
        }).encode()
        raw = _http(
            f"https://{shop_domain()}.myshopify.com/admin/oauth/access_token",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        j = json.loads(raw)
        if not j.get("access_token"):
            raise ShopifyError("Shopify did not return an access token. Check the client ID and secret.")
        _tok["value"] = j["access_token"]
        _tok["expires"] = time.time() + float(j.get("expires_in", 86399))
        return _tok["value"]


def gql(query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    url = f"https://{shop_domain()}.myshopify.com/admin/api/{api_version()}/graphql.json"
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()

    def call() -> dict[str, Any]:
        raw = _http(url, data=payload, headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": get_token(),
        })
        return json.loads(raw)

    try:
        out = call()
    except ShopifyError as e:
        if e.status == 401 and not env("SHOPIFY_ACCESS_TOKEN"):
            get_token(force=True)
            out = call()
        elif e.status in (401, 403):
            raise ShopifyError(
                "Shopify rejected the access. Check that the app is installed on the store and has the "
                "read_products and write_products permissions.", status=e.status) from e
        elif e.status == 404:
            raise ShopifyError("Shopify could not find that store. Check SHOPIFY_SHOP in .env.", status=404) from e
        else:
            raise
    if out.get("errors"):
        errs = out["errors"]
        msg = "; ".join(x.get("message", str(x)) for x in errs) if isinstance(errs, list) else str(errs)
        raise ShopifyError(msg)
    return out["data"]


# --------------------------------------------------------------------------- shaping
FRAGMENT = """
fragment P on Product {
  id title handle vendor productType tags status descriptionHtml
  seo { title description }
  featuredMedia { preview { image { url altText } } }
  options { name values }
}
"""
LIST_QUERY = FRAGMENT + """
query Products($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query, sortKey: UPDATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    nodes { ...P }
  }
}"""
ONE_QUERY = FRAGMENT + "query One($id: ID!) { product(id: $id) { ...P } }"
UPDATE_MUTATION = FRAGMENT + """
mutation Update($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product { ...P }
    userErrors { field message }
  }
}"""


def strip_html(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"(?i)<\s*br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</\s*(p|div|li|h[1-6]|tr)\s*>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def text_to_html(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n{2,}", text.strip()) if p.strip()]
    return "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paras)


def merge_tags(current: list[str], new: list[str]) -> list[str]:
    seen = {t.lower() for t in current}
    out = list(current)
    for t in new:
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def shape(node: dict[str, Any]) -> dict[str, Any]:
    """Turn a Shopify product into what the UI needs, including a ready-to-use /generate input."""
    attrs: dict[str, str] = {}
    for o in node.get("options") or []:
        values = [str(v) for v in (o.get("values") or []) if str(v).strip()]
        if not values or (o.get("name") == "Title" and values == ["Default Title"]):
            continue
        attrs[o["name"]] = ", ".join(values)
    image = (((node.get("featuredMedia") or {}).get("preview") or {}).get("image")) or {}
    description = strip_html(node.get("descriptionHtml"))
    seo = node.get("seo") or {}
    product = {
        "id": node["id"],
        "title": node.get("title") or "",
        "handle": node.get("handle") or "",
        "vendor": node.get("vendor") or "",
        "product_type": node.get("productType") or "",
        "tags": list(node.get("tags") or []),
        "status": (node.get("status") or "").lower(),
        "existing_description": description,
        "attributes": attrs,
        "image_url": image.get("url"),
        "image_alt": image.get("altText"),
        "seo_title": seo.get("title") or "",
        "seo_description": seo.get("description") or "",
    }
    product["input"] = {
        "title": product["title"],
        "product_type": product["product_type"],
        "vendor": product["vendor"],
        "attributes": attrs,
        "tags": product["tags"],
        "existing_description": description or None,
    }
    return product


# --------------------------------------------------------------------------- demo store
def _demo_nodes() -> dict[str, dict[str, Any]]:
    def node(i, title, vendor, ptype, tags, options, desc=""):
        return {
            "id": f"demo-{i}", "title": title, "handle": re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
            "vendor": vendor, "productType": ptype, "tags": tags, "status": "ACTIVE",
            "descriptionHtml": desc, "seo": {"title": "", "description": ""}, "featuredMedia": None,
            "options": [{"name": k, "values": v} for k, v in options.items()],
        }
    items = [
        node(1, "METRONAUT Women Regular Fit Printed Spread Collar Casual Shirt", "METRONAUT", "Shirts",
             ["women", "shirt"], {"Size": ["S", "M", "L", "XL"], "Colour": ["Blue"]}),
        node(2, "Stainless Steel Kadai", "", "Cookware", [], {"Material": ["Stainless steel"], "Capacity": ["2 litre"]}),
        node(3, "The Lost River", "", "Book", ["mystery", "novel"],
             {"Format": ["Paperback"], "Pages": ["320"], "Language": ["English"]},
             "<p>A mystery about a village whose river vanishes overnight and the search for the cause.</p>"),
        node(4, "Women Red Maxi Dress", "", "Clothing", [], {"Colour": ["Red"], "Size": ["S", "M", "L"], "Length": ["Full length"]}),
        node(5, "Wooden Building Blocks Toy", "", "Toys", [], {"Title": ["Default Title"]}, "<p>50 wooden building blocks.</p>"),
        node(6, "Men Slim Fit Cotton Jeans", "Northlane", "Jeans", ["men", "jeans"],
             {"Size": ["30", "32", "34", "36"], "Colour": ["Dark blue"], "Fabric": ["Cotton"]}),
    ]
    return {n["id"]: n for n in items}


DEMO_DB: dict[str, dict] = _demo_nodes()


# --------------------------------------------------------------------------- store access (live or demo)
def fetch_products(search: str, after: Optional[str]) -> tuple[list[dict[str, Any]], Optional[str]]:
    term = re.sub(r"[^\w\s-]", " ", search or "").strip()
    if mode() == "demo":
        rows = [n for n in DEMO_DB.values() if not term or term.lower() in n["title"].lower()]
        start = int(after) if after and after.isdigit() else 0
        page = rows[start:start + PAGE_SIZE]
        nxt = str(start + PAGE_SIZE) if start + PAGE_SIZE < len(rows) else None
        return [shape(n) for n in page], nxt
    variables: dict[str, Any] = {"first": PAGE_SIZE, "after": after or None,
                                 "query": f"title:*{term}*" if term else None}
    data = gql(LIST_QUERY, variables)["products"]
    info = data["pageInfo"]
    return [shape(n) for n in data["nodes"]], (info["endCursor"] if info["hasNextPage"] else None)


def fetch_node(pid: str) -> dict[str, Any]:
    if mode() == "demo":
        if pid not in DEMO_DB:
            raise ShopifyError("That product was not found.", status=404)
        return DEMO_DB[pid]
    node = gql(ONE_QUERY, {"id": pid}).get("product")
    if not node:
        raise ShopifyError("That product was not found in your store.", status=404)
    return node


def update_node(pid: str, changes: dict[str, Any]) -> dict[str, Any]:
    if mode() == "demo":
        node = DEMO_DB[pid]
        node.update({k: v for k, v in changes.items() if k != "seo"})
        if "seo" in changes:
            node["seo"] = {**(node.get("seo") or {}), **changes["seo"]}
        return node
    out = gql(UPDATE_MUTATION, {"product": {"id": pid, **changes}})["productUpdate"]
    if out.get("userErrors"):
        raise ShopifyError("; ".join(e["message"] for e in out["userErrors"]), status=422)
    return out["product"]


# --------------------------------------------------------------------------- backups
_backup_lock = threading.Lock()


def _write_backup(pid: str, before: dict[str, Any], after: dict[str, Any]) -> str:
    bid = f"{int(time.time() * 1000)}-{pid.rsplit('/', 1)[-1]}"
    rec = {"id": bid, "product": pid, "shop": shop_domain() or "demo", "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "before": before, "after": after}
    with _backup_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with BACKUP_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return bid


def _find_backup(bid: str) -> Optional[dict[str, Any]]:
    try:
        lines = BACKUP_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("id") == bid:
            return rec
    return None


def _snapshot(node: dict[str, Any]) -> dict[str, Any]:
    seo = node.get("seo") or {}
    return {"title": node.get("title") or "", "descriptionHtml": node.get("descriptionHtml") or "",
            "tags": list(node.get("tags") or []), "seo": {"title": seo.get("title") or "", "description": seo.get("description") or ""}}


# --------------------------------------------------------------------------- endpoints
class SaveRequest(BaseModel):
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None


class UndoRequest(BaseModel):
    backup_id: str


class CaptionRequest(BaseModel):
    image_url: str


def _guard(fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except ShopifyError as e:
        raise HTTPException(status_code=e.status if 400 <= e.status < 600 else 502, detail=str(e))


@router.get("/status")
async def status():
    m = mode()
    return {"mode": m, "shop": shop_domain() if m == "live" else "", "api_version": api_version()}


@router.get("/products")
async def products(search: str = Query("", max_length=80), after: Optional[str] = Query(None, max_length=200)):
    rows, nxt = await run_in_threadpool(_guard, fetch_products, search, after)
    return {"mode": mode(), "products": rows, "next": nxt}


def _save(req: SaveRequest) -> dict[str, Any]:
    if mode() == "live" and not req.id.startswith("gid://shopify/Product/"):
        raise ShopifyError("That is not a valid product id.", status=400)
    cur = fetch_node(req.id)
    before = _snapshot(cur)
    changes: dict[str, Any] = {}
    if req.title and req.title.strip():
        changes["title"] = req.title.strip()[:255]
    if req.description is not None and req.description.strip():
        changes["descriptionHtml"] = text_to_html(req.description)
    if req.tags:
        changes["tags"] = merge_tags(before["tags"], req.tags)
    if req.seo_title is not None or req.seo_description is not None:
        changes["seo"] = {
            "title": (req.seo_title if req.seo_title is not None else before["seo"]["title"])[:70],
            "description": (req.seo_description if req.seo_description is not None else before["seo"]["description"])[:320],
        }
    if not changes:
        raise ShopifyError("There is nothing to save.", status=400)
    updated = update_node(req.id, changes)
    bid = _write_backup(req.id, before, _snapshot(updated))
    return {"ok": True, "backup_id": bid, "product": shape(updated)}


@router.post("/save")
async def save(req: SaveRequest):
    return await run_in_threadpool(_guard, _save, req)


def _undo(req: UndoRequest) -> dict[str, Any]:
    rec = _find_backup(req.backup_id)
    if not rec:
        raise ShopifyError("That saved change could not be found, so it can't be undone from here.", status=404)
    b = rec["before"]
    updated = update_node(rec["product"], {"title": b["title"], "descriptionHtml": b["descriptionHtml"],
                                           "tags": b["tags"], "seo": b["seo"]})
    return {"ok": True, "product": shape(updated)}


@router.post("/undo")
async def undo(req: UndoRequest):
    return await run_in_threadpool(_guard, _undo, req)


def _caption(req: CaptionRequest) -> dict[str, Any]:
    if mode() == "demo":
        raise ShopifyError("Reading photos needs a connected store.", status=400)
    u = urllib.parse.urlparse(req.image_url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not (host == "cdn.shopify.com" or host.endswith(".shopify.com")):
        raise ShopifyError("Only photos hosted by Shopify can be read.", status=400)
    q = dict(urllib.parse.parse_qsl(u.query))
    q["width"] = "768"
    img_url = urllib.parse.urlunparse(u._replace(query=urllib.parse.urlencode(q)))
    img = _http(img_url, timeout=30)
    if len(img) > 8_000_000:
        raise ShopifyError("That photo is too large to read.", status=400)
    base = env("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    base = re.sub(r"/v1$", "", base)
    model = env("OLLAMA_VISION_MODEL") or env("OLLAMA_MODEL", "gemma3:4b")
    body = json.dumps({
        "model": model, "stream": False,
        "messages": [{
            "role": "user",
            "content": ("Describe only what is clearly visible in this product photo, in one plain sentence: "
                        "colours, pattern and style. Do not guess the brand, material, size, fit, price or anything "
                        "you cannot see. Reply with the sentence only."),
            "images": [base64.b64encode(img).decode()],
        }],
    }).encode()
    try:
        raw = _http(f"{base}/api/chat", data=body, headers={"Content-Type": "application/json"}, timeout=180)
    except ShopifyError as e:
        raise ShopifyError(f"The writing model could not read the photo ({e}). It needs a model that understands images, such as gemma3:4b.") from e
    text = (json.loads(raw).get("message") or {}).get("content", "").strip().replace("\n", " ")
    return {"caption": text[:300]}


@router.post("/caption")
async def caption(req: CaptionRequest):
    return await run_in_threadpool(_guard, _caption, req)


def _check() -> dict[str, Any]:
    if mode() == "demo":
        return {"ok": False, "mode": "demo", "shop": "",
                "message": "No store is connected yet. Run the command in step 2, then check again."}
    d = gql("{ shop { name } products(first: 1) { nodes { id } } }")
    return {"ok": True, "mode": "live", "shop": (d.get("shop") or {}).get("name") or shop_domain()}


@router.get("/check")
async def check():
    """Tries a tiny read from the store so the page can say 'connected' or explain what is wrong."""
    try:
        return await run_in_threadpool(_check)
    except ShopifyError as e:
        return {"ok": False, "mode": mode(), "shop": "", "message": str(e)}
