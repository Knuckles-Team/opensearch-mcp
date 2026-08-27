"""Pydantic models for OpenSearch operations."""

from typing import Any

from pydantic import BaseModel, Field


class IndexRef(BaseModel):
    """One OpenSearch index."""

    index: str = Field(description="Index name, e.g. 'kg-homelab-document'.")


class DlsRenderingEntry(BaseModel):
    """One ``renderings.opensearch`` array element from a DEC-CA-04 policy bundle.

    Mirrors the bundle contract's own shape exactly
    (``decisions/DEC-CA-04-principal-and-marking-propagation.md``'s Contract
    section) — this package validates a caller-supplied bundle against this
    shape and never constructs one of these itself.
    """

    index_pattern: str = Field(description="OpenSearch index-pattern glob this rendering targets.")
    role: str = Field(description="OpenSearch security-plugin role name to receive this DLS rule.")
    dls_query: dict[str, Any] = Field(
        description="OpenSearch Query DSL object applied as the role's document-level-security filter."
    )
