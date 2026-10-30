# pyright: reportUnknownLambdaType=false
# pyright: reportUnknownMemberType=false
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.service as service
from app.main import app

TestClient.__test__ = False  # type: ignore[attr-defined]
client = TestClient(app)
BODY: dict[str, Any] = {
    "product": {"title": "Women Red Maxi Dress", "attributes": {"color": "red"}},
    "options": {"category": "fashion", "paragraphs": 2},
    "fields": ["description", "seo_title", "tags"],
}


def test_generate_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    good = json.dumps({"description": "A.\n\nB.", "seo_title": "Red Maxi Dress", "tags": ["dress", "red"]})

    def fake_chat(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        return good, "fake:model"

    monkeypatch.setattr(service, "chat", fake_chat)
    r = client.post("/generate", json=BODY)
    assert r.status_code == 200 and r.json()["provider"] == "fake:model" and r.json()["warnings"] == []


def test_generate_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = json.dumps({"description": "A.\n\nB.", "seo_title": "x" * 80, "tags": ["a"]})
    good = json.dumps({"description": "A.\n\nB.", "seo_title": "Short", "tags": ["a"]})
    replies = iter([bad, good])

    def fake_chat(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        return next(replies), "fake:model"

    monkeypatch.setattr(service, "chat", fake_chat)
    assert client.post("/generate", json=BODY).json()["result"]["seo_title"] == "Short"


def test_invented_details_are_rejected_then_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = json.dumps({"description": "Made of breathable fabric.\n\nHand wash only.", "seo_title": "Dress", "tags": ["breathable"]})
    good = json.dumps({"description": "A red maxi dress.\n\nFull length.", "seo_title": "Dress", "tags": ["red"]})
    replies = iter([bad, good])

    def fake_chat(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        return next(replies), "fake:model"

    monkeypatch.setattr(service, "chat", fake_chat)
    r = client.post("/generate", json=BODY).json()
    assert "breathable" not in r["result"]["description"] and r["warnings"] == []


def test_auto_category_for_a_book(monkeypatch: pytest.MonkeyPatch) -> None:
    body: dict[str, Any] = {
        "product": {"title": "The Lost River Paperback Novel"},
        "fields": ["description"],
        "options": {"paragraphs": 1},
    }
    bad = json.dumps({"description": "Written by a famous author, 320 pages."})
    good = json.dumps({"description": "A paperback novel titled The Lost River."})
    replies = iter([bad, good])

    def fake_chat(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        return next(replies), "fake:model"

    monkeypatch.setattr(service, "chat", fake_chat)
    r = client.post("/generate", json=body).json()
    assert "author" not in r["result"]["description"] and r["warnings"] == []


def test_root_redirects_to_ui() -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/ui"


def test_int_attributes_accepted_and_generate_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    good = json.dumps({"description": "Wooden blocks set of 50."})

    def fake_chat(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        return good, "fake:model"

    monkeypatch.setattr(service, "chat", fake_chat)
    body: dict[str, Any] = {
        "product": {"title": "Wooden Blocks", "attributes": {"pieces": 50}},
        "fields": ["description"],
    }
    r = client.post("/generate", json=body)
    assert r.status_code == 200


def test_retry_survives_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    # First attempt: valid JSON with bad tag. Second attempt: broken JSON.
    bad_first = json.dumps({"description": "Dress.", "tags": ["unsupported-xyz"]})
    broken_second = "Not json at all"
    replies = iter([bad_first, broken_second, broken_second])

    def fake_chat(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        return next(replies), "fake:model"

    monkeypatch.setattr(service, "chat", fake_chat)
    r = client.post("/generate", json=BODY)
    assert r.status_code == 200
    assert "description" in r.json()["result"]


def test_model_omits_tags_gets_grounded_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Model generates description but omits tags completely
    no_tags = json.dumps({"description": "A women's red maxi dress."})

    def fake_chat(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        return no_tags, "fake:model"

    monkeypatch.setattr(service, "chat", fake_chat)
    r = client.post("/generate", json=BODY)
    assert r.status_code == 200
    res: dict[str, Any] = r.json()["result"]
    assert "tags" in res and len(res["tags"]) > 0
    assert all(t in "women red maxi dress color" for t in res["tags"])
