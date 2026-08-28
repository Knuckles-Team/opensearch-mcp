# Opensearch Mcp
## CLI or API | MCP | Agent

![PyPI - Version](https://img.shields.io/pypi/v/opensearch-mcp)
![MCP Server](https://badge.mcpx.dev?type=server 'MCP Server')
![PyPI - Downloads](https://img.shields.io/pypi/dd/opensearch-mcp)
![GitHub Repo stars](https://img.shields.io/github/stars/Knuckles-Team/opensearch-mcp)
![GitHub forks](https://img.shields.io/github/forks/Knuckles-Team/opensearch-mcp)
![GitHub contributors](https://img.shields.io/github/contributors/Knuckles-Team/opensearch-mcp)
![PyPI - License](https://img.shields.io/pypi/l/opensearch-mcp)
![GitHub](https://img.shields.io/github/license/Knuckles-Team/opensearch-mcp)
![GitHub last commit (by committer)](https://img.shields.io/github/last-commit/Knuckles-Team/opensearch-mcp)
![GitHub pull requests](https://img.shields.io/github/issues-pr/Knuckles-Team/opensearch-mcp)
![GitHub closed pull requests](https://img.shields.io/github/issues-pr-closed/Knuckles-Team/opensearch-mcp)
![GitHub issues](https://img.shields.io/github/issues/Knuckles-Team/opensearch-mcp)
![GitHub top language](https://img.shields.io/github/languages/top/Knuckles-Team/opensearch-mcp)
![GitHub language count](https://img.shields.io/github/languages/count/Knuckles-Team/opensearch-mcp)
![GitHub repo size](https://img.shields.io/github/repo-size/Knuckles-Team/opensearch-mcp)
![GitHub repo file count (file type)](https://img.shields.io/github/directory-file-count/Knuckles-Team/opensearch-mcp)
![PyPI - Wheel](https://img.shields.io/pypi/wheel/opensearch-mcp)
![PyPI - Implementation](https://img.shields.io/pypi/implementation/opensearch-mcp)

*Version: 0.1.0*

> **Documentation** — Installation, deployment, and usage across the API, CLI, MCP,
> and A2A agent interfaces are maintained in the
> [official documentation](https://knuckles-team.github.io/opensearch-mcp/).

---

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
deployment (CA-50, `http://localhost:9200`) via the Model Context Protocol —
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
        "OPENSEARCH_URL": "http://localhost:9200",
        "OPENSEARCHTOOL": "True",
        "INGESTTOOL": "True",
        "ENABLE_DELEGATION": "True",
        "OIDC_CONFIG_URL": "http://localhost:8080/realms/homelab/.well-known/openid-configuration",
        "OIDC_CLIENT_ID": "",
        "OIDC_CLIENT_SECRET_REF": "",
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

<!-- ENV-VARS-TABLE:START -->

#### Package environment variables

| Variable | Example | Description |
|----------|---------|-------------|
| `OPENSEARCH_URL` | `http://localhost:9200` |  |
| `ENABLE_DELEGATION` | `True` | opensearch-mcp has NO fixed/service-credential fallback — every request carries the calling principal's own token, exchanged for one scoped to the audience below. These flags are the fleet-shared MCP OIDC-delegation surface (agent_utilities.mcp.server_factory / delegated_auth), not opensearch-mcp-specific, but MUST be enabled for this package's tools to work at all: |
| `OIDC_CONFIG_URL` | `http://localhost:8080/realms/homelab/.well-known/openid-configuration` |  |
| `OIDC_CLIENT_ID` | — |  |
| `OIDC_CLIENT_SECRET_REF` | — |  |
| `OPENSEARCH_KEYCLOAK_CLIENT_ID` | `opensearch` | Audience/scope this package exchanges the caller's token for — defaults to OPENSEARCH_KEYCLOAK_CLIENT_ID if --audience isn't passed at MCP startup. |
| `OPENSEARCH_TLS_PROFILE` | — |  |
| `OPENSEARCH_TLS_PROFILE_REF` | — |  |
| `OPENSEARCHTOOL` | `True` |  |
| `INGESTTOOL` | `True` |  |

#### Inherited agent-utilities variables (apply to every connector)

| Variable | Example | Description |
|----------|---------|-------------|
| `TRANSPORT` | `stdio` | MCP transport: `stdio` \| `streamable-http` \| `sse` |
| `HOST` | `127.0.0.1` | Loopback bind host (set an authenticated ingress explicitly) |
| `PORT` | `8000` | Bind port (HTTP transports) |
| `MCP_TOOL_MODE` | `intent` | Tool surface: `intent` \| `condensed` \| `verbose` \| `both` |
| `MCP_ENABLED_TOOLS` | — | Comma-separated tool allow-list |
| `MCP_DISABLED_TOOLS` | — | Comma-separated tool deny-list |
| `MCP_ENABLED_TAGS` | — | Comma-separated tag allow-list |
| `MCP_DISABLED_TAGS` | — | Comma-separated tag deny-list |
| `EUNOMIA_TYPE` | `none` | Authorization mode: `none` \| `embedded` \| `remote` |
| `EUNOMIA_POLICY_FILE` | `mcp_policies.json` | Embedded Eunomia policy file |
| `EUNOMIA_REMOTE_URL` | — | Remote Eunomia authorization server URL |
| `ENABLE_OTEL` | `False` | Enable OpenTelemetry export |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTLP collector endpoint |
| `MCP_CLIENT_AUTH` | — | Outbound MCP child auth: `oidc-client-credentials` \| `basic` \| `none` |
| `MCP_BASIC_AUTH_USERNAME` | — | HTTP Basic username (`MCP_CLIENT_AUTH=basic`) |
| `MCP_BASIC_AUTH_PASSWORD_REF` | `secret://identity/mcp-basic-password` | Runtime secret reference for HTTP Basic auth (`MCP_CLIENT_AUTH=basic`) |
| `DEBUG` | `False` | Verbose logging |
| `PYTHONUNBUFFERED` | `1` | Unbuffered stdout (recommended in containers) |
| `MCP_URL` | `http://localhost:8000/mcp` | URL of the MCP server the agent connects to |
| `PROVIDER` | `openai` | LLM provider for the agent |
| `MODEL_ID` | `gpt-4o` | Model id for the agent |
| `ENABLE_WEB_UI` | `True` | Serve the AG-UI web interface |

_10 package + 22 inherited variable(s). Auto-generated from `.env.example` + the shared agent-utilities set — do not edit._
<!-- ENV-VARS-TABLE:END -->


| Variable | Required | Notes |
|----------|----------|-------|
| `OPENSEARCH_URL` | recommended | Bare OpenSearch origin. Defaults to `http://localhost:9200`. |
| `ENABLE_DELEGATION` | ✅ | Must be `True` — this package has no other credential path. |
| `OIDC_CONFIG_URL` | ✅ | OIDC discovery document URL (shared agent-utilities MCP surface). |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET_REF` | ✅ | Confidential client used for the RFC 8693 token exchange. |
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

## Available MCP Tools

<!-- MCP-TOOLS-TABLE:START -->

#### Condensed action-routed tools (`MCP_TOOL_MODE=condensed`)

| MCP Tool | Toggle Env Var | Description |
|----------|----------------|-------------|
| `opensearch_apply_dls_bundle` | `OPENSEARCHTOOL` | Apply a CA-16/26-rendered policy bundle's OpenSearch renderings. |
| `opensearch_ingest_pipeline` | `OPENSEARCHTOOL` | Read or define an ingest pipeline. |
| `opensearch_reindex_from_kg` | `INGESTTOOL` | Request a reindex of ``index_pattern`` from the KG's current state. |

#### Verbose 1:1 API-mapped tools (`MCP_TOOL_MODE=verbose` or `both`)

<details>
<summary>18 per-operation tools — one per public API method (click to expand)</summary>

| MCP Tool | Toggle Env Var | Description |
|----------|----------------|-------------|
| `opensearch_apply_dls_bundle_rendering` | `OPEN_SEARCH_APITOOL` | Apply ONE already-validated ``renderings.opensearch`` entry. |
| `opensearch_cluster_health` | `OPEN_SEARCH_APITOOL` | Invoke the cluster_health operation. |
| `opensearch_create_index` | `OPENSEARCHTOOL` | Invoke the create_index operation. |
| `opensearch_delete_index` | `OPENSEARCHTOOL` | Invoke the delete_index operation. |
| `opensearch_get_aliases` | `OPENSEARCHTOOL` | Invoke the get_aliases operation. |
| `opensearch_get_ingest_pipeline` | `OPEN_SEARCH_APITOOL` | Invoke the get_ingest_pipeline operation. |
| `opensearch_hybrid_search` | `OPENSEARCHTOOL` | OpenSearch's native hybrid (lexical + vector) query compound clause. |
| `opensearch_ingest_pipeline__get` | `MUTATINGTOOL` | Read or define an ingest pipeline. |
| `opensearch_ingest_pipeline__put` | `MUTATINGTOOL` | Read or define an ingest pipeline. |
| `opensearch_knn_plugin_enabled` | `OPEN_SEARCH_APITOOL` | Live check of the k-NN plugin's runtime-enabled flag (never assumed). |
| `opensearch_knn_search` | `OPENSEARCHTOOL` | Invoke the knn_search operation. |
| `opensearch_manage_alias` | `OPENSEARCHTOOL` | Apply one or more alias actions (``{"add": {...}}``/``{"remove": {...}}``). |
| `opensearch_put_ingest_pipeline` | `OPEN_SEARCH_APITOOL` | Invoke the put_ingest_pipeline operation. |
| `opensearch_read_dls_rules` | `OPENSEARCHTOOL` | Read one OpenSearch security-plugin role's index permissions/DLS query. |
| `opensearch_rollover` | `OPENSEARCHTOOL` | Invoke the rollover operation. |
| `opensearch_search` | `OPENSEARCHTOOL` | Invoke the search operation. |
| `opensearch_update_mapping` | `OPENSEARCHTOOL` | Invoke the update_mapping operation. |
| `opensearch_update_settings` | `OPENSEARCHTOOL` | Invoke the update_settings operation. |

</details>

_3 action-routed tool(s) · 18 verbose 1:1 tool(s). Each is enabled unless its `<DOMAIN>TOOL` toggle is set false; `MCP_TOOL_MODE` selects the surface (**`intent` default** — the six verb-tools, granular set loaded on demand · `condensed` action-routed · `verbose` 1:1 · `both`). Auto-generated — do not edit._
<!-- MCP-TOOLS-TABLE:END -->

---

## Repository Owners

<img width="100%" height="180em" src="https://github-readme-stats.vercel.app/api?username=example&show_icons=true&hide_border=true&&count_private=true&include_all_commits=true" />

![GitHub followers](https://img.shields.io/github/followers/example)
![GitHub User's stars](https://img.shields.io/github/stars/example)

---

## Contribute

Contributions are welcome! Please ensure code quality by executing local checks before submitting pull requests:
- Format code using `ruff format .`
- Lint code using `ruff check .`
- Validate type-safety with `mypy .`
- Execute test suites using `pytest`


<!-- BEGIN agent-utilities-deployment (generated; do not edit between markers) -->

## Deploy with `agent-utilities-deployment`

Provision this package with the consolidated **`agent-utilities-deployment`**
workflow. It selects an installed-package, editable-source, or immutable-container
path; records only runtime secret and TLS-profile references in `AgentConfig`; and
runs doctor, registration, policy, observability, and rollback gates. Ask your agent
to **"deploy `opensearch-mcp` with agent-utilities-deployment"**.

| Install mode | Command |
|------|---------|
| Installed package | `uv tool install "opensearch-mcp[mcp]"`, then run `opensearch-mcp` |
| Editable source | `uv pip install -e ".[agent]"`, then run `opensearch-mcp` |
| Immutable container | deploy `registry.example.invalid/opensearch-mcp@sha256:<digest>` through the operator-selected orchestrator |

The repository embeds no deployment profile, credential value, certificate path, or
environment-specific endpoint. Supply those at runtime through `AgentConfig` and the
configured secret provider.

<!-- END agent-utilities-deployment -->

<!-- GOVERNED-CAPABILITY:START -->
## Governed capability contract

This package ships a compact canonical skill surface with specialist procedures
kept as referenced workflows. The current MCP tools, skill metadata,
`connector_manifest.yml`, ontology, mappings, shapes, fixtures, migrations,
tool-schema fingerprints, and certification metadata form one versioned
capability contract. Validate them together; do not rely on stale tool names or
historical per-task skill wrappers.

Runtime endpoints, credentials, certificate trust, tenant identity, retention,
and observability policy are deployment inputs and are never packaged values.
See [Configuration, trust, and privacy](docs/configuration.md) before enabling a
network transport, connector ingestion, GraphOS delegation, or trace export.
<!-- GOVERNED-CAPABILITY:END -->
