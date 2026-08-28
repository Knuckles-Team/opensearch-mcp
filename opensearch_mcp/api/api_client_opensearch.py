"""OpenSearch client wrapping ``opensearchpy.OpenSearch`` for the search tier (CA-50).

Every method routes through one ``opensearchpy.OpenSearch`` instance whose
transport auth is :class:`~opensearch_mcp.api.api_client_base._PerCallBearerAuth`
— the calling principal's own token, re-minted on every request (see that
module's docstring for why this is structural rather than conventional).

**k-NN plugin**: disabled cluster-wide (pre-AVX2 homelab nodes — no AVX2-free
OpenSearch k-NN build exists upstream, `services/opensearch/AGENTS.md`).
`knn_search`/`hybrid_search` exist per this lane's scope but degrade to a
typed :class:`OpenSearchApiError` (naming the plugin as the cause) rather
than a bare 500 when the plugin refuses the query — verified live against
the deployed cluster (2.19.6): indexing a `knn_vector` document and running a
`knn` query both fail with `illegal_state_exception: "KNN plugin is
disabled..."`.

**Security-plugin admin surface** (DLS role read/apply) has no first-class
``opensearchpy`` client namespace — both go through
``client.transport.perform_request`` against ``/_plugins/_security/api/...``,
the same low-level path OpenSearch's own `securityadmin.sh`/Dashboards use.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

from opensearchpy import OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import TransportError

from opensearch_mcp.api.api_client_base import (
    OpenSearchApiError,
    _PerCallBearerAuth,
    raise_for_transport_error,
)

logger = logging.getLogger("opensearch_mcp.api")

__all__ = ["OpenSearchApi", "OpenSearchApiError"]

_MAX_SEARCH_SIZE = 100
_KNN_DISABLED_MARKERS = ("knn plugin is disabled", "knn.plugin.enabled")


def _is_knn_disabled_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _KNN_DISABLED_MARKERS)


class OpenSearchApi:
    """Authenticated OpenSearch client — always constructed with a per-call
    token provider, never a static baked-in credential.

    ``base_url`` is the bare OpenSearch origin (e.g. ``http://localhost:9200``).
    """

    def __init__(
        self,
        base_url: str,
        token_provider: Any = None,
        verify_certs: bool | str = True,
        timeout: float = 30.0,
        _test_basic_auth: tuple[str, str] | None = None,
    ) -> None:
        """Construct the client. ``token_provider`` (a zero-arg callable
        returning a bearer token) is the ONLY production credential path —
        ``opensearch_mcp.auth.get_client()`` is the sole caller that should
        ever populate it, sourced from the calling principal's own delegated
        token, never a fixed/service credential.

        ``_test_basic_auth`` exists ONLY for this package's own live-proof
        scripts/tests exercising this exact client class against OpenSearch's
        pre-bundle internal-user DLS demonstration accounts
        (``services/opensearch/AGENTS.md``'s W07 fixture — CA-16/26's real
        policy bundle has not landed yet). It is never referenced by
        ``auth.py`` or by any ``mcp/*.py`` tool — passing it from either would
        be exactly the admin/service-bypass this package's own contract
        forbids.
        """
        if token_provider is None and _test_basic_auth is None:
            raise OpenSearchApiError(
                "OpenSearchApi requires a token_provider callable — a static token "
                "or no credential at all would violate the 'always the calling "
                "principal, per-call' invariant this package exists to hold"
            )
        parsed = urlparse(base_url)
        host = parsed.hostname or base_url
        port = parsed.port or (443 if parsed.scheme != "http" else 9200)
        use_ssl = parsed.scheme != "http"
        self.base_url = base_url.rstrip("/")
        if token_provider is not None:
            http_auth: Any = _PerCallBearerAuth(token_provider)
        else:
            logger.warning(
                "OpenSearchApi constructed with _test_basic_auth — this is the "
                "package's TEST-ONLY escape hatch and must never be reachable "
                "from auth.get_client() or any mcp/*.py tool"
            )
            http_auth = _test_basic_auth
        self._client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=http_auth,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            connection_class=RequestsHttpConnection,
            timeout=timeout,
        )

    # ── low-level escape hatch (security-plugin admin API) ───────────────
    def _perform(self, method: str, url: str, body: Any = None) -> Any:
        try:
            return self._client.transport.perform_request(method, url, body=body)
        except Exception as exc:  # noqa: BLE001 - normalized below
            raise_for_transport_error(exc, operation=f"{method} {url}")

    # ── cluster / plugin introspection ────────────────────────────────────
    def cluster_health(self) -> dict[str, Any]:
        try:
            return self._client.cluster.health()
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(exc, operation="cluster_health")

    def knn_plugin_enabled(self) -> bool:
        """Live check of the k-NN plugin's runtime-enabled flag (never assumed)."""
        # `include_defaults` isn't expressible via the high-level client's
        # settings helper params without extra plumbing; ask the flat path
        # directly, matching services/opensearch/AGENTS.md's own verification.
        flat = self._perform(
            "GET",
            "/_cluster/settings?include_defaults=true&filter_path=**.knn.plugin.enabled",
        )
        try:
            return str(flat["defaults"]["knn"]["plugin"]["enabled"]).lower() == "true"
        except (KeyError, TypeError):
            return False

    # ── index admin (typed OntologyActions per DEC-CA-07) ─────────────────
    def create_index(
        self, index: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            return self._client.indices.create(index=index, body=body or {})
        except Exception as exc:  # noqa: BLE001
            if (
                isinstance(exc, TransportError)
                and getattr(exc, "status_code", None) == 400
            ):
                info = getattr(exc, "info", {}) or {}
                err = (info.get("error") or {}) if isinstance(info, dict) else {}
                if err.get("type") == "resource_already_exists_exception":
                    # Idempotent per this lane's contract: creating an index
                    # that already exists is not an error.
                    return {
                        "index": index,
                        "acknowledged": True,
                        "already_exists": True,
                    }
            raise_for_transport_error(exc, operation=f"create_index({index})")

    def update_mapping(self, index: str, properties: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.indices.put_mapping(
                index=index, body={"properties": properties}
            )
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(exc, operation=f"update_mapping({index})")

    def manage_alias(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply one or more alias actions (``{"add": {...}}``/``{"remove": {...}}``).

        The Alias Swap idiom (remove old + add new in one call) is OpenSearch's
        own idempotent primitive — this method is a thin pass-through to it.
        """
        try:
            return self._client.indices.update_aliases(body={"actions": actions})
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(exc, operation="manage_alias")

    def get_aliases(self, index: str = "*") -> dict[str, Any]:
        try:
            return self._client.indices.get_alias(index=index)
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(exc, operation=f"get_aliases({index})")

    def update_settings(self, index: str, settings: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.indices.put_settings(
                index=index, body={"index": settings}
            )
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(exc, operation=f"update_settings({index})")

    def rollover(
        self,
        alias: str,
        conditions: dict[str, Any] | None = None,
        new_index: str | None = None,
    ) -> dict[str, Any]:
        try:
            target = f"{alias}/{new_index}" if new_index else alias
            return self._client.indices.rollover(
                alias=target, body={"conditions": conditions or {}}
            )
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(exc, operation=f"rollover({alias})")

    def delete_index(self, index: str) -> dict[str, Any]:
        try:
            return self._client.indices.delete(index=index)
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(exc, operation=f"delete_index({index})")

    # ── search (always the calling principal — DLS applies per-request) ──
    def search(
        self,
        index: str,
        query: dict[str, Any],
        size: int = 10,
        _source: list[str] | None = None,
    ) -> dict[str, Any]:
        capped = min(max(int(size), 0), _MAX_SEARCH_SIZE)
        body: dict[str, Any] = {"query": query, "size": capped}
        if _source is not None:
            body["_source"] = _source
        try:
            return self._client.search(index=index, body=body)
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(exc, operation=f"search({index})")

    def knn_search(
        self,
        index: str,
        field: str,
        vector: list[float],
        k: int = 10,
        size: int = 10,
    ) -> dict[str, Any]:
        capped = min(max(int(size), 0), _MAX_SEARCH_SIZE)
        body = {
            "size": capped,
            "query": {"knn": {field: {"vector": vector, "k": k}}},
        }
        try:
            return self._client.search(index=index, body=body)
        except Exception as exc:  # noqa: BLE001
            if _is_knn_disabled_error(exc):
                raise OpenSearchApiError(
                    "k-NN plugin is disabled on this cluster (pre-AVX2 homelab "
                    "nodes — no AVX2-free k-NN build exists upstream, "
                    "services/opensearch/AGENTS.md). opensearch_knn_search cannot "
                    "run here; use opensearch_search (BM25) or eg-vector/vector-mcp "
                    "for vector search instead.",
                    status_code=getattr(exc, "status_code", None),
                ) from exc
            raise_for_transport_error(exc, operation=f"knn_search({index})")

    def hybrid_search(
        self,
        index: str,
        queries: list[dict[str, Any]],
        size: int = 10,
    ) -> dict[str, Any]:
        """OpenSearch's native hybrid (lexical + vector) query compound clause.

        Degrades the same way as :meth:`knn_search` when any sub-query is a
        ``knn`` clause and the plugin is disabled — never a bare 500.
        """
        capped = min(max(int(size), 0), _MAX_SEARCH_SIZE)
        body = {"size": capped, "query": {"hybrid": {"queries": queries}}}
        try:
            return self._client.search(
                index=index,
                body=body,
                params={"search_pipeline": "hybrid-search-pipeline"},
            )
        except Exception as exc:  # noqa: BLE001
            if _is_knn_disabled_error(exc):
                raise OpenSearchApiError(
                    "hybrid search includes a k-NN clause and the k-NN plugin is "
                    "disabled on this cluster (pre-AVX2 homelab nodes). Run a "
                    "lexical-only opensearch_search instead, or drop the vector "
                    "sub-query.",
                    status_code=getattr(exc, "status_code", None),
                ) from exc
            raise_for_transport_error(exc, operation=f"hybrid_search({index})")

    # ── ingest pipelines ───────────────────────────────────────────────────
    def put_ingest_pipeline(
        self, pipeline_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return self._client.ingest.put_pipeline(id=pipeline_id, body=body)
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(
                exc, operation=f"put_ingest_pipeline({pipeline_id})"
            )

    def get_ingest_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        try:
            return self._client.ingest.get_pipeline(id=pipeline_id)
        except Exception as exc:  # noqa: BLE001
            raise_for_transport_error(
                exc, operation=f"get_ingest_pipeline({pipeline_id})"
            )

    # ── security / DLS (never hand-authored — applies a CA-16/26 bundle) ──
    def read_dls_rules(self, role: str) -> dict[str, Any]:
        """Read one OpenSearch security-plugin role's index permissions/DLS query.

        Read-only — this is the *only* security-group method the ``search``
        invariant does not apply to as strictly (it reads config, it does not
        search data), but it still runs as the calling principal's own token
        (a principal with no ``security_rest_api_access`` simply gets a 403
        from OpenSearch itself, which is surfaced, not swallowed).
        """
        return self._perform("GET", f"/_plugins/_security/api/roles/{role}")

    def apply_dls_bundle_rendering(
        self, role: str, index_pattern: str, dls_query: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply ONE already-validated ``renderings.opensearch`` entry.

        Callers (``mcp/mcp_opensearch.py``) are responsible for validating the
        bundle's shape and provenance BEFORE calling this — this method never
        constructs a DLS predicate itself, it only PUTs the one already given
        to it, matching this package's "never hand-author a DLS rule" invariant.
        """
        body = {
            "cluster_permissions": [],
            "index_permissions": [
                {
                    "index_patterns": [index_pattern],
                    "dls": json.dumps(dls_query),
                    "allowed_actions": ["read"],
                }
            ],
        }
        return self._perform("PUT", f"/_plugins/_security/api/roles/{role}", body=body)
