# pyright: reportUnknownMemberType=false
import base64
import json
from typing import Any, Callable

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from app import quick, service
from app.main import app
from app.vision import VisionError

client = TestClient(app)
TEXT = "Insulated stainless steel water bottle, 750 ml, keeps drinks cold 24 hours, leak-proof lid, 5 colors"


def fake_model(
    reply: dict[str, str],
    seen: list[list[dict[str, str]]] | None = None,
) -> Callable[..., tuple[str, str]]:
    def chat(
        messages: list[dict[str, str]],
        temperature: float = 0.4,
        max_tokens: int = 700,
    ) -> tuple[str, str]:
        if seen is not None:
            seen.append(messages)
        return json.dumps(reply), "ollama:fake"
    return chat


def test_needs_something_to_write_about() -> None:
    r = client.post("/quick/generate", json={})
    assert r.status_code == 422 and "Describe your product" in r.json()["detail"]


def test_build_request_maps_free_text() -> None:
    req = quick.QuickRequest(
        name="",
        description=TEXT,
        image=None,
        keywords="water bottle, gym bottle",
    )
    g = quick.build_request(req, caption="")
    assert g.product.title.startswith("Insulated stainless steel water bottle")
    assert g.product.existing_description == TEXT
    assert g.product.attributes == {"search keywords": "water bottle, gym bottle"}
    assert g.options.category != "auto"


def test_name_wins_over_derived_title() -> None:
    g = quick.build_request(
        quick.QuickRequest(
            name="ColdCap 750", description=TEXT, keywords="", image=None
        ),
        "",
    )
    assert g.product.title == "ColdCap 750"


def test_end_to_end_keeps_supported_text_and_drops_invented(monkeypatch: pytest.MonkeyPatch) -> None:
    reply: dict[str, str] = {
        "description": "This 750 ml insulated stainless steel bottle keeps drinks cold for 24 hours. "
                        "It holds 1000 ml of premium water and comes in 5 colors."
    }
    monkeypatch.setattr(service, "chat", fake_model(reply))
    r = client.post("/quick/generate", json={"description": TEXT})
    assert r.status_code == 200
    d: str = r.json()["result"]["description"]
    assert "750 ml" in d and "24 hours" in d
    assert "1000" not in d and "premium" not in d.lower()
    assert r.json()["warnings"]


def test_prompt_tells_model_to_use_every_fact(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[dict[str, str]]] = []
    monkeypatch.setattr(service, "chat", fake_model({"description": "A 750 ml bottle."}, seen))
    client.post("/quick/generate", json={"description": TEXT})
    assert "EVERY fact" in seen[0][0]["content"]


def test_photo_caption_is_used_and_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[dict[str, str]]] = []
    monkeypatch.setattr(service, "chat", fake_model({"description": "A blue printed shirt."}, seen))

    def fake_caption(img: bytes) -> str:
        return "A blue printed shirt."

    monkeypatch.setattr(quick, "caption_bytes", fake_caption)
    img = "data:image/jpeg;base64," + base64.b64encode(b"fakejpeg").decode()
    r = client.post("/quick/generate", json={"image": img})
    assert r.status_code == 200
    assert r.json()["photo_note"] == "A blue printed shirt."
    assert "A blue printed shirt." in seen[0][1]["content"]


def test_photo_failure_does_not_block_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "chat", fake_model({"description": "A 750 ml bottle."}))

    def boom(img: bytes) -> None:
        raise VisionError("could not read")

    monkeypatch.setattr(quick, "caption_bytes", boom)
    img = base64.b64encode(b"x").decode()
    r = client.post("/quick/generate", json={"description": TEXT, "image": img})
    assert r.status_code == 200 and r.json()["photo_error"] == "could not read"


def test_photo_only_failure_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(img: bytes) -> None:
        raise VisionError("could not read")

    monkeypatch.setattr(quick, "caption_bytes", boom)
    r = client.post("/quick/generate", json={"image": base64.b64encode(b"x").decode()})
    assert r.status_code == 422


def test_new_tones_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "chat", fake_model({"description": "A 750 ml bottle."}))
    for tone in ("casual", "persuasive", "simple"):
        r = client.post("/quick/generate", json={"description": TEXT, "options": {"tone": tone}})
        assert r.status_code == 200
