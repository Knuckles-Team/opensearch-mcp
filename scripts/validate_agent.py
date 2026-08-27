#!/usr/bin/env python3
"""Validate opensearch-mcp end-to-end through the actual MCP tool-call path.

Builds the real FastMCP server instance (``get_mcp_instance()``) and drives
it through ``fastmcp.Client`` over the in-memory transport — the same call
path an MCP client (Claude, the multiplexer) actually uses (tool discovery +
``call_tool``), not a shortcut around it.

Requires OIDC delegation to be configured (``ENABLE_DELEGATION``,
``OIDC_CONFIG_URL``, ``OIDC_CLIENT_ID``, ``OIDC_CLIENT_SECRET_REF``) AND a real
Bearer token on the inbound request — this package has no other credential
path (see ``auth.py``). Because this harness runs the server over FastMCP's
in-memory transport (no real inbound HTTP request), the delegated-auth
context var is never populated, so every tool call below is EXPECTED to
raise ``OpenSearchApiError`` naming the missing delegation — that failure
IS this script's positive proof that the calling-principal invariant holds
(see the printed assertion at the end). For a live, credentialed round-trip
against the deployed cluster, see this package's ``AGENTS.md`` and its
test-only ``OpenSearchApi(_test_basic_auth=...)`` escape hatch instead.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


async def main() -> int:
    try:
        from fastmcp import Client

        from opensearch_mcp.mcp_server import get_mcp_instance
    except ImportError as e:
        print(f"Import failed: {type(e).__name__}: {e}")
        print("Please install dependencies via `pip install .[mcp]`")
        return 1

    print("Building opensearch-mcp FastMCP server instance...")
    mcp, _args, _middlewares = get_mcp_instance()

    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools)
        print(f"Discovered {len(names)} tools.")
        opensearch_tools = [n for n in names if n.startswith("opensearch_")]
        print(f"opensearch_* tools ({len(opensearch_tools)}): {opensearch_tools}")
        if not opensearch_tools:
            print("FAIL: no opensearch_* tools discovered")
            return 1

        expected_groups = {
            "opensearch_create_index",
            "opensearch_search",
            "opensearch_knn_search",
            "opensearch_apply_dls_bundle",
            "opensearch_read_dls_rules",
            "opensearch_reindex_from_kg",
        }
        missing = expected_groups - set(opensearch_tools)
        if missing:
            print(f"FAIL: expected tools missing from discovery: {sorted(missing)}")
            return 1

        print(
            "\nCalling opensearch_search with no delegated principal token present..."
        )
        try:
            result = await client.call_tool(
                "opensearch_search",
                {"index": "kg-ca43-proof", "query": {"match_all": {}}, "size": 1},
            )
            payload = result.data if hasattr(result, "data") else result
            print(
                "UNEXPECTED: opensearch_search succeeded with no delegated principal "
                f"token — this would be a P8-failing regression: {json.dumps(payload, default=str)}"
            )
            return 1
        except Exception as exc:  # noqa: BLE001 - this IS the expected/positive path
            message = str(exc)
            print(
                f"EXPECTED failure (calling-principal invariant held): {type(exc).__name__}: {message}"
            )
            if "delegat" not in message.lower() and "principal" not in message.lower():
                print(
                    "FAIL: the failure was not attributable to the missing calling-"
                    "principal token — investigate before trusting this as the "
                    "invariant proof"
                )
                return 1

    print(
        "\nOK: opensearch-mcp validated end-to-end through the MCP tool-call path — "
        "all tool groups discoverable, and the calling-principal invariant held "
        "(no delegated token -> no OpenSearch call, never a silent bypass)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
