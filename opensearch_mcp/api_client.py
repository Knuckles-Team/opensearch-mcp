"""Public client facade for opensearch_mcp."""

from opensearch_mcp.api.api_client_opensearch import OpenSearchApi, OpenSearchApiError

__version__ = "0.1.0"

__all__ = ["Api", "OpenSearchApiError"]


class Api(OpenSearchApi):
    """Authenticated OpenSearch client — always the calling principal's token."""

    pass
