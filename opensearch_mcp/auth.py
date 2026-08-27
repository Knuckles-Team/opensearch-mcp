"""Identity credentials loader for the OpenSearch client — CA-43's hardest invariant.

Every OpenSearch request this package makes must carry the CALLING
PRINCIPAL's own bearer token, never a service-level/admin bypass credential
— stated three times in this lane's source specs for emphasis (the lane
brief's WORK section, `designs/MCP-SERVERS.md` §3, and the lane's own
mission statement). This module holds that structurally, not by convention:

* :func:`get_client` is the ONLY client factory in this package. Every tool
  group — index, search, pipelines, security, and the reindex-from-KG
  trigger — calls it. There is no second factory, and no parameter on this
  one that accepts an override credential.
* It has no fallback path to a fixed/service credential. If OIDC delegation
  is not enabled, or the token exchange fails, it raises
  :class:`~opensearch_mcp.api.api_client_base.OpenSearchApiError` — it never
  degrades to something that would still work but silently bypass DLS. This
  is a deliberate divergence from the fleet's usual delegated-auth pattern
  (``gitlab-api``/``twenty-mcp`` fall through to a fixed token on delegation
  failure) — that fallback is exactly what this package's security
  invariant forbids.
* The resulting client's auth is a per-call token PROVIDER (a zero-arg
  callable), not a token value — ``opensearchpy``'s
  ``RequestsHttpConnection`` stores it as ``requests.Session.auth`` and
  ``requests`` invokes it fresh on every outbound request, never once at
  construction time (verified against opensearch-py 3.2.0's own source —
  see ``api/api_client_base.py``'s module docstring).

Uses the fleet's shared ``agent_utilities.mcp.delegated_auth`` RFC 8693
token-exchange helper (the same mechanism ``gitlab-api``/``twenty-mcp`` use)
to exchange the MCP-layer caller's Keycloak (realm ``homelab``) token for one
scoped to the ``opensearch`` Keycloak client audience.
``services/opensearch/AGENTS.md``'s W04 note confirms OpenSearch's security
plugin validates a Keycloak-issued bearer token directly (its
``openid_auth_domain`` treats the JWT's ``roles`` claim as OpenSearch backend
roles) — proven live: a ``client_credentials`` grant against
``https://keycloak.arpa/realms/homelab/protocol/openid-connect/token``
authenticates successfully against ``https://opensearch.arpa/_cluster/health``.
"""

from __future__ import annotations

from typing import Any

from agent_utilities.base_utilities import get_logger
from agent_utilities.core.config import setting
from agent_utilities.core.transport_security import resolve_configured_tls_profile

from opensearch_mcp.api.api_client_base import OpenSearchApiError
from opensearch_mcp.api_client import Api

logger = get_logger(__name__)

# Keycloak grants a broad default scope set (observed live: "profile email");
# the `opensearch` client does not require a distinct custom scope the way
# Lakekeeper's `lakekeeper-service` client does — its authorization instead
# comes from the `roles` claim (the `opensearch-client-roles` protocol
# mapper), not from OAuth2 scope. Kept as a named constant so a future
# scope requirement has one place to change.
OPENSEARCH_DELEGATED_SCOPES = "profile"


def _delegated_token(config: dict[str, Any] | None) -> str:
    """Exchange the calling principal's own MCP-session token for one scoped
    to the ``opensearch`` Keycloak client audience.

    Raises rather than returning an empty/``None`` token — there is no
    fallback path in this package to a fixed or service-level credential.
    """
    from agent_utilities.mcp.delegated_auth import (
        get_delegated_token,
        is_delegation_enabled,
    )

    if not is_delegation_enabled(config):
        raise OpenSearchApiError(
            "OIDC delegation is not enabled for this MCP server (requires "
            "--auth-type oidc-proxy / --enable-delegation at MCP startup and a "
            "request carrying a Bearer token) — opensearch-mcp has no other "
            "credential path. This is deliberate: no tool in this package may "
            "construct an admin/service-level-bypass OpenSearch client, even as "
            "a debugging convenience."
        )
    try:
        audience = (config or {}).get(
            "audience", setting("OPENSEARCH_KEYCLOAK_CLIENT_ID", "opensearch")
        )
        scopes = (config or {}).get("delegated_scopes", OPENSEARCH_DELEGATED_SCOPES)
        return get_delegated_token(config=config, audience=audience, scopes=scopes)
    except OpenSearchApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalized into one typed error
        raise OpenSearchApiError(
            f"OIDC token exchange for OpenSearch failed: {type(exc).__name__} — "
            "refusing to fall back to a fixed/service credential"
        ) from exc


def get_client(config: dict[str, Any] | None = None) -> Api:
    """Build the OpenSearch client — the ONLY client factory in this package.

    Every tool group (index/search/pipelines/security, and the
    reindex-from-KG trigger) calls this, and only this. The returned
    client's credential is a per-call token PROVIDER, invoked fresh on every
    HTTP request — never a token captured once and baked in at construction
    time.
    """
    base_url = setting("OPENSEARCH_URL", "https://opensearch.arpa")
    tls_profile = resolve_configured_tls_profile(
        "opensearch",
        profile_name=setting("OPENSEARCH_TLS_PROFILE", None),
        profile_ref=setting("OPENSEARCH_TLS_PROFILE_REF", None),
    )
    verify = tls_profile.requests_kwargs().get("verify", True)
    return Api(
        base_url=base_url,
        token_provider=lambda: _delegated_token(config),
        verify_certs=verify,
    )
