"""Manual end-to-end smoke script — not a pytest test (pytest is scoped to
`tests/` via `testpaths` in pyproject.toml). Run against a fully running
stack with: `python scripts/test_upload.py`.
"""

from __future__ import annotations

import time

import requests

API_URL = "http://127.0.0.1:8000/api/v1"
HEALTH_URL = "http://127.0.0.1:8000/health"

SEED_EMAIL = "admin@enterprise.ai"
SEED_PASSWORD = "admin12345"


def run_flow() -> None:
    print("1. Checking API health...")
    try:
        response = requests.get(HEALTH_URL, timeout=5)
        print(f"   status={response.status_code} body={response.json()}")
    except requests.exceptions.ConnectionError:
        print("   API is not reachable. Is the backend running?")
        return

    print("2. Logging in as the seeded admin...")
    response = requests.post(
        f"{API_URL}/auth/login",
        data={"username": SEED_EMAIL, "password": SEED_PASSWORD},
        timeout=10,
    )
    if response.status_code != 200:
        print(f"   Auth failed: {response.status_code} {response.text}")
        print("   Did you run `python scripts/seed.py` first?")
        return

    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("   Logged in.")

    print("3. Uploading a test document...")
    content = (
        b"This is a highly confidential document about Project Zeta. "
        b"Project Zeta's launch date is December 2029."
    )
    files = {"file": ("project_zeta.txt", content, "text/plain")}
    res = requests.post(f"{API_URL}/documents/upload", headers=headers, files=files, timeout=20)
    print(f"   status={res.status_code}")
    if res.status_code != 201:
        print(f"   Upload failed: {res.text}")
        return
    doc_id = res.json()["id"]
    print(f"   Uploaded document {doc_id}")

    print("4. Waiting for ingestion to complete...")
    for _ in range(30):
        res = requests.get(f"{API_URL}/documents/{doc_id}", headers=headers, timeout=10)
        status = res.json().get("status")
        print(f"   status={status}")
        if status in ("completed", "failed"):
            break
        time.sleep(2)

    print("5. Asking Lumen about the document...")
    chat_res = requests.post(
        f"{API_URL}/chat/",
        headers=headers,
        json={"message": "When is the launch date for Project Zeta?"},
        timeout=60,
    )
    print(f"   status={chat_res.status_code}")
    if chat_res.status_code == 200:
        data = chat_res.json()
        print(f"   AI response: {data['message']}")
        print(f"   sources: {[s['filename'] for s in data['sources']]}")
    else:
        print(f"   Chat error: {chat_res.text}")


if __name__ == "__main__":
    run_flow()
