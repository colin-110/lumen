"""The refuse-to-boot guard on development credentials.

Every insecure default in this app is deliberate — a fresh clone has to work
with no configuration. The failure mode is that the same values reach a real
deployment, where nothing else in the system would ever notice that the JWT
signing key is the one published in .env.example.
"""

from __future__ import annotations

import pytest

from app.core.config import INSECURE_SECRET_KEY, INSECURE_SUPERUSER_PASSWORD, Settings

SAFE = {
    "SECRET_KEY": "a" * 48,
    "FIRST_SUPERUSER_PASSWORD": "a-real-password-from-the-vault",
    "ALLOW_OPEN_REGISTRATION": False,
    "POSTGRES_PASSWORD": "not-the-default",
    "S3_SECRET_KEY": "not-the-default",
    "METRICS_TOKEN": "scrape-token",
}


def _settings(environment: str, **overrides) -> Settings:
    return Settings(ENVIRONMENT=environment, **{**SAFE, **overrides})


class TestLocalStaysPermissive:
    def test_local_boots_with_every_default(self):
        """Every insecure default present at once, and `local` still starts.

        The values are passed explicitly rather than left to defaults: init
        arguments outrank both the environment and the .env file in
        pydantic-settings, so this asserts the same thing whether or not the
        surrounding shell happens to export SECRET_KEY — which CI does.
        """
        s = Settings(
            ENVIRONMENT="local",
            SECRET_KEY=INSECURE_SECRET_KEY,
            FIRST_SUPERUSER_PASSWORD=INSECURE_SUPERUSER_PASSWORD,
            ALLOW_OPEN_REGISTRATION=True,
            POSTGRES_PASSWORD="postgres",
            S3_SECRET_KEY="minioadmin",
            METRICS_TOKEN=None,
        )
        assert s.SECRET_KEY == INSECURE_SECRET_KEY
        assert s.DEBUG is True


class TestProductionRefusesInsecureDefaults:
    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_the_published_secret_key_is_refused(self, environment):
        with pytest.raises(ValueError, match="SECRET_KEY"):
            _settings(environment, SECRET_KEY=INSECURE_SECRET_KEY)

    def test_a_short_secret_key_is_refused(self):
        with pytest.raises(ValueError, match="at least 32"):
            _settings("production", SECRET_KEY="too-short")

    def test_the_default_superuser_password_is_refused(self):
        with pytest.raises(ValueError, match="FIRST_SUPERUSER_PASSWORD"):
            _settings("production", FIRST_SUPERUSER_PASSWORD="admin12345")

    def test_open_registration_is_refused(self):
        with pytest.raises(ValueError, match="ALLOW_OPEN_REGISTRATION"):
            _settings("production", ALLOW_OPEN_REGISTRATION=True)

    def test_the_default_database_password_is_refused(self):
        with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
            _settings("production", POSTGRES_PASSWORD="postgres")

    def test_the_default_object_storage_secret_is_refused(self):
        with pytest.raises(ValueError, match="S3_SECRET_KEY"):
            _settings("production", S3_SECRET_KEY="minioadmin")

    def test_an_unguarded_metrics_endpoint_is_refused(self):
        with pytest.raises(ValueError, match="METRICS_TOKEN"):
            _settings("production", METRICS_TOKEN=None)

    def test_every_problem_is_reported_at_once(self):
        """One restart per discovered problem is a miserable way to deploy."""
        with pytest.raises(ValueError) as exc:
            Settings(
                ENVIRONMENT="production",
                SECRET_KEY=INSECURE_SECRET_KEY,
                FIRST_SUPERUSER_PASSWORD="admin12345",
                ALLOW_OPEN_REGISTRATION=True,
            )
        message = str(exc.value)
        for expected in ("SECRET_KEY", "FIRST_SUPERUSER_PASSWORD", "ALLOW_OPEN_REGISTRATION"):
            assert expected in message

    def test_a_correctly_configured_production_boots(self):
        s = _settings("production")
        assert s.DEBUG is False
        assert s.ENVIRONMENT == "production"
