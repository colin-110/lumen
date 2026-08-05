"""Regression tests for env-var parsing bugs that previously crashed the app
at startup — pydantic-settings tries to JSON-decode list-typed env vars
*before* any field_validator runs, so these fields need `NoDecode` plus a
validator that accepts a plain/comma-separated/empty string. See
`_split_origins` / `_split_models` in app.core.config."""

from app.core.config import Settings


def test_empty_fallback_models_env_var_does_not_crash(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODELS", "")
    settings = Settings()
    assert settings.FALLBACK_MODELS == []


def test_comma_separated_fallback_models(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODELS", "gpt-4o, claude-3-5-sonnet ,groq/llama-3.1")
    settings = Settings()
    assert settings.FALLBACK_MODELS == ["gpt-4o", "claude-3-5-sonnet", "groq/llama-3.1"]


def test_json_array_fallback_models(monkeypatch):
    monkeypatch.setenv("FALLBACK_MODELS", '["gpt-4o", "groq/llama-3.1"]')
    settings = Settings()
    assert settings.FALLBACK_MODELS == ["gpt-4o", "groq/llama-3.1"]


def test_empty_cors_origins_env_var_does_not_crash(monkeypatch):
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "")
    settings = Settings()
    assert settings.BACKEND_CORS_ORIGINS == []


def test_comma_separated_cors_origins(monkeypatch):
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "http://localhost:3000,http://example.com")
    settings = Settings()
    assert settings.BACKEND_CORS_ORIGINS == ["http://localhost:3000", "http://example.com"]


def test_default_settings_construct_without_any_env_vars(monkeypatch):
    # Belt-and-braces: Settings() must never raise with a totally clean env
    # (this is exactly the failure mode that took the backend down in prod —
    # an unset/empty optional list field crashing app startup).
    for var in ("FALLBACK_MODELS", "BACKEND_CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    assert isinstance(settings.FALLBACK_MODELS, list)
    assert isinstance(settings.BACKEND_CORS_ORIGINS, list)
