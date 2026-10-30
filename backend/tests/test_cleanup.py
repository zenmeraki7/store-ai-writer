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


def test_stubborn_model_output_is_cleaned_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = json.dumps({"description": "50 wooden blocks for play. Perfect for children to build.", "tags": ["toys", "children"]})

    def fake_chat(_message: list[dict[str, str]], **_kwargs: object) -> tuple[str, str]:
        return bad, "fake:model"

    monkeypatch.setattr(service, "chat", fake_chat)  # model never improves
    body: dict[str, Any] = {
        "product": {"title": "Wooden Building Blocks Toy", "attributes": {"material": "wood", "pieces": "50"}},
        "options": {"category": "auto", "paragraphs": 1},
        "fields": ["description", "tags"],
    }
    r = client.post("/generate", json=body).json()
    assert "children" not in r["result"]["description"] and "children" not in r["result"]["tags"]
    assert any("Removed" in w for w in r["warnings"])
