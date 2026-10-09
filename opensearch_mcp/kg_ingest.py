"""Native epistemic-graph ingestion glue for opensearch-mcp — the reindex TRIGGER.

CONCEPT:AU-KG.ingest.enterprise-source-extractor. The record-source twin of
the egeria/jena/lakekeeper connectors, with one deliberate difference: this
package's OpenSearch index is itself a DERIVED PROJECTION of the KG (DEC-CA-01
— the CDC-fed indexer that keeps it in sync is CA-24's territory, explicitly
out of scope here per the lane's Non-goals). So there is no
``ingest_catalog``-style walk of OpenSearch INTO the graph here — that would
be ingesting a derived copy back into its own source of truth, which is
backwards.

What this module DOES provide, per the lane's Design section: a trigger-only
``opensearch_reindex_from_kg`` tool that records an ``:IndexingRun`` node
(marking the rebuild REQUEST) through ``agent_connector_sdk.ingest`` — the
generated epistemic-graph ``SourceIngest`` client, not a local ingestion
helper — and returns immediately with a run id — it never performs the
reindex itself. CA-24 is the sole owner of actually walking the KG and
populating OpenSearch; this tool's contract is satisfied entirely by the
request being durably recorded, matching this lane's Non-goals: "this
package's opensearch_reindex_from_kg only *triggers* that rebuild, never
implements the sync loop itself."
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_connector_sdk.ingest import (
    ChangeSet,
    Entity,
    IngestBinding,
    IngestError,
    KnowledgeIngest,
    current_ingest,
)
from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger("opensearch_mcp.kg")

_BINDING = IngestBinding(connector="opensearch-mcp", stream="opensearch")

_ENTITY_RESERVED_KEYS = frozenset({"id", "node_type"})


def _to_entity(record: dict[str, Any]) -> Entity:
    return Entity(
        id=record.get("id"),
        node_type=record.get("node_type"),
        properties={
            key: value
            for key, value in record.items()
            if key not in _ENTITY_RESERVED_KEYS
        },
    )


async def ingest_entities(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
    *,
    ingest: KnowledgeIngest | None = None,
) -> dict[str, int]:
    """Write canonical typed nodes through the SDK's knowledge-ingest facade.

    Thin wrapper kept for parity with the fleet's other ``kg_ingest.py``
    modules (egeria-mcp/lakekeeper-mcp/caddy-mcp) — used here only for
    ``:IndexingRun`` trigger records, never for a bulk catalog walk (see
    module docstring for why). ``relationships`` is accepted for parity with
    the other connectors' call shape; this package never emits any today.
    """
    if not entities:
        raise IngestError("ingest_entities needs at least one entity")
    change_set = ChangeSet(entities=tuple(_to_entity(entity) for entity in entities))
    service = ingest or current_ingest()
    receipt = await service.submit(_BINDING, change_set)
    return {"nodes": receipt.affected_count, "edges": receipt.relationship_count}


def _indexing_run_id(index_pattern: str, run_uuid: str) -> str:
    return f"opensearch:IndexingRun:{index_pattern}:{run_uuid}"


async def record_indexing_run(
    index_pattern: str,
    *,
    requested_by: str | None = None,
    ingest: KnowledgeIngest | None = None,
) -> dict[str, Any]:
    """Record ONE ``:IndexingRun`` node marking a reindex request.

    Never performs the reindex — CA-24 does, reading this node (or its own
    trigger queue) as the work item. Never partially commits: the SDK's
    ``KnowledgeIngest.submit`` raises ``IngestError`` rather than silently
    acking a failed write, so a caller can trust that a returned ``run_id``
    really was durably recorded.
    """
    run_uuid = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    entity = {
        "id": _indexing_run_id(index_pattern, run_uuid),
        "node_type": "IndexingRun",
        "name": f"reindex {index_pattern} ({run_uuid[:8]})",
        "runId": run_uuid,
        "indexPattern": index_pattern,
        "status": "requested",
        "requestedAt": now,
        "requestedBy": requested_by or "",
        "externalToolId": run_uuid,
    }
    await ingest_entities([entity], None, ingest=ingest)
    return {
        "run_id": run_uuid,
        "index_pattern": index_pattern,
        "status": "requested",
        "requested_at": now,
        "node_id": entity["id"],
    }


def register_ingest_tools(mcp: FastMCP) -> None:
    """Register the trigger-only reindex-from-KG tool."""

    @mcp.tool(
        annotations={
            "title": "Trigger OpenSearch Reindex From KG",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        tags={"ingest", "kg", "kg_ingest"},
    )
    async def opensearch_reindex_from_kg(
        index_pattern: str = Field(
            description="Index or index-pattern this reindex request targets, e.g. 'kg-*'."
        ),
    ) -> dict[str, Any]:
        """Request a reindex of ``index_pattern`` from the KG's current state.

        Returns immediately with a ``run_id`` and records an ``:IndexingRun``
        node — it does NOT itself walk the graph or write to OpenSearch.
        Because the index is fully derived/rebuildable (DEC-CA-01), this is
        always safe to call, including from offset 0 (a full rebuild)."""
        return await record_indexing_run(index_pattern)
