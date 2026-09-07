"""Coldline.

===================

File:              src/api/extensions/api_v2.py
Component:         API — Version 2 router (student implementation)
Purpose:           Add exactly one versioned write endpoint and protect its write path.
Interacts With:    api/v2_contracts.py, api/idempotency.py, the wiring factory
Sprint/Task:       Sprint 2 — Project 2 / Task 2.5
Concepts:          API versioning, idempotent writes
Tools:             Python 3.12, FastAPI

This file is student-editable. Build one router here and return it from
`build_v2_router` in `src/api/extensions/wiring.py`.

Two operations are supported. Implement exactly one and record its identifier
in `answers.selected_operation_id`:

| Operation | Path | Request | Response |
|---|---|---|---|
| `documents_v2_create` | `POST /api/v2/documents` | `DocumentV2Request` | `DocumentV2Response` |
| `readings_v2_accept` | `POST /api/v2/readings` | `ReadingV2Request` | `ReadingV2Response` |

The contracts are published in `src/api/v2_contracts.py` and are protected: you
build the route, not the schema.

What the checks require:

- The v1 routes keep working, unchanged. Do not edit them; add a version.
- Exactly one `/api/v2/...` path exists. Adding both fails.
- The write path is protected by the supplied `IdempotencyHandler`. Apply it,
  do not reimplement it.
- A request without the `Idempotency-Key` header is a client error.
- A repeated request with the same key returns the same status and body and
  performs no second write.

A sketch of the shape, for the documents choice:

```python
def build_documents_v2_router(
    documents: DocumentService, store: IdempotencyStore
) -> APIRouter:
    router = APIRouter()
    handler = IdempotencyHandler(store, operation_id=DOCUMENTS_OPERATION_ID)

    @router.post(DOCUMENTS_V2_PATH, response_model=DocumentV2Response, status_code=201)
    async def create(
        payload: DocumentV2Request, request: Request, response: Response
    ) -> object:
        async def operation() -> tuple[int, DocumentV2Response]:
            chunks = await documents.create(payload.document)
            return 201, DocumentV2Response(...)

        return await handler.run(request, response, operation)

    return router
```

Note that the operation callable performs the write and the handler decides
whether to call it at all. That ordering is what makes the write happen once.
"""
