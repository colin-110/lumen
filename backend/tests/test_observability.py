"""Metrics and request-id handling.

Both failures here are the kind that never surface in the service that causes
them: unbounded Prometheus labels degrade the Prometheus server, and forged
log entries only matter when someone later reads the logs.
"""

from __future__ import annotations

import re

from app.main import _REQUEST_ID_RE, _safe_request_id


class TestRequestIdValidation:
    def test_a_well_formed_inbound_id_is_kept(self):
        assert _safe_request_id("abc-123_DEF.45:6") == "abc-123_DEF.45:6"

    def test_a_missing_id_gets_a_generated_uuid(self):
        generated = _safe_request_id(None)
        assert re.fullmatch(r"[0-9a-f-]{36}", generated)

    def test_newlines_are_rejected(self):
        """The id is written into every log line for the request. A value
        containing a newline can append a fabricated log entry."""
        forged = "ok\nlevel=ERROR msg=\"database deleted\""
        assert _safe_request_id(forged) != forged

    def test_control_characters_are_rejected(self):
        assert _safe_request_id("abc\r\ndef") != "abc\r\ndef"
        assert _safe_request_id("abc\x00def") != "abc\x00def"

    def test_an_overlong_id_is_rejected(self):
        assert _safe_request_id("x" * 5000) != "x" * 5000

    def test_the_pattern_accepts_a_plain_uuid(self):
        assert _REQUEST_ID_RE.match("3f7c1b2e-0f4a-4c2a-9a1f-0b6d2e5a7c81")


class TestMetricLabelCardinality:
    """`request.url.path` as a Prometheus label meant one time series per
    document UUID ever requested, growing without bound."""

    def test_the_route_template_is_used_not_the_concrete_path(self):
        from app.main import _metric_path

        class _Route:
            path = "/api/v1/documents/{document_id}"

        class _Request:
            scope = {"route": _Route()}

        assert _metric_path(_Request()) == "/api/v1/documents/{document_id}"

    def test_unmatched_paths_collapse_to_one_bucket(self):
        from app.main import _metric_path

        class _Request:
            scope: dict = {}

        assert _metric_path(_Request()) == "__unmatched__"

    def test_two_different_ids_produce_the_same_label(self):
        from app.main import _metric_path

        class _Route:
            path = "/api/v1/conversations/{conversation_id}"

        class _Request:
            scope = {"route": _Route()}

        # Whatever the concrete URL was, the label is the template.
        assert _metric_path(_Request()) == _metric_path(_Request())


class TestMetricsEndpointGuard:
    async def test_metrics_requires_the_token_when_one_is_configured(self, monkeypatch):
        import httpx

        from app.core.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret", raising=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=True
        ) as ac:
            assert (await ac.get("/metrics")).status_code == 401
            assert (
                await ac.get("/metrics", headers={"Authorization": "Bearer wrong"})
            ).status_code == 401
            ok = await ac.get("/metrics", headers={"Authorization": "Bearer s3cret"})
            assert ok.status_code == 200

    async def test_metrics_is_open_when_no_token_is_configured(self, monkeypatch):
        import httpx

        from app.core.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "METRICS_TOKEN", None, raising=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", follow_redirects=True
        ) as ac:
            assert (await ac.get("/metrics")).status_code == 200
