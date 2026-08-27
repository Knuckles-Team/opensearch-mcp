# opensearch-mcp

A Model Context Protocol (MCP) server, A2A agent, and API client for
OpenSearch (the CA-50 search tier) integration.

![MCP Server](https://badge.mcpx.dev?type=server 'MCP Server')

## Table of Contents
- [Overview](#overview)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Environment Variables](#environment-variables)
- [MCP Tools](#mcp-tools)
- [Documentation](#documentation)

## Overview
`opensearch-mcp` exposes a standardized interface to the platform's OpenSearch
deployment (CA-50, `https://opensearch.arpa`) via the Model Context Protocol —
index/alias/mapping/settings/rollover admin, BM25/k-NN/hybrid search, ingest
pipeline admin, and document-level-security (DLS) policy read/apply. A
trigger-only `opensearch_reindex_from_kg` tool records a rebuild request as an
`:IndexingRun` node; the actual reindex is CA-24's own CDC-fed indexer.

**The single hardest invariant this package holds**: every request carries
the calling principal's own token, attached fresh on every HTTP call — never
a fixed/service-level credential. `opensearch_mcp.auth.get_client()` is the
ONLY client factory in the package; there is no fallback path. See
[Architecture](#architecture) and `AGENTS.md` for how this is enforced
structurally.

**k-NN is disabled cluster-wide** (pre-AVX2 homelab nodes — no AVX2-free
OpenSearch k-NN build exists upstream). `opensearch_knn_search`/
`opensearch_hybrid_search` exist per this package's scope but raise a typed,
named error rather than a bare 500 when the plugin refuses the operation.

## Installation

Pick the extra that matches what you want to run:

| Extra | Installs | Use when |
|-------|----------|----------|
| `opensearch-mcp[mcp]` | Connector-focused MCP server (`agent-utilities[mcp]` — FastMCP/FastAPI + `epistemic-graph[full]`) | You only run the **MCP server** (smallest install / image) |
| `opensearch-mcp[agent]` | Agent runtime (`agent-utilities[agent-runtime,logfire]` — model orchestration + `epistemic-graph[full]`) | You run the **integrated A2A agent** |
| `opensearch-mcp[all]` | Everything (`mcp` + `agent` + `logfire`) | Development / both surfaces |

```bash
uv pip install "opensearch-mcp[mcp]"
```

### Container images (`:mcp` vs `:agent`)

One multi-stage `docker/Dockerfile` builds two right-sized images, selected by `--target`:

```bash
docker build --target mcp   -t opensearch-mcp:mcp    .
docker build --target agent -t opensearch-mcp:agent   .
```

## Usage
Run the MCP server directly:
```bash
python -m opensearch_mcp
```

### MCP Configuration Example (stdio)

```json
{
  "mcpServers": {
    "opensearch-mcp": {
      "command": "uv",
      "args": ["run", "opensearch-mcp"],
      "env": {
        "MCP_TOOL_MODE": "intent",
        "OPENSEARCH_URL": "https://opensearch.arpa",
        "OPENSEARCHTOOL": "True",
        "INGESTTOOL": "True",
        "ENABLE_DELEGATION": "True",
        "OIDC_CONFIG_URL": "https://keycloak.arpa/realms/homelab/.well-known/openid-configuration",
        "OIDC_CLIENT_ID": "",
        "OIDC_CLIENT_SECRET": "",
        "OPENSEARCH_KEYCLOAK_CLIENT_ID": "opensearch"
      }
    }
  }
}
```

## Architecture

`api/api_client_opensearch.py`'s `OpenSearchApi` wraps `opensearchpy.OpenSearch`
directly (the fleet's one new dependency this package adds). Its transport
auth is `api/api_client_base.py`'s `_PerCallBearerAuth` — a
`requests.auth.AuthBase` callable that `opensearchpy`'s
`RequestsHttpConnection` invokes fresh on EVERY outbound request (verified
against opensearch-py 3.2.0's own source: `RequestsHttpConnection.__init__`
assigns `http_auth` directly to `requests.Session.auth`, and `requests` calls
an `AuthBase.__call__` per request, never once at session construction).

`auth.py`'s `get_client()` is the ONLY client factory in the package. It
exchanges the calling MCP principal's own token for one scoped to the
`opensearch` Keycloak client audience via the fleet's shared
`agent_utilities.mcp.delegated_auth` (RFC 8693 token exchange) — and, unlike
`gitlab-api`/`twenty-mcp`'s use of the same helper, it has **no fallback to a
fixed/service credential**: if delegation isn't enabled or the exchange
fails, it raises. No tool in `mcp/mcp_opensearch.py` or `kg_ingest.py` accepts
a credential override parameter of any kind.

`mcp/mcp_opensearch.py` registers four tool groups (`index`, `search`,
`pipelines`, `security`) via one `register_tool_surface(...)` call in
`mcp_server.py`, matching the fleet's one-registration-call convention.
`kg_ingest.py` registers the fifth group (`opensearch_reindex_from_kg`,
tagged `ingest`/`kg`/`kg_ingest`) — a trigger-only tool that records an
`:IndexingRun` node through the required `native_ingest` (Wire-First)
authority; it never performs the reindex itself (CA-24 does).

`opensearch_apply_dls_bundle` validates a caller-supplied DEC-CA-04 policy
bundle's shape (`renderings.opensearch`, `governs: ["M1"]`, `graph`) before
applying it — this package contains no code path that constructs a DLS
predicate from scratch.

## Environment Variables

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENSEARCH_URL` | recommended | Bare OpenSearch origin. Defaults to `https://opensearch.arpa`. |
| `ENABLE_DELEGATION` | ✅ | Must be `True` — this package has no other credential path. |
| `OIDC_CONFIG_URL` | ✅ | OIDC discovery document URL (shared agent-utilities MCP surface). |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | ✅ | Confidential client used for the RFC 8693 token exchange. |
| `OPENSEARCH_KEYCLOAK_CLIENT_ID` | optional | Delegated-token audience. Defaults to `opensearch`. |
| `OPENSEARCH_TLS_PROFILE` / `OPENSEARCH_TLS_PROFILE_REF` | optional | Named outbound TLS trust policy. |
| `OPENSEARCHTOOL` | optional | Tool-group toggle (set `False` to disable the index/search/pipelines/security tools). Default `True`. |
| `INGESTTOOL` | optional | Tool-group toggle for `opensearch_reindex_from_kg`. Default `True`. |
| `MCP_TOOL_MODE` | optional | `condensed` \| `verbose` \| `both` \| `intent` (inherited from agent-utilities). |

## MCP Tools

| Tool | Group | Purpose |
|------|-------|---------|
| `opensearch_create_index` | index | Create an index (idempotent) |
| `opensearch_update_mapping` | index | Merge field mappings |
| `opensearch_manage_alias` | index | Add/remove/swap aliases |
| `opensearch_get_aliases` | index | Read-only alias inspection |
| `opensearch_update_settings` | index | Update dynamic index settings |
| `opensearch_rollover` | index | Roll a write alias to a new backing index |
| `opensearch_delete_index` | index | Delete an index |
| `opensearch_search` | search | BM25 lexical search (capped at 100 hits) |
| `opensearch_knn_search` | search | k-NN vector search (typed error — plugin disabled) |
| `opensearch_hybrid_search` | search | Lexical + vector hybrid |
| `opensearch_ingest_pipeline` | pipelines | Get/put an ingest pipeline |
| `opensearch_read_dls_rules` | security | Read-only: one role's DLS query |
| `opensearch_apply_dls_bundle` | security | Validate + apply a CA-16/26-rendered bundle |
| `opensearch_reindex_from_kg` | ingest | Trigger-only: records an `:IndexingRun` node |

## Documentation
See `docs/` for architecture, configuration, and deployment notes, and
`AGENTS.md` for domain-specific traps (the calling-principal invariant, the
k-NN-disabled degrade path, and the DLS-bundle-never-hand-authored rule).
