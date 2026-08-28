---
name: opensearch-index-operations
skill_type: skill
description: >-
  Administer OpenSearch (CA-50 search tier) indices via the opensearch-mcp MCP
  server's index tool group — create indices, update mappings, manage/swap
  aliases, update index settings, roll an alias over to a new backing index,
  and delete indices. Use when the agent must provision or reshape the
  derived, KG-rebuildable search index layer. Do NOT use for querying data
  (use opensearch-search) or for pushing KG state into the index (use
  opensearch-kg-ingestion, which only triggers CA-24's rebuild — this package
  never performs the reindex itself).
license: MIT
tags: [opensearch, search, index, mcp]
metadata:
  author: Genius
  version: '0.1.0'
---
# OpenSearch Index Operations

Create and administer OpenSearch indices/aliases/settings for the CA-50
search tier. The index is a fully derived, rebuildable projection of the KG
(DEC-CA-01) — this skill never touches the KG's own source-of-truth data,
only the search-tier's own admin/lifecycle state.

## When to use
- Create a new index with a mapping (`opensearch_create_index`).
- Merge new field mappings into an existing index (`opensearch_update_mapping`).
- Add/remove/swap aliases atomically (`opensearch_manage_alias`), or inspect
  current aliases (`opensearch_get_aliases`).
- Tune dynamic index settings, e.g. `refresh_interval`/replica count
  (`opensearch_update_settings`).
- Roll a write alias over to a new backing index once size/age conditions are
  met (`opensearch_rollover`).
- Remove an index entirely (`opensearch_delete_index`) — safe because the
  index is fully rebuildable from the KG.

## When NOT to use
- Querying documents → `opensearch-search`.
- Triggering a KG-driven rebuild → `opensearch-kg-ingestion`
  (`opensearch_reindex_from_kg`); this skill's tools never populate an index
  with data, only shape its schema/lifecycle.
- Reading or applying document-level-security rules → the `security` tool
  group (`opensearch_read_dls_rules`/`opensearch_apply_dls_bundle`), not this
  skill.

## Prerequisites & environment
Connect via the `mcp-client` skill against the **`opensearch-mcp`** MCP
server. Every call — including these index-admin tools — runs as the calling
principal's own delegated OpenSearch credential; there is no service-level
fallback (see `opensearch-mcp`'s `AGENTS.md`).

| Variable | Required | Notes |
|----------|----------|-------|
| `OPENSEARCH_URL` | recommended | Bare OpenSearch origin. Defaults to `http://localhost:9200`. |
| `ENABLE_DELEGATION` / `OIDC_CONFIG_URL` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET_REF` | ✅ | Shared agent-utilities MCP OIDC-delegation surface — required for ANY tool in this package to authenticate. |
| `OPENSEARCH_KEYCLOAK_CLIENT_ID` | optional | Delegated-token audience. Defaults to `opensearch`. |
| `OPENSEARCH_TLS_PROFILE` / `OPENSEARCH_TLS_PROFILE_REF` | optional | Named outbound TLS trust policy. |

## Tools

| Tool | Purpose |
|------|---------|
| `opensearch_create_index` | Create an index (idempotent — `already_exists: true` if it exists) |
| `opensearch_update_mapping` | Merge field mappings into an existing index |
| `opensearch_manage_alias` | Add/remove/swap aliases atomically |
| `opensearch_get_aliases` | Read-only alias inspection |
| `opensearch_update_settings` | Update dynamic index settings |
| `opensearch_rollover` | Roll a write alias to a new backing index |
| `opensearch_delete_index` | Delete an index (safe — the index is rebuildable) |

## Failure modes to expect
- A non-2xx OpenSearch response raises a typed `OpenSearchApiError`, never a
  silent empty success.
- `opensearch_create_index` against an already-existing index returns
  `already_exists: true` rather than raising (idempotent per this package's
  contract).
- `opensearch_rollover`/`opensearch_delete_index` are typed `OntologyAction`s
  per DEC-CA-07 (once `ActionSpec` lands fleet-wide) — never auto-triggered
  by this package's own logic.
