"""Coldline.

===================

File:              src/api/extensions/wiring.py
Component:         API — Student service wiring
Purpose:           Decide which student implementation the application uses.
Interacts With:    api/bootstrap.py, the document repository, domain services
Sprint/Task:       Sprint 2 — Project 2 / Task 2.3
Concepts:          Composition, dependency injection, bounded student surface
Tools:             Python 3.12, PostgreSQL

This file is student-editable, and it is where the application decides which
implementation of a student-owned collaborator it uses.

Task 2.2's service boundary is settled: the reference orchestration service is
now supplied at `src/api/retrieval_orchestration.py`, and this file wires it
without a choice to make.

Task 2.3's data layer is settled: `build_document_repository` now returns the
supplied reference repository.

Task 2.4's authorization mechanism is settled: `build_access_constraints`
returns the supplied reference tenant-boundary policy.

Task 2.5's factory is `build_v2_router`. It returns `None` in the starter, so
no `/api/v2/...` path exists yet and the versioning and replay checks fail
until you return a router.
"""

import asyncpg
from fastapi import APIRouter

from adapters.persistence.document_repository import PostgresDocumentRepository
from api.document_service import DocumentService
from api.retrieval_orchestration import RetrievalOrchestrationService
from api.use_cases import ReadingApplication
from domain.access import AccessConstraintProvider
from domain.idempotency import IdempotencyStore
from domain.repositories import DocumentRepository
from domain.services import RetrievalOrchestrator
from domain.tenant_authorization import TenantBoundaryAccessConstraints
from ports import Retriever


def build_retrieval_orchestrator(
    retriever: Retriever,
    *,
    top_k: int,
    dense_weight: float,
    citation_limit: int,
) -> RetrievalOrchestrator:
    """Return the supplied reference retrieval-orchestration service."""
    return RetrievalOrchestrationService(
        retriever,
        top_k=top_k,
        dense_weight=dense_weight,
        citation_limit=citation_limit,
    )


def build_document_repository(pool: asyncpg.Pool) -> DocumentRepository | None:
    """Return the supplied reference document repository."""
    return PostgresDocumentRepository(pool)


def build_access_constraints() -> AccessConstraintProvider:
    """Return the access-constraint policy the retrieval adapter applies.

    The adapter applies this inside both query arms, so the constraint decides
    what is *fetched* rather than what is discarded afterwards.
    """
    return TenantBoundaryAccessConstraints()


def build_v2_router(
    *,
    documents: DocumentService,
    readings: ReadingApplication,
    store: IdempotencyStore,
) -> APIRouter | None:
    """Return the version 2 router the application should mount.

    Build one router in `src/api/extensions/api_v2.py` for exactly one of the
    two supported operations and return it here. The composition root mounts
    whatever this returns and mounts nothing when it returns `None`.

    Both collaborators and the idempotency store are handed over already
    composed. Do not construct a pool, a client, or a second store: applying
    the supplied mechanism is the Task.
    """
    return None
