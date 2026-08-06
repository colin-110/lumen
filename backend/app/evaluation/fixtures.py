"""Shared golden-dataset fixture ingestion, used by both the retrieval
harness (run.py) and the generation harness (run_generation.py) so the two
don't drift into separate copies of the same isolation/cleanup logic.
"""

from __future__ import annotations

import uuid

from app.evaluation.golden_dataset import DOCUMENTS
from app.services import retrieval
from app.services.qdrant_client import delete_owner_points, init_qdrant

# Stable, deterministic ids so re-running either harness is idempotent and
# never collides with real tenant data (no real owner_id will ever equal
# this fixed UUID5).
_NAMESPACE = uuid.UUID("2f6a2b0e-2b0a-4e2b-9c3a-8f1e0d6a7b10")
EVAL_OWNER_ID = uuid.uuid5(_NAMESPACE, "eval-harness-owner")


def doc_uuid(doc_key: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"doc:{doc_key}")


async def ingest_fixtures() -> None:
    init_qdrant()
    delete_owner_points(str(EVAL_OWNER_ID))
    for doc in DOCUMENTS:
        await retrieval.index_chunks(
            document_id=doc_uuid(doc.doc_key),
            filename=doc.filename,
            owner_id=EVAL_OWNER_ID,
            organization_id=None,
            chunks=[doc.text],
        )


def cleanup_fixtures() -> None:
    delete_owner_points(str(EVAL_OWNER_ID))
