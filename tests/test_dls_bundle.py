"""DLS-bundle shape validation — this package NEVER hand-authors a rule.

This is the lane's explicit negative test: a malformed bundle (missing
``renderings.opensearch``) must be rejected with a NAMED field error, never
partially applied.
"""

from __future__ import annotations

import pytest

from opensearch_mcp.api.api_client_base import OpenSearchApiError
from opensearch_mcp.mcp.mcp_opensearch import _validate_dls_bundle

_GOOD_BUNDLE = {
    "version": "1",
    "generated_from": "epoch-1",
    "governs": ["M1"],
    "graph": "ca_e2e",
    "principals": {},
    "markings": {},
    "renderings": {
        "opensearch": [
            {
                "index_pattern": "kg-*",
                "role": "ca_dls_demo_reader",
                "dls_query": {
                    "bool": {"must_not": {"term": {"marking": "restricted"}}}
                },
            }
        ]
    },
}


def test_valid_bundle_passes_validation():
    validated = _validate_dls_bundle(_GOOD_BUNDLE)
    assert len(validated) == 1
    assert validated[0]["role"] == "ca_dls_demo_reader"


def test_missing_renderings_opensearch_is_rejected():
    bundle = {k: v for k, v in _GOOD_BUNDLE.items() if k != "renderings"}
    with pytest.raises(OpenSearchApiError, match="renderings.opensearch"):
        _validate_dls_bundle(bundle)


def test_renderings_present_but_no_opensearch_key_is_rejected():
    bundle = dict(_GOOD_BUNDLE)
    bundle["renderings"] = {"trino": []}
    with pytest.raises(OpenSearchApiError, match="renderings.opensearch"):
        _validate_dls_bundle(bundle)


def test_empty_opensearch_renderings_list_is_rejected():
    bundle = dict(_GOOD_BUNDLE)
    bundle["renderings"] = {"opensearch": []}
    with pytest.raises(OpenSearchApiError, match="non-empty list"):
        _validate_dls_bundle(bundle)


def test_unrecognized_governs_is_rejected():
    bundle = dict(_GOOD_BUNDLE)
    bundle["governs"] = ["M6"]
    with pytest.raises(OpenSearchApiError, match="governs"):
        _validate_dls_bundle(bundle)


def test_missing_graph_is_rejected():
    bundle = {k: v for k, v in _GOOD_BUNDLE.items() if k != "graph"}
    with pytest.raises(OpenSearchApiError, match="graph"):
        _validate_dls_bundle(bundle)


def test_rendering_entry_missing_required_field_is_rejected():
    bundle = dict(_GOOD_BUNDLE)
    bundle["renderings"] = {
        "opensearch": [{"index_pattern": "kg-*", "role": "ca_dls_demo_reader"}]
    }
    with pytest.raises(OpenSearchApiError, match="dls_query"):
        _validate_dls_bundle(bundle)


def test_bundle_must_be_an_object():
    with pytest.raises(OpenSearchApiError, match="JSON object"):
        _validate_dls_bundle(["not", "a", "dict"])  # type: ignore[arg-type]
