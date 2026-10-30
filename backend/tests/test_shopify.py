# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownLambdaType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportMissingParameterType=false

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from app import shopify as sh


@pytest.fixture(autouse=True)
def demo_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for k in ("SHOPIFY_SHOP", "SHOPIFY_STORE", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_CLIENT_ID",
              "SHOPIFY_CLIENT_SECRET", "SHOPIFY_DEMO"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(sh, "_dotenv", lambda: {})
    monkeypatch.setattr(sh, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sh, "BACKUP_FILE", tmp_path / "backups.jsonl")
    monkeypatch.setattr(sh, "DEMO_DB", sh._demo_nodes())
    sh._tok.update(value="", expires=0.0)


def test_strip_html_keeps_paragraphs() -> None:
    assert sh.strip_html("<p>Soft &amp; light</p><p>Second<br>line</p>") == "Soft & light\n\nSecond\nline"
    assert sh.strip_html(None) == ""
    assert sh.strip_html("<p></p>") == ""


def test_text_to_html_escapes_and_splits() -> None:
    assert sh.text_to_html("A <b> & B\n\nSecond") == "<p>A &lt;b&gt; &amp; B</p><p>Second</p>"


def test_merge_tags_never_drops_existing() -> None:
    assert sh.merge_tags(["Women", "shirt"], ["shirt", "Blue", "women", " "]) == ["Women", "shirt", "Blue"]


def test_shape_builds_attributes_and_skips_default_title() -> None:
    node: dict[str, Any] = {"id": "gid://shopify/Product/1", "title": "T", "vendor": "V", "productType": "Shirts", "tags": ["a"],
            "descriptionHtml": "<p>Hi</p>", "status": "ACTIVE",
            "options": [{"name": "Title", "values": ["Default Title"]},
                        {"name": "Size", "values": ["S", "M"]}, {"name": "Colour", "values": ["Blue"]}],
            "featuredMedia": {"preview": {"image": {"url": "https://cdn.shopify.com/x.jpg", "altText": "alt"}}},
            "seo": {"title": None, "description": None}}
    p = sh.shape(node)
    assert p["attributes"] == {"Size": "S, M", "Colour": "Blue"}
    assert p["image_url"] == "https://cdn.shopify.com/x.jpg"
    assert p["input"]["existing_description"] == "Hi"
    assert p["input"]["product_type"] == "Shirts"
    assert p["seo_title"] == ""


def test_shape_handles_missing_image_and_empty_description() -> None:
    node: dict[str, Any] = {"id": "x", "title": "T", "options": [], "featuredMedia": None, "descriptionHtml": ""}
    p: dict[str, Any] = sh.shape(node)
    assert p["image_url"] is None and p["input"]["existing_description"] is None


def test_mode_demo_until_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sh.mode() == "demo"
    monkeypatch.setenv("SHOPIFY_SHOP", "https://my-store.myshopify.com/")
    assert sh.mode() == "demo"  # shop alone is not enough
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_x")
    assert sh.mode() == "live" and sh.shop_domain() == "my-store"
    monkeypatch.setenv("SHOPIFY_DEMO", "1")
    assert sh.mode() == "demo"


def test_mode_live_with_client_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret")
    assert sh.mode() == "live"


def test_client_credentials_token_is_cached_and_refreshed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret")
    calls: list[tuple[str, Any]] = []

    def fake_http(url: str, data: Optional[bytes] = None, headers: Optional[dict[str, str]] = None, timeout: int = 30) -> bytes:
        calls.append((url, data))
        return json.dumps({"access_token": f"tok{len(calls)}", "expires_in": 86399}).encode()

    monkeypatch.setattr(sh, "_http", fake_http)
    assert sh.get_token() == "tok1"
    assert sh.get_token() == "tok1"
    assert len(calls) == 1
    assert calls[0][0] == "https://abc.myshopify.com/admin/oauth/access_token"
    assert b"grant_type=client_credentials" in calls[0][1]
    assert sh.get_token(force=True) == "tok2"


def test_gql_refreshes_token_once_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret")
    state: dict[str, int] = {"graphql": 0, "tokens": 0}

    def fake_http(url: str, data: Optional[bytes] = None, headers: Optional[dict[str, str]] = None, timeout: int = 30) -> bytes:
        if "oauth" in url:
            state["tokens"] += 1
            return json.dumps({"access_token": f"t{state['tokens']}", "expires_in": 86399}).encode()
        state["graphql"] += 1
        if state["graphql"] == 1:
            raise sh.ShopifyError("expired", status=401)
        assert headers is not None and headers["X-Shopify-Access-Token"] == "t2"
        return json.dumps({"data": {"ok": True}}).encode()

    monkeypatch.setattr(sh, "_http", fake_http)
    assert sh.gql("query { x }") == {"ok": True}
    assert state == {"graphql": 2, "tokens": 2}


def test_gql_reports_graphql_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "t")
    monkeypatch.setattr(sh, "_http", lambda *a, **k: json.dumps({"errors": [{"message": "Access denied for products"}]}).encode())
    with pytest.raises(sh.ShopifyError, match="Access denied"):
        sh.gql("query { x }")


def test_demo_products_search_and_shape() -> None:
    rows, nxt = sh.fetch_products("", None)
    assert nxt is None and len(rows) == 6
    shirt = rows[0]
    assert shirt["title"].startswith("METRONAUT") and shirt["attributes"]["Size"] == "S, M, L, XL"
    rows, _ = sh.fetch_products("kadai", None)
    assert [r["title"] for r in rows] == ["Stainless Steel Kadai"]


def test_save_replaces_description_merges_tags_and_can_undo() -> None:
    pid = "demo-1"
    res = sh._save(sh.SaveRequest(id=pid, description="A shirt.\n\nIn blue.", tags=["Blue", "women"],
                                  seo_title="Blue shirt"))
    p = res["product"]
    assert p["existing_description"] == "A shirt.\n\nIn blue."
    assert p["tags"] == ["women", "shirt", "Blue"]
    assert p["seo_title"] == "Blue shirt"
    undone = sh._undo(sh.UndoRequest(backup_id=res["backup_id"]))["product"]
    assert undone["existing_description"] == "" and undone["tags"] == ["women", "shirt"] and undone["seo_title"] == ""


def test_save_with_nothing_is_an_error() -> None:
    with pytest.raises(sh.ShopifyError):
        sh._save(sh.SaveRequest(id="demo-1"))


def test_undo_unknown_backup() -> None:
    with pytest.raises(sh.ShopifyError):
        sh._undo(sh.UndoRequest(backup_id="nope"))


def test_live_save_rejects_bad_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "t")
    with pytest.raises(sh.ShopifyError):
        sh._save(sh.SaveRequest(id="../../etc", description="x"))


def test_live_update_sends_product_update_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "t")
    seen: dict[str, Any] = {}
    node: dict[str, Any] = {"id": "gid://shopify/Product/9", "title": "T", "tags": ["x"], "descriptionHtml": "", "options": [],
                              "seo": {"title": "", "description": ""}}

    def fake_gql(query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if "productUpdate" in query:
            assert variables is not None
            seen["vars"] = variables
            description_html: str = variables["product"].get("descriptionHtml", "")
            return {"productUpdate": {"product": {**node, "descriptionHtml": description_html}, "userErrors": []}}
        return {"product": node}

    monkeypatch.setattr(sh, "gql", fake_gql)
    result = sh._save(sh.SaveRequest(id="gid://shopify/Product/9", description="Hello"))
    product: Optional[dict[str, Any]] = result.get("product")
    assert isinstance(product, dict)
    assert seen["vars"]["product"] == {"id": "gid://shopify/Product/9", "descriptionHtml": "<p>Hello</p>"}
    assert product.get("existing_description") == "Hello"


def test_live_user_errors_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "t")
    node: dict[str, Any] = {"id": "gid://shopify/Product/9", "title": "T", "tags": [], "descriptionHtml": "", "options": [], "seo": {}}

    def fake_gql(query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if "productUpdate" in query:
            return {"productUpdate": {"product": None, "userErrors": [{"message": "Title can't be blank"}]}}
        return {"product": node}

    monkeypatch.setattr(sh, "gql", fake_gql)
    with pytest.raises(sh.ShopifyError, match="Title can't be blank"):
        sh._save(sh.SaveRequest(id="gid://shopify/Product/9", title="x"))


def test_caption_only_reads_shopify_photos() -> None:
    with pytest.raises(sh.ShopifyError):
        sh._caption(sh.CaptionRequest(image_url="https://cdn.shopify.com/a.jpg"))  # demo mode


def test_caption_blocks_other_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "t")
    for bad in ("http://cdn.shopify.com/a.jpg", "https://evil.example/a.jpg", "https://cdn.shopify.com.evil.io/a.jpg",
                "http://169.254.169.254/latest"):
        with pytest.raises(sh.ShopifyError):
            sh._caption(sh.CaptionRequest(image_url=bad))


def test_caption_calls_ollama_native_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "t")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma3:4b")
    calls: list[str] = []

    def fake_http(url: str, data: Optional[bytes] = None, headers: Optional[dict[str, str]] = None, timeout: int = 30) -> bytes:
        calls.append(url)
        if url.startswith("https://cdn.shopify.com"):
            return b"\x89PNG"
        assert data is not None
        body: dict[str, Any] = json.loads(data)
        assert body["model"] == "gemma3:4b"
        assert body["messages"][0]["images"]
        return json.dumps({"message": {"content": "A blue printed shirt.\n"}}).encode()

    monkeypatch.setattr(sh, "_http", fake_http)
    out = sh._caption(sh.CaptionRequest(image_url="https://cdn.shopify.com/s/files/a.jpg?v=1"))
    assert out == {"caption": "A blue printed shirt."}
    assert "width=768" in calls[0] and "v=1" in calls[0]
    assert calls[1] == "http://localhost:11434/api/chat"


def test_http_endpoints_in_demo_mode() -> None:
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(sh.router)
    c = TestClient(app)
    assert c.get("/shopify/status").json()["mode"] == "demo"
    prods = c.get("/shopify/products").json()
    assert len(prods["products"]) == 6 and prods["next"] is None
    r = c.post("/shopify/save", json={"id": "demo-2", "description": "Steel kadai."})
    assert r.status_code == 200
    bid = r.json()["backup_id"]
    assert c.post("/shopify/undo", json={"backup_id": bid}).json()["ok"] is True
    assert c.post("/shopify/save", json={"id": "demo-2"}).status_code == 400
    assert c.post("/shopify/save", json={"id": "demo-999", "description": "x"}).status_code == 404


def test_check_reports_demo_then_live_then_error(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sh._check()["ok"] is False
    monkeypatch.setenv("SHOPIFY_SHOP", "abc")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "t")

    def fake_gql_ok(q: str, v: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {"shop": {"name": "Neha's Kitchen"}, "products": {"nodes": []}}

    monkeypatch.setattr(sh, "gql", fake_gql_ok)
    assert sh._check() == {"ok": True, "mode": "live", "shop": "Neha's Kitchen"}

    def bad(q: str, v: Optional[dict[str, Any]] = None) -> None:
        raise sh.ShopifyError("Shopify rejected the access.", status=401)

    monkeypatch.setattr(sh, "gql", bad)
    with pytest.raises(sh.ShopifyError):
        sh._check()
