import json

import pytest

from app import linkreader as lr

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from app import quick
from app.main import app

LD = {"@context": "https://schema.org", "@graph": [{"@type": "Product", "name": "VeBNoR Men Solid Formal Blue Shirt",
      "description": "A solid blue formal shirt.", "brand": {"@type": "Brand", "name": "VeBNoR"}, "color": "Blue",
      "image": ["/img/shirt.jpg"]}]}
PAGE = f'<html><head><script type="application/ld+json">{json.dumps(LD)}</script></head></html>'


def test_parse_reads_product_data_from_json_ld():
    p = lr.parse_product(PAGE, "https://shop.example/p/1")
    assert p["name"] == "VeBNoR Men Solid Formal Blue Shirt"
    assert "A solid blue formal shirt." in p["description"] and "Brand: VeBNoR" in p["description"] and "Colour: Blue" in p["description"]
    assert p["image_url"] == "https://shop.example/img/shirt.jpg"


def test_parse_falls_back_to_open_graph_and_cleans_marketplace_title():
    htm = ('<meta property="og:title" content="Blue Shirt - Buy Blue Shirt Online at Best Prices | Flipkart.com">'
           "<meta property='og:description' content='Formal fit.'><meta property=\"og:image\" content=\"https://c.example/a.jpg\">")
    p = lr.parse_product(htm, "https://x.example/")
    assert p["name"] == "Blue Shirt" and p["description"] == "Formal fit." and p["image_url"] == "https://c.example/a.jpg"


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "ftp://a.example/x", "http://127.0.0.1/x", "http://10.0.0.5/x",
                                 "http://169.254.169.254/latest", "https://example.com:8080/x", "not a link", ""])
def test_unsafe_or_invalid_links_are_refused(bad):
    with pytest.raises(lr.LinkError):
        lr.check_url(bad)


def test_read_link_returns_fields_and_embeds_photo(monkeypatch):
    def fake_get(url, limit, accept):
        if accept.startswith("image"):
            return b"\xff\xd8jpeg", "image/jpeg", "utf-8", url
        return PAGE.encode(), "text/html", "utf-8", "https://shop.example/p/1"
    monkeypatch.setattr(lr, "_get", fake_get)
    out = lr.read_link("https://shop.example/p/1")
    assert out["name"].startswith("VeBNoR") and out["image"].startswith("data:image/jpeg;base64,") and out["source"] == "shop.example"


def test_read_link_without_product_data_is_an_error(monkeypatch):
    monkeypatch.setattr(lr, "_get", lambda u, l, a: (b"<html></html>", "text/html", "utf-8", u))
    with pytest.raises(lr.LinkError):
        lr.read_link("https://shop.example/")


def test_endpoint_maps_errors_to_422(monkeypatch):
    c = TestClient(app)
    assert c.post("/quick/link", json={"url": "http://127.0.0.1/x"}).status_code == 422
    monkeypatch.setattr(quick, "read_link", lambda u: {"name": "A", "description": "", "image": "", "source": "x"})
    assert c.post("/quick/link", json={"url": "https://x.example"}).json()["name"] == "A"
