"""Fail-closed behavior of the OpenSearch client's transport primitives.

Covers the two structural mechanisms this package's security contract
depends on: (1) ``_PerCallBearerAuth`` mints the Authorization header fresh
on every request and never sends an unauthenticated one, and (2)
``raise_for_transport_error``/``OpenSearchApiError`` never let a transport
failure look like an empty success — the exact class of bug this program has
hit before (ServiceNow PDI returning 200+HTML on every path).
"""

from __future__ import annotations

import pytest
from requests import PreparedRequest

from opensearch_mcp.api.api_client_base import (
    OpenSearchApiError,
    _PerCallBearerAuth,
    raise_for_transport_error,
)


def test_per_call_bearer_auth_invokes_provider_on_every_call():
    calls = {"n": 0}

    def _provider() -> str:
        calls["n"] += 1
        return f"tok-{calls['n']}"

    auth = _PerCallBearerAuth(_provider)
    req1 = PreparedRequest()
    req1.headers = {}
    req2 = PreparedRequest()
    req2.headers = {}

    auth(req1)
    auth(req2)

    assert req1.headers["Authorization"] == "Bearer tok-1"
    assert req2.headers["Authorization"] == "Bearer tok-2"
    assert calls["n"] == 2


def test_per_call_bearer_auth_refuses_empty_token():
    auth = _PerCallBearerAuth(lambda: "")
    req = PreparedRequest()
    req.headers = {}

    with pytest.raises(OpenSearchApiError, match="no calling-principal"):
        auth(req)


def test_raise_for_transport_error_wraps_not_found():
    from opensearchpy.exceptions import NotFoundError

    exc = NotFoundError(404, "not_found", {"found": False})
    with pytest.raises(OpenSearchApiError) as excinfo:
        raise_for_transport_error(exc, operation="get(kg-x/_doc/1)")
    assert excinfo.value.status_code == 404


def test_raise_for_transport_error_wraps_generic_transport_error():
    from opensearchpy.exceptions import TransportError

    exc = TransportError(503, "service_unavailable", {"error": "cluster red"})
    with pytest.raises(OpenSearchApiError) as excinfo:
        raise_for_transport_error(exc, operation="search(kg-*)")
    assert excinfo.value.status_code == 503


def test_raise_for_transport_error_wraps_unexpected_exception():
    with pytest.raises(OpenSearchApiError, match="transport"):
        raise_for_transport_error(RuntimeError("connection reset"), operation="search(kg-*)")
