"""Reindex-trigger record shape: opensearch_reindex_from_kg records an
:IndexingRun node and never performs the reindex itself."""

from __future__ import annotations

from unittest.mock import patch

from opensearch_mcp.kg_ingest import _indexing_run_id, record_indexing_run


def test_indexing_run_id_is_stable_shape():
    run_id = _indexing_run_id("kg-*", "abc123")
    assert run_id == "opensearch:IndexingRun:kg-*:abc123"


def test_record_indexing_run_calls_native_ingest_exactly_once():
    with patch("opensearch_mcp.kg_ingest._native_ingest_entities") as mock_ingest:
        mock_ingest.return_value = {"nodes": 1, "edges": 0}

        result = record_indexing_run("kg-homelab-document", requested_by="ca-e2e")

        assert mock_ingest.call_count == 1
        (entities, relationships), kwargs = mock_ingest.call_args
        assert relationships is None
        assert len(entities) == 1
        entity = entities[0]
        assert entity["node_type"] == "IndexingRun"
        assert entity["indexPattern"] == "kg-homelab-document"
        assert entity["status"] == "requested"
        assert entity["requestedBy"] == "ca-e2e"
        assert kwargs["source"] == "opensearch-mcp"
        assert kwargs["domain"] == "opensearch"

        assert result["index_pattern"] == "kg-homelab-document"
        assert result["status"] == "requested"
        assert "run_id" in result and result["run_id"]
        assert result["node_id"] == entity["id"]


def test_record_indexing_run_never_swallows_a_write_failure():
    """NativeIngestError must propagate — a returned run_id must always mean
    the request was durably recorded."""
    from agent_utilities.knowledge_graph.memory.native_ingest import NativeIngestError

    with patch("opensearch_mcp.kg_ingest._native_ingest_entities") as mock_ingest:
        mock_ingest.side_effect = NativeIngestError("engine unavailable")

        import pytest

        with pytest.raises(NativeIngestError):
            record_indexing_run("kg-*")
