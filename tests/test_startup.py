"""Import-time smoke test — every module in the package must import cleanly."""


def test_startup():
    import opensearch_mcp.api_client  # noqa: F401
    import opensearch_mcp.auth  # noqa: F401
    import opensearch_mcp.kg_ingest  # noqa: F401
    import opensearch_mcp.mcp.mcp_opensearch  # noqa: F401
    import opensearch_mcp.mcp_server  # noqa: F401
    import opensearch_mcp.models  # noqa: F401
