"""The calling-principal invariant: no fallback to a fixed/service credential.

This is CA-43's hardest invariant, tested directly rather than by
inspection: ``get_client()``/``OpenSearchApi`` must raise — never silently
degrade to an unauthenticated or admin-scoped client — whenever a real
delegated principal token isn't available.
"""

from __future__ import annotations

import pytest

import opensearch_mcp.auth as auth_module
from opensearch_mcp.api.api_client_base import OpenSearchApiError
from opensearch_mcp.api.api_client_opensearch import OpenSearchApi


def test_opensearch_api_requires_a_credential():
    """Constructing the client with no token_provider AND no _test_basic_auth
    is refused outright — there is no unauthenticated path."""
    with pytest.raises(OpenSearchApiError, match="token_provider"):
        OpenSearchApi("http://localhost:9200")


def test_delegated_token_raises_when_delegation_disabled(monkeypatch):
    """`get_client()`'s only credential path is OIDC delegation. When it's
    disabled, this must raise, never fall back to a fixed credential (no
    such fallback exists anywhere in this module)."""
    monkeypatch.setattr(
        "agent_utilities.mcp.delegated_auth.is_delegation_enabled", lambda config: False
    )

    with pytest.raises(OpenSearchApiError, match="OIDC delegation is not enabled"):
        auth_module._delegated_token(None)


def test_delegated_token_wraps_exchange_failure(monkeypatch):
    """A token-exchange failure must surface as OpenSearchApiError, not the
    raw underlying exception, and must never return an empty token."""
    monkeypatch.setattr(
        "agent_utilities.mcp.delegated_auth.is_delegation_enabled", lambda config: True
    )

    def _boom(**kwargs):
        raise RuntimeError("token endpoint unreachable")

    monkeypatch.setattr("agent_utilities.mcp.delegated_auth.get_delegated_token", _boom)

    with pytest.raises(OpenSearchApiError, match="refusing to fall back"):
        auth_module._delegated_token(None)


def test_get_client_wires_a_per_call_token_provider(monkeypatch):
    """`get_client()` must build the client with a token PROVIDER (called
    fresh per request), never a token captured once at construction time."""
    monkeypatch.setenv("OPENSEARCH_URL", "https://opensearch.example")
    calls = {"n": 0}

    def _fake_delegated_token(config):
        calls["n"] += 1
        return f"tok-{calls['n']}"

    monkeypatch.setattr(auth_module, "_delegated_token", _fake_delegated_token)

    client = auth_module.get_client()

    assert client.base_url == "https://opensearch.example"
    # The provider is a closure over _delegated_token — invoking it directly
    # (as opensearchpy would, per request) must call through, not replay a
    # captured value.
    bearer_auth = client._client.transport.get_connection().session.auth
    assert bearer_auth._token_provider() == "tok-1"
    assert bearer_auth._token_provider() == "tok-2"
    assert calls["n"] == 2
