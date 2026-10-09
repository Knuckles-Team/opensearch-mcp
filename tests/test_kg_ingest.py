"""Reindex-trigger record shape: opensearch_reindex_from_kg records an
:IndexingRun node and never performs the reindex itself.

Exercises the real ``ingest_entities``/``record_indexing_run`` seam against a
fake ``agent_connector_sdk.ingest`` transport (no engine required). The real
SDK request builder (``agent_connector_sdk.ingest.request.build_request``)
still runs, so a malformed change set is still caught by the SDK's own
contract, not re-derived here; only the final network commit is faked.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from agent_connector_sdk.ingest import IngestError, KnowledgeIngest
from epistemic_graph.generated.source_ingestion import SourceIngestionRequest

from opensearch_mcp.kg_ingest import _indexing_run_id, record_indexing_run


class _FakeTransport:
    """Records every submitted request; no epistemic-graph engine required."""

    def __init__(self) -> None:
        self.requests: list[SourceIngestionRequest] = []

    async def source_status(self, _connector: str, _stream: str) -> Any:
        return SimpleNamespace(accepted_checkpoint=None)

    async def submit(self, request: SourceIngestionRequest) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            affected_count=len(request.records),
            relationship_count=len(request.relationships),
        )

    async def store_blob(self, _data: bytes) -> str:
        raise AssertionError("opensearch-mcp reindex-trigger ingestion carries no media")


@pytest.fixture
def ingest() -> tuple[KnowledgeIngest, _FakeTransport]:
    transport = _FakeTransport()
    return KnowledgeIngest(transport, loop=None), transport


def test_indexing_run_id_is_stable_shape():
    run_id = _indexing_run_id("kg-*", "abc123")
    assert run_id == "opensearch:IndexingRun:kg-*:abc123"


@pytest.mark.asyncio
async def test_record_indexing_run_writes_one_indexing_run_node(ingest):
    service, transport = ingest

    result = await record_indexing_run(
        "kg-homelab-document", requested_by="ca-e2e", ingest=service
    )

    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert len(request.records) == 1
    assert not request.relationships
    record = request.records[0]
    assert record.mapping_reference.endswith("schema_mappings/IndexingRun")
    assert record.payload["indexPattern"] == "kg-homelab-document"
    assert record.payload["status"] == "requested"
    assert record.payload["requestedBy"] == "ca-e2e"

    assert result["index_pattern"] == "kg-homelab-document"
    assert result["status"] == "requested"
    assert "run_id" in result and result["run_id"]
    assert result["node_id"] == record.record_id


@pytest.mark.asyncio
async def test_record_indexing_run_never_swallows_a_write_failure(ingest):
    """IngestError must propagate — a returned run_id must always mean the
    request was durably recorded."""
    service, transport = ingest

    async def _failing_submit(_request: SourceIngestionRequest) -> Any:
        raise IngestError("engine unavailable")

    transport.submit = _failing_submit  # type: ignore[method-assign]

    with pytest.raises(IngestError):
        await record_indexing_run("kg-*", ingest=service)
