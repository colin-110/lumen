"""Auth behaviour that only a real database can demonstrate.

Each test here corresponds to a defect that shipped: organizations that never
matched between two users, a deactivated superuser who kept privileged
access, and JWTs that outlived the account they authenticated.
"""

from __future__ import annotations

import pytest

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


class TestOrganizationResolution:
    async def test_two_users_naming_the_same_organization_share_it(self, client, unique_email):
        """The whole tenant model rests on this.

        Registration used to create a new Organization unconditionally, so
        colleagues who both typed "Acme Corp" got different organization_ids
        and could not see each other's documents — making org-scoped sharing,
        which retrieval and the semantic cache are both built around,
        unreachable in production.
        """
        first, _ = await register_and_login(
            client, unique_email, organization_name="Shared Industries"
        )
        second, _ = await register_and_login(
            client, f"other-{unique_email}", organization_name="Shared Industries"
        )

        assert first["organization_id"] is not None
        assert first["organization_id"] == second["organization_id"]

    async def test_organization_matching_ignores_case_and_padding(self, client, unique_email):
        first, _ = await register_and_login(client, unique_email, organization_name="Acme Corp")
        second, _ = await register_and_login(
            client, f"other-{unique_email}", organization_name="  acme corp  "
        )
        assert first["organization_id"] == second["organization_id"]

    async def test_different_names_stay_separate(self, client, unique_email):
        first, _ = await register_and_login(client, unique_email, organization_name="Acme Corp")
        second, _ = await register_and_login(
            client, f"other-{unique_email}", organization_name="Globex"
        )
        assert first["organization_id"] != second["organization_id"]

    async def test_no_organization_name_means_no_organization(self, client, unique_email):
        user, _ = await register_and_login(client, unique_email)
        assert user["organization_id"] is None


class TestRegistrationGuards:
    async def test_duplicate_email_is_rejected(self, client, unique_email):
        await register_and_login(client, unique_email)
        res = await client.post(
            "/api/v1/auth/register", json={"email": unique_email, "password": "another-password"}
        )
        assert res.status_code == 409

    async def test_oversized_organization_name_is_rejected(self, client, unique_email):
        res = await client.post(
            "/api/v1/auth/register",
            json={
                "email": unique_email,
                "password": "correct-horse-battery",
                "organization_name": "x" * 300,
            },
        )
        assert res.status_code == 422


class TestTokenLifetime:
    async def test_deactivating_a_user_invalidates_their_existing_token(
        self, client, db_session, unique_email
    ):
        """`is_active=False` used to be cosmetic for the token's whole
        lifetime — up to 14 days for a refresh token."""
        from app.crud.crud_user import user as crud_user
        from app.schemas.user import UserUpdate

        user, headers = await register_and_login(client, unique_email)

        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

        db_user = await crud_user.get(db_session, id=user["id"])
        await crud_user.update(db_session, db_obj=db_user, obj_in=UserUpdate(is_active=False))

        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401

    async def test_changing_a_password_invalidates_existing_tokens(
        self, client, db_session, unique_email
    ):
        from app.crud.crud_user import user as crud_user
        from app.schemas.user import UserUpdate

        user, headers = await register_and_login(client, unique_email)
        db_user = await crud_user.get(db_session, id=user["id"])
        await crud_user.update(
            db_session, db_obj=db_user, obj_in=UserUpdate(password="a-brand-new-password")
        )

        assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401

    async def test_a_deactivated_superuser_cannot_reach_the_debug_endpoint(
        self, client, db_session, unique_email
    ):
        """get_current_active_superuser chained off get_current_user, not
        get_current_active_user, so being inactive did not block a superuser
        from an endpoint that returns system prompts and raw document text."""
        from app.crud.crud_user import user as crud_user

        user, headers = await register_and_login(client, unique_email)

        db_user = await crud_user.get(db_session, id=user["id"])
        db_user.is_superuser = True
        db_user.is_active = False
        db_session.add(db_user)
        await db_session.commit()

        res = await client.post("/api/v1/debug/retrieval", json={"message": "hello"}, headers=headers)
        assert res.status_code in (400, 401), res.text
        assert res.status_code != 200

    async def test_refresh_rejects_a_malformed_subject(self, client):
        from app.core.security import TokenType, _create_token
        from datetime import timedelta

        forged = _create_token("not-a-uuid", TokenType.REFRESH, timedelta(minutes=5))
        res = await client.post("/api/v1/auth/refresh", json={"refresh_token": forged})
        assert res.status_code == 401

    async def test_an_access_token_is_not_accepted_as_a_refresh_token(self, client, unique_email):
        password = "correct-horse-battery"
        await register_and_login(client, unique_email, password=password)
        tokens = (
            await client.post(
                "/api/v1/auth/login", data={"username": unique_email, "password": password}
            )
        ).json()

        res = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
        )
        assert res.status_code == 401

    async def test_refresh_returns_a_usable_access_token(self, client, unique_email):
        password = "correct-horse-battery"
        await register_and_login(client, unique_email, password=password)
        tokens = (
            await client.post(
                "/api/v1/auth/login", data={"username": unique_email, "password": password}
            )
        ).json()

        res = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert res.status_code == 200
        refreshed = res.json()

        me = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {refreshed['access_token']}"}
        )
        assert me.status_code == 200
