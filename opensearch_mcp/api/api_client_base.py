"""Shared transport primitives for the OpenSearch API wrapper.

CA-43's single hardest invariant (stated three times in the lane's source
specs, restated here so it cannot be missed by anyone editing this file):
**every OpenSearch request this package makes carries the calling
principal's own bearer token, attached per HTTP call — never a token baked
in once at client-construction time, and never a service-level/admin bypass
credential.** :class:`_PerCallBearerAuth` below is the structural mechanism
that makes this true: it is a ``requests.auth.AuthBase`` callable that
``opensearchpy``'s ``RequestsHttpConnection`` stores as ``session.auth`` and
invokes fresh on every single outbound request (see ``requests``'
``Session.send`` -> ``PreparedRequest.prepare_auth``) — so a token that
expires mid-session, or a caller whose identity changes between two tool
calls in the same process, is never silently reused.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from requests.auth import AuthBase


class OpenSearchApiError(RuntimeError):
    """An OpenSearch call failed with a typed, non-2xx response (or no usable
    calling-principal credential was available at all).

    Never silently degraded to an empty result — a caller (tool layer, KG
    ingest, the DLS-bundle applier) must be able to distinguish "no hits"
    from "the call failed" / "unreachable" / "no principal token available".
    """

    def __init__(
        self, message: str, *, status_code: int | str | None = None, body: Any = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class _PerCallBearerAuth(AuthBase):
    """A ``requests`` auth callable that mints the ``Authorization`` header
    fresh on every request by invoking ``token_provider()``.

    This is the structural half of the "always the calling principal, never
    a bypass credential" invariant: ``opensearchpy.RequestsHttpConnection``
    assigns whatever is passed as ``http_auth`` directly to
    ``requests.Session.auth`` (verified against opensearch-py 3.2.0's own
    source), and ``requests`` calls an ``AuthBase.__call__`` on EVERY
    prepared request, not once at session construction. A client built from
    this auth object cannot go stale, and cannot be handed a credential at
    construction time that outlives the request it was minted for.
    """

    def __init__(self, token_provider: Callable[[], str]) -> None:
        self._token_provider = token_provider

    def __call__(self, r: Any) -> Any:
        token = self._token_provider()
        if not token:
            raise OpenSearchApiError(
                "no calling-principal bearer token was available at request time — "
                "refusing to send an unauthenticated OpenSearch request rather than "
                "silently falling back to an admin/service credential"
            )
        r.headers["Authorization"] = f"Bearer {token}"
        return r


def raise_for_transport_error(exc: Exception, *, operation: str) -> None:
    """Translate an ``opensearchpy`` transport exception into
    :class:`OpenSearchApiError`, fail-closed and never swallowed.

    A hibernating/misrouted backend or a transport-layer failure must never
    look like "zero hits" — the exact class of bug recorded platform-wide
    from the ServiceNow PDI case (HTTP 200 + HTML on every path treated as
    silent success).
    """
    from opensearchpy.exceptions import NotFoundError, TransportError

    if isinstance(exc, OpenSearchApiError):
        # Already typed (e.g. _PerCallBearerAuth's "no calling-principal
        # token available") — re-raise as-is rather than double-wrapping it
        # inside a generic transport-failure message.
        raise exc
    if isinstance(exc, NotFoundError):
        raise OpenSearchApiError(
            f"OpenSearch {operation}: not found", status_code=404, body=getattr(exc, "info", None)
        ) from exc
    if isinstance(exc, TransportError):
        raise OpenSearchApiError(
            f"OpenSearch {operation} failed: {exc}",
            status_code=getattr(exc, "status_code", None),
            body=getattr(exc, "info", None),
        ) from exc
    raise OpenSearchApiError(f"OpenSearch {operation} failed (transport): {exc}") from exc
