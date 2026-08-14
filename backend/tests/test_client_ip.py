"""Which address the rate limiter buckets on.

Getting this wrong fails in both directions. Trust the header when nothing
sets it and an attacker rotates a fake value per request, so the limit does
nothing. Ignore it behind a reverse proxy and every user shares the proxy's
address, so one person hitting the limit locks out everybody — on this
project's own deployment, where Caddy is the only ingress, that is the
default-off behaviour.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.rate_limit import client_ip


class _Client:
    def __init__(self, host: str) -> None:
        self.host = host


class _Request:
    def __init__(self, headers: dict[str, str] | None = None, peer: str | None = "10.0.0.9"):
        self.headers = headers or {}
        self.client = _Client(peer) if peer else None


@pytest.fixture
def trusted(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADERS", True, raising=False)


@pytest.fixture
def untrusted(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HEADERS", False, raising=False)


class TestWithoutATrustedProxy:
    def test_the_socket_address_is_used(self, untrusted):
        assert client_ip(_Request(peer="203.0.113.7")) == "203.0.113.7"

    def test_a_forwarded_header_is_ignored(self, untrusted):
        """Nothing trustworthy set it, so it is attacker-controlled."""
        req = _Request({"X-Forwarded-For": "1.2.3.4"}, peer="203.0.113.7")
        assert client_ip(req) == "203.0.113.7"

    def test_a_missing_peer_degrades_to_a_shared_bucket(self, untrusted):
        assert client_ip(_Request(peer=None)) == "unknown"


class TestBehindATrustedProxy:
    def test_the_forwarded_address_is_used(self, trusted):
        req = _Request({"X-Forwarded-For": "203.0.113.7"}, peer="172.18.0.4")
        assert client_ip(req) == "203.0.113.7"

    def test_a_forged_prefix_cannot_win(self, trusted):
        """Proxies append. A client sending `X-Forwarded-For: 1.2.3.4`
        arrives as "1.2.3.4, <real>", so reading the left end would hand the
        attacker a fresh bucket per request — exactly the bypass the header
        check exists to prevent."""
        req = _Request({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"}, peer="172.18.0.4")
        assert client_ip(req) == "203.0.113.7"

    def test_a_long_forged_chain_still_resolves_to_the_proxys_entry(self, trusted):
        chain = ", ".join(["9.9.9.9"] * 50 + ["203.0.113.7"])
        assert client_ip(_Request({"X-Forwarded-For": chain})) == "203.0.113.7"

    def test_whitespace_and_empty_entries_are_tolerated(self, trusted):
        req = _Request({"X-Forwarded-For": " 1.2.3.4 , , 203.0.113.7 "})
        assert client_ip(req) == "203.0.113.7"

    def test_an_empty_header_falls_back_to_the_socket(self, trusted):
        req = _Request({"X-Forwarded-For": "   "}, peer="172.18.0.4")
        assert client_ip(req) == "172.18.0.4"

    def test_the_value_is_length_bounded(self, trusted):
        """It becomes part of a Redis key."""
        req = _Request({"X-Forwarded-For": "x" * 500})
        assert len(client_ip(req)) <= 64
