# opensearch-mcp - AGENTS

> Claude Code loads this file via `CLAUDE.md` (`@AGENTS.md` import) — the two stay
> in sync. Edit **this** file, not `CLAUDE.md`.

## Project Structure
- `opensearch_mcp/`: Main server code (API client, MCP tool groups, KG ingest, skills)
- `tests/`: Test suite
- `docs/`: Architecture documentation

## Tech Stack
- Python 3.12+
- agent-utilities >= 2.0.0, <3.0.0
- Model Context Protocol (MCP)
- `opensearch-py` (`opensearchpy.OpenSearch`) against the CA-50 search tier,
  `http://localhost:9200` — the only new dependency this package adds.

## Commands
- `pytest`: Run tests
- `pre-commit run --all-files`: Lint code
- `python -m agent_utilities.mcp.check_env_var_drift --check`: env-var drift gate (must be 0)

## Domain notes (read before touching `auth.py` or `api/api_client_opensearch.py`)

- **The single hardest invariant in this package**, structural, not conventional:
  every OpenSearch request carries the CALLING PRINCIPAL's own bearer token,
  attached fresh on every HTTP call. `auth.get_client()` is the ONLY client
  factory in the package — no tool anywhere accepts or constructs a second one,
  and there is no fallback to a fixed/service credential (a deliberate
  divergence from the fleet's usual delegated-auth pattern, where
  `gitlab-api`/`twenty-mcp` fall through to a fixed token on delegation
  failure — that fallback is exactly what this package forbids). See
  `auth.py`'s module docstring and `api/api_client_base.py`'s
  `_PerCallBearerAuth` for how this is enforced structurally: it is a
  `requests.auth.AuthBase` callable `opensearchpy.RequestsHttpConnection`
  invokes on every outbound request, not a token baked in at construction.
- `OpenSearchApi.__init__` has a `_test_basic_auth` escape hatch used ONLY by
  this package's own live-proof tests, exercising the pre-bundle DLS
  demonstration accounts documented in `services/opensearch/AGENTS.md`
  (`ca-e2e` / `restricted-viewer`). It is never referenced by `auth.py` or by
  any `mcp/*.py` tool — if you ever see it imported from either, that is a
  security regression, not a convenience.
- **k-NN is disabled cluster-wide** (pre-AVX2 homelab nodes — no AVX2-free
  OpenSearch k-NN build exists upstream). `opensearch_knn_search`/
  `opensearch_hybrid_search` exist per this lane's scope but raise a typed,
  named `OpenSearchApiError` (not a bare 500) when the plugin refuses the
  operation — verified live against the deployed cluster (2.19.6): indexing a
  `knn_vector` document and running a `knn` query both fail with
  `illegal_state_exception: "KNN plugin is disabled..."`.
- **`opensearch_apply_dls_bundle` never hand-authors a DLS rule.** It
  validates a caller-supplied CA-16/26-rendered bundle's shape
  (`renderings.opensearch`, `governs: ["M1"]`, `graph`) and applies EXACTLY
  the `dls_query` it is given via OpenSearch's security-plugin role API. A
  malformed bundle (missing `renderings.opensearch`) is rejected with a named
  field error, never partially applied.
- The OpenSearch index is a fully derived, rebuildable projection of the KG
  (DEC-CA-01) — `opensearch_reindex_from_kg` only records an `:IndexingRun`
  trigger node; CA-24 performs the actual walk-and-index. This package never
  ingests OpenSearch's own content back into the KG (that would be ingesting
  a derived copy into its own source of truth).
- OpenSearch's OIDC bearer-token auth (`services/opensearch/AGENTS.md`'s W04
  note) validates a Keycloak `homelab`-realm token directly via its
  `openid_auth_domain`, mapping the token's `roles` claim to OpenSearch
  backend roles — `auth.py` exchanges the MCP-layer caller's token for one
  scoped to the `opensearch` Keycloak client audience via the fleet's shared
  `agent_utilities.mcp.delegated_auth` (RFC 8693), the same mechanism
  `gitlab-api`/`twenty-mcp` use for their non-fallback delegation path.

## ActionSpec / DEC-CA-07 status (as of this package's initial build, 2026-08-26)
`CA-32` (the `ActionSpec` schema extension adding `parameters`/`target_resource`/
`conflict_policy`/`requires_approval`/`approval_class`) has **not** merged onto
`agent-utilities` `main` yet — confirmed by reading
`agent_utilities/knowledge_graph/ontology/connector_manifest.py` (still the
three-field `{id, name, description}` shape). This package's
`connector_manifest.yml` therefore carries only the boilerplate two-field
`actions:` entries every generated manifest gets (`epistemic-answer`,
`run_graph_flow`) — the rich typed-Action declarations for
`opensearch_create_index` / `opensearch_update_mapping` / `opensearch_manage_alias`
/ `opensearch_update_settings` / `opensearch_rollover` / `opensearch_delete_index`
/ `opensearch_apply_dls_bundle` are deferred until CA-32 lands. Every one of
those tools is fully implemented and callable now; only its typed-Action
manifest declaration is pending.

## connector_manifest.yml / ontology bundle generation status

`connector_manifest.yml` and the ontology bundle
(`opensearch_mcp/ontology/{certification.json,shapes/connector.shacl.ttl,
mappings/source.yaml,fixtures/records.json,migrations/manifest.json}`) were
generated via `agent-utilities`'s real generator scripts
(`generate_connector_manifests.py` / `generate_connector_capability_bundles.py`,
`--unsigned`), same shape as every other connector in the fleet — **not**
hand-written. Both scripts require the connector to already be a
**registered** provider (`agent-utilities/deploy/mcp-fleet.registry.yml` for
the manifest generator's server-alias lookup; `workspace.yml`'s
`agent-packages/agents` repository list for the capability-bundle generator's
`_configured_provider_names` check) — `opensearch-mcp` is not registered in
either file yet, and per this lane's explicit contract, registering it is
**not this lane's job**: a coordinator lane (CA-29) does that centrally after
CA-40..46 all report back, to avoid concurrent edits to shared registration
files. To produce real generator output anyway (rather than hand-faking
generated-looking YAML/JSON), this build ran both scripts against **scratch,
throwaway copies** of `mcp-fleet.registry.yml` and `workspace.yml` (one added
`opensearch-mcp` entry each, in `/tmp`, never touching the tracked files) via
their `--registry`/`--workspace` override parameters, and `--bundled-output`
pointed at a scratch directory rather than
`agent_utilities/knowledge_graph/ontology/connector_manifests/` (also never
touched). The generated artifacts under `opensearch_mcp/ontology/` and
`connector_manifest.yml` at repo root are therefore the real deterministic
generator output, reproducible byte-for-byte once the coordinator performs
the real central registration.

**Still blocked, same shape as every other connector's first pass**:
`connector_manifest.yml`'s `ontology.lock` entry (`scripts/
update_ontology_lock.py` requires `ONTOLOGY_RELEASE_SIGNING_PRIVATE_KEY_REF`
key custody, not available in this environment — expected, not a defect in
this package) and `REGISTERED_FEDERATED_IRIS` allowlisting of
`http://knuckles.team/kg/opensearch` (`agent_utilities/knowledge_graph/core/
ontology_federation.py`) are both left to the coordinator's central
registration pass, per this lane's explicit instructions.

## ⛔ Keep the Repository Root Pristine — No Scratch / Temp / Debug Files

**The repository ROOT must contain only canonical project files** (packaging,
config, docs, lockfiles). The only hidden directories allowed at root are
`.git/`, `.github/`, and `.specify/` (plus a local, git-ignored `.venv/`).

**NEVER write any of the following — anywhere in the repo, and ESPECIALLY at the root:**
- One-off / debug / migration scripts: `fix_*.py`, `migrate_*.py`, `refactor_*.py`,
  `replace_*.py`, `update_*.py`, `debug_*.py`, or `test_*.py` **at the root**
  (real tests live in `tests/` only).
- Databases / data dumps: `*.db`, `*.db-wal`, `*.sqlite*`, `*.corrupted`.
- Logs / command output: `*.log`, scratch `*.txt`, `*.orig`, `*.rej`, `*.bak`.
- Build artifacts: `*.tsbuildinfo`, compiled binaries, coverage files.
- AI agent scratch directories: `.agent/`, `.agents/`, `.agent_data/`, `.tmp/`,
  `.hypothesis/`, or any per-tool cache committed to git.
- Any file that is NOT production source, a test in `tests/`, documentation, or
  a recognized config/lockfile.

**Where scratch goes instead:** `~/workspace/scratch/` (experiments),
`~/workspace/reports/` (command output); tests go in `tests/` (pytest).
Before finishing a task, run `git status` and confirm no stray root files were added.

## Working Discipline — think, simplify, stay surgical, verify
- **Think before coding.** State assumptions explicitly; surface options rather
  than silently picking one.
- **Simplicity first.** Minimum code that solves the stated problem.
- **Stay surgical.** Every changed line traces to the task.
- **Verify against a goal.** Prove behavior with a real test or a real call
  against the live OpenSearch deployment, not a mock alone.

## Quality Bar — Leave the Codebase Clean (REQUIRED)
Run `pre-commit run --all-files` and drive it fully green before committing.
Do not silence checks (`# noqa`, `# type: ignore`, `SKIP=`, `--no-verify`) to
force green.

## Working with Git Worktrees (multi-session)
This is a small, individually-owned package repo. Check `git worktree list`
before assuming a shared-worktree convention applies — if single-worktree,
committing on a topic branch in place is fine (confirm the branch first).
