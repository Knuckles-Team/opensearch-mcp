"""Main FastMCP server and tool registration for opensearch-mcp."""

import sys
from typing import Any

from agent_utilities.core.config import load_config
from agent_utilities.mcp.server_factory import create_mcp_server
from agent_utilities.mcp.verbose_tools import register_tool_surface
from fastmcp.utilities.logging import get_logger
from starlette.requests import Request
from starlette.responses import JSONResponse

from opensearch_mcp.api_client import Api
from opensearch_mcp.auth import get_client
from opensearch_mcp.kg_ingest import register_ingest_tools  # noqa: F401
from opensearch_mcp.mcp.mcp_opensearch import register_opensearch_tools  # noqa: F401

__version__ = "0.1.0"
logger = get_logger(name="opensearch_mcp")


def get_mcp_instance() -> tuple[Any, ...]:
    load_config()
    args, mcp, middlewares = create_mcp_server(
        name="OpenSearch MCP",
        version=__version__,
        instructions=(
            "OpenSearch MCP Server (CA-50 search tier) — index/alias/settings/rollover "
            "admin, BM25/kNN/hybrid search always run as the calling principal so "
            "document-level security applies, ingest-pipeline admin, DLS-bundle "
            "read/apply (never hand-authors a rule — only applies what CA-16/26 "
            "render), and a trigger-only reindex-from-KG tool."
        ),
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "OK"})

    register_tool_surface(
        mcp,
        client_cls=Api,
        get_client=get_client,
        service="opensearch-mcp",
        tools_module=sys.modules[__name__],
    )

    for mw in middlewares:
        mcp.add_middleware(mw)
    return mcp, args, middlewares


def mcp_server() -> None:
    mcp, args, middlewares = get_mcp_instance()
    print(f"OpenSearch MCP v{__version__}", file=sys.stderr)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "streamable-http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    elif args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    mcp_server()
