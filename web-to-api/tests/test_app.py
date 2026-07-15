from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel

from web_to_api.app import create_app
from web_to_api.settings import Settings


def test_service_routes_are_registered_before_chat_mount(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path), model=TestModel())

    with TestClient(app) as client:
        response = client.get("/healthz")
        docs = client.get("/docs")
        missing = client.get("/api/projects/not-found")

    assert response.json() == {"status": "ok"}
    assert docs.status_code == 200
    assert missing.status_code == 404
