"""Duplicate-upload detection and reprocessing of failed documents.

Object storage and the task queue are stubbed: what's under test is the
decision the endpoint makes (store + enqueue, or reuse; reprocess or refuse),
not MinIO or Celery.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


@pytest.fixture
def side_effects(monkeypatch):
    """Record storage writes and enqueued ingestions instead of performing them."""
    from app.api.v1.endpoints import documents as endpoint
    from app.core.config import settings

    calls: dict[str, list[str]] = {"stored": [], "enqueued": []}

    async def fake_upload(content, object_name, content_type=None):
        calls["stored"].append(object_name)
        return True

    class FakeTask:
        @staticmethod
        def delay(document_id):
            calls["enqueued"].append(document_id)

    monkeypatch.setattr(endpoint.storage, "upload_file", fake_upload)
    monkeypatch.setattr(endpoint, "process_document", FakeTask)
    monkeypatch.setattr(settings, "INGEST_INLINE", False, raising=False)
    return calls


async def _upload(client, headers, name="handbook.txt", body=b"Refunds within 30 days."):
    return await client.post(
        "/api/v1/documents/upload", files={"file": (name, body, "text/plain")}, headers=headers
    )


async def _set_status(db, doc_id, status):
    from app.crud.crud_document import document as crud_document
    from app.schemas.document import DocumentUpdate

    doc = await crud_document.get(db, id=uuid.UUID(doc_id))
    await crud_document.update(db, db_obj=doc, obj_in=DocumentUpdate(status=status))


class TestDuplicateUploads:
    async def test_identical_bytes_return_the_existing_document(
        self, client, side_effects, unique_email
    ):
        _, headers = await register_and_login(client, unique_email)

        first = await _upload(client, headers)
        assert first.status_code == 201
        assert first.json()["duplicate"] is False

        second = await _upload(client, headers, name="handbook-copy.txt")
        assert second.status_code == 200
        assert second.json()["duplicate"] is True
        assert second.json()["id"] == first.json()["id"]

        # Stored and indexed exactly once.
        assert len(side_effects["stored"]) == 1
        assert side_effects["enqueued"] == [first.json()["id"]]

        listed = (await client.get("/api/v1/documents/", headers=headers)).json()
        assert len(listed) == 1

    async def test_different_bytes_are_a_new_document(self, client, side_effects, unique_email):
        _, headers = await register_and_login(client, unique_email)

        a = await _upload(client, headers, body=b"version one")
        b = await _upload(client, headers, body=b"version two")
        assert a.status_code == b.status_code == 201
        assert a.json()["id"] != b.json()["id"]

    async def test_a_failed_copy_does_not_swallow_a_fresh_upload(
        self, client, db_session, side_effects, unique_email
    ):
        from app.models.document import DocumentStatus

        _, headers = await register_and_login(client, unique_email)
        first = await _upload(client, headers)
        await _set_status(db_session, first.json()["id"], DocumentStatus.FAILED)

        again = await _upload(client, headers)
        assert again.status_code == 201
        assert again.json()["id"] != first.json()["id"]

    async def test_duplicates_are_not_detected_across_organizations(
        self, client, side_effects, unique_email
    ):
        _, alice = await register_and_login(client, unique_email, organization_name="Initech")
        _, mallory = await register_and_login(
            client, f"mallory-{unique_email}", organization_name="Globex"
        )

        a = await _upload(client, alice)
        m = await _upload(client, mallory)
        # A hash match must never hand one tenant another tenant's document —
        # that would also leak that the file exists elsewhere.
        assert m.status_code == 201
        assert m.json()["id"] != a.json()["id"]


class TestReprocess:
    async def test_a_failed_document_is_requeued(
        self, client, db_session, side_effects, unique_email
    ):
        from app.models.document import DocumentStatus

        _, headers = await register_and_login(client, unique_email)
        doc_id = (await _upload(client, headers)).json()["id"]
        await _set_status(db_session, doc_id, DocumentStatus.FAILED)

        res = await client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "pending"
        assert res.json()["error_message"] is None
        assert side_effects["enqueued"] == [doc_id, doc_id]
        # Re-ingested from storage, not uploaded again.
        assert len(side_effects["stored"]) == 1

    async def test_a_document_that_is_not_failed_is_refused(
        self, client, side_effects, unique_email
    ):
        _, headers = await register_and_login(client, unique_email)
        doc_id = (await _upload(client, headers)).json()["id"]  # still pending

        res = await client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=headers)
        assert res.status_code == 409
        assert side_effects["enqueued"] == [doc_id]

    async def test_only_the_uploader_can_reprocess(
        self, client, db_session, side_effects, unique_email
    ):
        from app.models.document import DocumentStatus

        _, alice = await register_and_login(client, unique_email, organization_name="Initech")
        _, bob = await register_and_login(
            client, f"bob-{unique_email}", organization_name="Initech"
        )
        doc_id = (await _upload(client, alice)).json()["id"]
        await _set_status(db_session, doc_id, DocumentStatus.FAILED)

        res = await client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=bob)
        assert res.status_code == 403

    async def test_another_tenants_document_is_a_404(
        self, client, db_session, side_effects, unique_email
    ):
        from app.models.document import DocumentStatus

        _, alice = await register_and_login(client, unique_email, organization_name="Initech")
        _, mallory = await register_and_login(
            client, f"mallory-{unique_email}", organization_name="Globex"
        )
        doc_id = (await _upload(client, alice)).json()["id"]
        await _set_status(db_session, doc_id, DocumentStatus.FAILED)

        res = await client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=mallory)
        assert res.status_code == 404
