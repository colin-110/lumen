"""Document visibility, and whether it agrees with retrieval's boundary.

The documents API scoped by `owner_id` while `retrieval._tenant_filter`
scoped by `organization_id`. Both were individually defensible and together
incoherent: chat cited documents — filename and a 600-character snippet —
that the same user got a 404 for. Rows are created through the CRUD layer so
these tests need no object storage or Qdrant.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


async def _make_document(db, owner_id, organization_id, filename="contract.pdf"):
    from app.crud.crud_document import document as crud_document
    from app.models.document import DocumentStatus
    from app.schemas.document import DocumentCreate

    return await crud_document.create(
        db,
        obj_in=DocumentCreate(
            id=uuid.uuid4(),
            filename=filename,
            file_type="application/pdf",
            file_size=1024,
            storage_key=f"{organization_id or owner_id}/{uuid.uuid4()}/{filename}",
            owner_id=uuid.UUID(str(owner_id)),
            organization_id=uuid.UUID(str(organization_id)) if organization_id else None,
            status=DocumentStatus.COMPLETED,
        ),
    )


class TestOrganizationVisibility:
    async def test_a_colleagues_document_is_listed(self, client, db_session, unique_email):
        alice, alice_headers = await register_and_login(
            client, unique_email, organization_name="Initech"
        )
        bob, bob_headers = await register_and_login(
            client, f"bob-{unique_email}", organization_name="Initech"
        )
        assert alice["organization_id"] == bob["organization_id"]

        doc = await _make_document(db_session, alice["id"], alice["organization_id"])

        listed = (await client.get("/api/v1/documents/", headers=bob_headers)).json()
        assert [d["id"] for d in listed] == [str(doc.id)]

    async def test_a_colleagues_document_is_fetchable(self, client, db_session, unique_email):
        alice, _ = await register_and_login(client, unique_email, organization_name="Initech")
        _, bob_headers = await register_and_login(
            client, f"bob-{unique_email}", organization_name="Initech"
        )
        doc = await _make_document(db_session, alice["id"], alice["organization_id"])

        res = await client.get(f"/api/v1/documents/{doc.id}", headers=bob_headers)
        assert res.status_code == 200

    async def test_another_organization_sees_nothing(self, client, db_session, unique_email):
        alice, _ = await register_and_login(client, unique_email, organization_name="Initech")
        _, outsider_headers = await register_and_login(
            client, f"out-{unique_email}", organization_name="Globex"
        )
        doc = await _make_document(db_session, alice["id"], alice["organization_id"])

        assert (await client.get("/api/v1/documents/", headers=outsider_headers)).json() == []
        res = await client.get(f"/api/v1/documents/{doc.id}", headers=outsider_headers)
        assert res.status_code == 404

    async def test_a_user_without_an_organization_sees_only_their_own(
        self, client, db_session, unique_email
    ):
        solo, solo_headers = await register_and_login(client, unique_email)
        other, _ = await register_and_login(client, f"other-{unique_email}")
        assert solo["organization_id"] is None

        mine = await _make_document(db_session, solo["id"], None, filename="mine.pdf")
        await _make_document(db_session, other["id"], None, filename="theirs.pdf")

        listed = (await client.get("/api/v1/documents/", headers=solo_headers)).json()
        assert [d["id"] for d in listed] == [str(mine.id)]


class TestDeletionOwnership:
    async def test_a_colleague_cannot_delete_someone_elses_document(
        self, client, db_session, unique_email
    ):
        """Visible to the organization, deletable only by its owner. 403 and
        not 404, because the document is demonstrably visible to this user."""
        alice, _ = await register_and_login(client, unique_email, organization_name="Initech")
        _, bob_headers = await register_and_login(
            client, f"bob-{unique_email}", organization_name="Initech"
        )
        doc = await _make_document(db_session, alice["id"], alice["organization_id"])

        res = await client.delete(f"/api/v1/documents/{doc.id}", headers=bob_headers)
        assert res.status_code == 403

        still_there = await client.get(f"/api/v1/documents/{doc.id}", headers=bob_headers)
        assert still_there.status_code == 200

    async def test_an_outsider_gets_a_404_not_a_403(self, client, db_session, unique_email):
        """A 403 would confirm the document exists to someone with no reason
        to know that."""
        alice, _ = await register_and_login(client, unique_email, organization_name="Initech")
        _, outsider_headers = await register_and_login(
            client, f"out-{unique_email}", organization_name="Globex"
        )
        doc = await _make_document(db_session, alice["id"], alice["organization_id"])

        res = await client.delete(f"/api/v1/documents/{doc.id}", headers=outsider_headers)
        assert res.status_code == 404


class TestUploadValidation:
    async def test_an_unsupported_extension_is_rejected(self, client, unique_email):
        _, headers = await register_and_login(client, unique_email)
        res = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("payload.exe", b"MZ\x00\x00", "application/octet-stream")},
            headers=headers,
        )
        assert res.status_code == 415

    async def test_an_empty_file_is_rejected(self, client, unique_email):
        _, headers = await register_and_login(client, unique_email)
        res = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
            headers=headers,
        )
        assert res.status_code == 400

    async def test_an_oversized_upload_is_rejected_by_declared_length(
        self, client, monkeypatch, unique_email
    ):
        """Rejected on Content-Length, before the body is buffered to disk."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 1024, raising=False)
        _, headers = await register_and_login(client, unique_email)

        res = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("big.txt", b"x" * 5000, "text/plain")},
            headers=headers,
        )
        assert res.status_code == 413
