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


class TestASignignKeyDefaultIsAlwaysFatal:
    """The one check with no safe way to continue: a published or short
    signing key means anyone can mint a token for any account, superuser
    included."""

    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_the_published_secret_key_is_refused(self, environment):
        with pytest.raises(ValueError, match="SECRET_KEY"):
            _settings(environment, SECRET_KEY=INSECURE_SECRET_KEY)

    def test_a_short_secret_key_is_refused(self):
        with pytest.raises(ValueError, match="at least 32"):
            _settings("production", SECRET_KEY="too-short")

    def test_it_is_fatal_even_without_strict_mode(self):
        with pytest.raises(ValueError, match="SECRET_KEY"):
            _settings("production", SECRET_KEY=INSECURE_SECRET_KEY, STRICT_PRODUCTION_CHECKS=False)


class TestConfigHygieneWarnsByDefault:
    """These are real problems, but an operator may have compensating
    controls — and a check introduced in one release must not turn the next
    upgrade into an outage. METRICS_TOKEN is the clearest case: it did not
    exist before, so no deployed .env can satisfy it."""

    @pytest.mark.parametrize(
        "override",
        [
            {"FIRST_SUPERUSER_PASSWORD": "admin12345"},
            {"ALLOW_OPEN_REGISTRATION": True},
            {"POSTGRES_PASSWORD": "postgres"},
            {"S3_SECRET_KEY": "minioadmin"},
            {"METRICS_TOKEN": None},
        ],
    )
    def test_production_still_boots(self, override):
        s = _settings("production", **override)
        assert s.ENVIRONMENT == "production"

    def test_the_problem_is_reported_on_stderr(self, capsys):
        _settings("production", METRICS_TOKEN=None)
        assert "METRICS_TOKEN" in capsys.readouterr().err

    def test_a_new_check_cannot_brick_an_existing_deployment(self):
        """The regression this severity split exists to prevent: an .env
        written before METRICS_TOKEN existed must still start."""
        s = Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a" * 48,
            METRICS_TOKEN=None,
            POSTGRES_PASSWORD="postgres",
            S3_SECRET_KEY="minioadmin",
        )
        assert s.ENVIRONMENT == "production"


class TestStrictModePromotesEverything:
    @pytest.mark.parametrize(
        "override,expected",
        [
            ({"FIRST_SUPERUSER_PASSWORD": "admin12345"}, "FIRST_SUPERUSER_PASSWORD"),
            ({"ALLOW_OPEN_REGISTRATION": True}, "ALLOW_OPEN_REGISTRATION"),
            ({"POSTGRES_PASSWORD": "postgres"}, "POSTGRES_PASSWORD"),
            ({"S3_SECRET_KEY": "minioadmin"}, "S3_SECRET_KEY"),
            ({"METRICS_TOKEN": None}, "METRICS_TOKEN"),
        ],
    )
    def test_each_warning_becomes_fatal(self, override, expected):
        with pytest.raises(ValueError, match=expected):
            _settings("production", STRICT_PRODUCTION_CHECKS=True, **override)

    def test_every_problem_is_reported_at_once(self):
        """One restart per discovered problem is a miserable way to deploy."""
        with pytest.raises(ValueError) as exc:
            Settings(
                ENVIRONMENT="production",
                STRICT_PRODUCTION_CHECKS=True,
                SECRET_KEY=INSECURE_SECRET_KEY,
                FIRST_SUPERUSER_PASSWORD="admin12345",
                ALLOW_OPEN_REGISTRATION=True,
            )
        message = str(exc.value)
        for expected in ("SECRET_KEY", "FIRST_SUPERUSER_PASSWORD", "ALLOW_OPEN_REGISTRATION"):
            assert expected in message

    def test_a_correctly_configured_production_boots_under_strict_mode(self):
        s = _settings("production", STRICT_PRODUCTION_CHECKS=True)
        assert s.DEBUG is False
        assert s.ENVIRONMENT == "production"
