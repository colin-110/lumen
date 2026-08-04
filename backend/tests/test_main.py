"""Smoke tests that don't require a live database/Qdrant/Redis — just that
the app assembles correctly and the unauthenticated routes behave."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_openapi_schema_loads():
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/auth/login" in schema["paths"]
    assert "/api/v1/chat/stream" in schema["paths"]


def test_chat_requires_auth():
    response = client.post("/api/v1/chat/", json={"message": "hello"})
    assert response.status_code == 401


def test_upload_requires_auth():
    response = client.post("/api/v1/documents/upload")
    assert response.status_code in (401, 422)
