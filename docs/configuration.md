# Configuration

See the [README's Environment Variables table](../README.md#environment-variables)
for the full, authoritative list — the code (`auth.py`, `mcp/mcp_opensearch.py`,
`kg_ingest.py`) is the source of truth; `.env.example`, every `mcp_config*.json`,
`docker/*compose*.yml`, and this table must all match it exactly (enforced by
`python -m agent_utilities.mcp.check_env_var_drift --check`).

## Delegation is not optional

Unlike most fleet packages, `opensearch-mcp` has **no fixed/service-credential
fallback**. `ENABLE_DELEGATION=True` plus a working `OIDC_CONFIG_URL` /
`OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET_REF` are required for ANY tool in this
package to authenticate — a `search`, `security`, or `index` call made
without a valid delegated principal token raises rather than silently
falling back to something that would work but bypass document-level
security.

## `OPENSEARCH_KEYCLOAK_CLIENT_ID`

The audience the caller's own MCP-session token is exchanged for (RFC 8693).
Defaults to `opensearch`, matching the Keycloak `homelab`-realm client
provisioned for OpenSearch (`services/opensearch/AGENTS.md`'s W04 note). A
valid token for this audience carries the `roles` claim OpenSearch's
`openid_auth_domain` maps directly to its own backend roles.

## TLS

`OPENSEARCH_TLS_PROFILE`/`OPENSEARCH_TLS_PROFILE_REF` select a named outbound
TLS trust policy (via `agent_utilities.core.transport_security`). The
homelab's internal CA (`homelab-arpa-ca`) is trusted fleet-wide via the
`homelab-ca-bundle` ConfigMap mount; OpenSearch itself terminates its own TLS
at `:9200` (the security plugin refuses to run without it) and the ingress
re-encrypts rather than offloading to plain HTTP.

## k-NN stays disabled

Do not set `knn.plugin.enabled: true` anywhere in this package's
configuration surface, and do not add a tool whose only path requires k-NN.
The homelab's nodes have no AVX2 and no AVX2-free OpenSearch k-NN build
exists upstream — see `docs/architecture.md` for how `knn_search`/
`hybrid_search` degrade instead of assuming the plugin is available.
