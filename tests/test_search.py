"""Search-size cap and k-NN-disabled degrade path, exercised against the real
``OpenSearchApi`` class with its low-level ``opensearchpy`` client mocked out
(no network) — never against ``auth.get_client()``, per this package's own
test-only-escape-hatch rule (see ``api/api_client_opensearch.py``)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from opensearch_mcp.api.api_client_base import OpenSearchApiError
from opensearch_mcp.api.api_client_opensearch import OpenSearchApi


def _api() -> OpenSearchApi:
    return OpenSearchApi(
        "https://opensearch.example", _test_basic_auth=("test-user", "test-pass")
    )


def test_search_caps_size_at_100():
    api = _api()
    api._client = MagicMock()
    api._client.search.return_value = {"hits": {"hits": []}}

    api.search("kg-*", {"match_all": {}}, size=10_000)

    _, kwargs = api._client.search.call_args
    assert kwargs["body"]["size"] == 100


def test_search_rejects_negative_size_by_flooring_at_zero():
    api = _api()
    api._client = MagicMock()
    api._client.search.return_value = {"hits": {"hits": []}}

    api.search("kg-*", {"match_all": {}}, size=-5)

    _, kwargs = api._client.search.call_args
    assert kwargs["body"]["size"] == 0


def test_knn_search_translates_plugin_disabled_error_to_named_typed_error():
    from opensearchpy.exceptions import TransportError

    api = _api()
    api._client = MagicMock()
    api._client.search.side_effect = TransportError(
        400,
        "search_phase_execution_exception",
        {
            "error": {
                "root_cause": [
                    {
                        "reason": (
                            'illegal_state_exception: "KNN plugin is disabled. '
                            'To enable update knn.plugin.enabled setting to true"'
                        )
                    }
                ]
            }
        },
    )

    with pytest.raises(OpenSearchApiError, match="k-NN plugin is disabled"):
        api.knn_search("kg-vectors", "embedding", [0.1, 0.2, 0.3], k=5)


def test_knn_search_other_errors_pass_through_as_typed_error_not_knn_message():
    from opensearchpy.exceptions import NotFoundError

    api = _api()
    api._client = MagicMock()
    api._client.search.side_effect = NotFoundError(404, "index_not_found_exception", {})

    with pytest.raises(OpenSearchApiError) as excinfo:
        api.knn_search("kg-vectors", "embedding", [0.1], k=5)
    assert "k-NN plugin is disabled" not in str(excinfo.value)


def test_create_index_is_idempotent_on_already_exists():
    from opensearchpy.exceptions import TransportError

    api = _api()
    api._client = MagicMock()
    api._client.indices.create.side_effect = TransportError(
        400,
        "resource_already_exists_exception",
        {"error": {"type": "resource_already_exists_exception"}},
    )

    result = api.create_index("kg-existing")

    assert result["already_exists"] is True
