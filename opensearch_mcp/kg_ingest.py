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
(marking the rebuild REQUEST) through the required
``agent_utilities.knowledge_graph.memory.native_ingest`` write authority, and
returns immediately with a run id — it never performs the reindex itself.
CA-24 is the sole owner of actually walking the KG and populating OpenSearch;
this tool's contract is satisfied entirely by the request being durably
recorded, matching this lane's Non-goals: "this package's
opensearch_reindex_from_kg only *triggers* that rebuild, never implements the
sync loop itself."
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_utilities.knowledge_graph.memory.native_ingest import (
    ingest_entities as _native_ingest_entities,
)
from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger("opensearch_mcp.kg")

_SOURCE = "opensearch-mcp"
_DOMAIN = "opensearch"


def ingest_entities(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
    *,
    client: Any | None = None,
    graph: str | None = None,
) -> dict[str, int]:
    """Write canonical typed nodes and relationships through native ingestion.

    Thin wrapper kept for parity with the fleet's other ``kg_ingest.py``
    modules (egeria-mcp/lakekeeper-mcp) — used here only for
    ``:IndexingRun`` trigger records, never for a bulk catalog walk (see
    module docstring for why).
    """
    return _native_ingest_entities(
        entities,
        relationships,
        source=_SOURCE,
        domain=_DOMAIN,
        client=client,
        graph=graph,
    )


def _indexing_run_id(index_pattern: str, run_uuid: str) -> str:
    return f"opensearch:IndexingRun:{index_pattern}:{run_uuid}"


def record_indexing_run(
    index_pattern: str,
    *,
    requested_by: str | None = None,
    client: Any | None = None,
    graph: str | None = None,
) -> dict[str, Any]:
    """Record ONE ``:IndexingRun`` node marking a reindex request.

    Never performs the reindex — CA-24 does, reading this node (or its own
    trigger queue) as the work item. Never partially commits:
    ``native_ingest.ingest_entities`` raises ``NativeIngestError`` rather
    than silently acking a failed write, so a caller can trust that a
    returned ``run_id`` really was durably recorded.
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
    ingest_entities([entity], None, client=client, graph=graph)
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
        return record_indexing_run(index_pattern)
