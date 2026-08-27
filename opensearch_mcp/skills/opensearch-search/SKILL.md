---
name: opensearch-search
skill_type: skill
description: >-
  Run BM25, k-NN, or hybrid queries against OpenSearch (CA-50 search tier)
  via the opensearch-mcp MCP server's search tool group, and inspect/apply
  document-level-security (DLS) policy — always as the calling principal, so
  DLS applies per-request; this package never constructs an admin/service-
  level-bypass client for a search call. Use when the agent must search
  indexed KG content, or read/apply a CA-16/26-rendered DLS bundle. Do NOT
  use for index/alias/mapping administration (use
  opensearch-index-operations) or for triggering a reindex (use
  opensearch-kg-ingestion).
license: MIT
tags: [opensearch, search, dls, security, mcp]
metadata:
  author: Genius
  version: '0.1.0'
---
# OpenSearch Search

Query the CA-50 search tier and manage its document-level-security policy.
**The single hardest invariant in this skill**: every search runs as the
calling principal's own delegated OpenSearch credential — never a
service-level or admin bypass, even for debugging. A restricted principal's
search for a marked-hidden object returns it absent (zero hits, or a
`found: false` on a direct get) — never a permission-denied error that
leaks the object's existence.

## When to use
- Lexical (BM25) search over an index (`opensearch_search`).
- Vector or hybrid search (`opensearch_knn_search`/`opensearch_hybrid_search`)
  — **note: the k-NN plugin is disabled on this cluster** (pre-AVX2 homelab
  nodes); both tools raise a typed, named error rather than a bare 500 when
  the plugin refuses the operation. Use `opensearch_search` (BM25) or
  eg-vector/vector-mcp for vector search instead.
- Read a security-plugin role's current DLS query (`opensearch_read_dls_rules`).
- Apply a CA-16/26-rendered policy bundle's OpenSearch renderings
  (`opensearch_apply_dls_bundle`) — this skill NEVER hand-authors a DLS rule;
  it only validates and applies a bundle it is given.

## When NOT to use
- Creating/reshaping indices → `opensearch-index-operations`.
- Triggering a KG-driven reindex → `opensearch-kg-ingestion`.
- Authoring a DLS rule from scratch — not supported anywhere in this
  package; that is CA-16 (bundle generation) / CA-26 (per-target render)'s
  territory. `opensearch_apply_dls_bundle` only applies what it's given.

## Prerequisites & environment
Connect via the `mcp-client` skill against the **`opensearch-mcp`** MCP
server. Search tools accept no credential override parameter of any kind —
there is nothing to configure per-call; the caller's own MCP session
identity is what determines what comes back.

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENSEARCH_URL` | recommended | Bare OpenSearch origin. Defaults to `https://opensearch.arpa`. |
| `ENABLE_DELEGATION` / `OIDC_CONFIG_URL` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET_REF` | ✅ | Shared agent-utilities MCP OIDC-delegation surface. Without this, every search tool raises rather than falling back to an unauthenticated or admin-scoped call. |
| `OPENSEARCH_KEYCLOAK_CLIENT_ID` | optional | Delegated-token audience. Defaults to `opensearch`. |

## Tools

| Tool | Purpose |
|------|---------|
| `opensearch_search` | BM25 lexical search, capped at 100 hits |
| `opensearch_knn_search` | k-NN vector search (typed error — plugin disabled) |
| `opensearch_hybrid_search` | Lexical + vector hybrid (typed error if a knn clause is present and the plugin is disabled) |
| `opensearch_read_dls_rules` | Read-only: one role's DLS query |
| `opensearch_apply_dls_bundle` | Validate + apply a CA-16/26-rendered bundle's `renderings.opensearch` entries |

## Failure modes to expect
- No delegated principal token available → typed `OpenSearchApiError`, never
  a silent fall-through to an unauthenticated or service-level request.
- `opensearch_apply_dls_bundle` with a malformed bundle (missing
  `renderings.opensearch`, an unrecognized `governs`, or a missing `graph`)
  is rejected with a named field error — never partially applied.
- A restricted principal searching for a marked-hidden document gets zero
  hits (or `found: false` on a direct get) — this is DLS working correctly,
  not a bug to "fix" by widening the query.
