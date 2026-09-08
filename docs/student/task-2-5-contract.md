# Task 2.5 contract — one versioned endpoint, one idempotent write path

Build one router in `src/api/extensions/api_v2.py`, return it from `build_v2_router` in
`src/api/extensions/wiring.py`, and record which operation you built in `submission.yaml`.

## Your two choices

| Operation | Recorded value | Path | Request | Response | Success status |
|---|---|---|---|---|---:|
| Documents | `documents_v2_create` | `POST /api/v2/documents` | `DocumentV2Request` | `DocumentV2Response` | 201 |
| Readings | `readings_v2_accept` | `POST /api/v2/readings` | `ReadingV2Request` | `ReadingV2Response` | 202 |

The contracts live in `src/api/v2_contracts.py` and are protected. Each adds one required field
the v1 contract does not carry — `source_system` and `reported_by` respectively. That field is the
whole evolution, and it is a breaking change for a v1 caller, which is precisely why it needs a
new version instead of an edit to the v1 route.

Implement exactly one. Publishing both fails: the check reads `/openapi.json` and requires exactly
one `/api/v2/` path, the one you recorded.

## Do not touch version 1

`src/api/routes.py` is protected. The v1 checks assert the existing responses still carry exactly
their original field sets and status codes, and that a v1 caller is never required to send an
idempotency key. Add a version; do not evolve a published one in place.

## Applying the supplied idempotency handler

`src/api/idempotency.py` supplies `IdempotencyHandler`. Construct one with the store and your
operation identifier, then hand it your write as a callable:

```python
handler = IdempotencyHandler(store, operation_id=DOCUMENTS_OPERATION_ID)


@router.post(DOCUMENTS_V2_PATH, response_model=DocumentV2Response, status_code=201)
async def create(payload: DocumentV2Request, request: Request, response: Response) -> object:
    async def operation() -> tuple[int, DocumentV2Response]:
        chunks = await documents.create(payload.document)
        return 201, DocumentV2Response(
            document_id=payload.document.document_id,
            chunk_count=len(chunks),
            source_system=payload.source_system,
        )

    return await handler.run(request, response, operation)
```

The handler decides whether to call `operation` at all. That ordering is the mechanism: on a
replay it returns the stored response and never runs the write. Read `src/domain/idempotency.py`
for why the claim is taken *before* the write and the response recorded *after* it.

Do not build your own store, lock, or cache. Do not add a concurrency requirement the Task does
not ask for.

The supplied store retains keys until its database is reset; there is no configurable expiry.
A concurrent request can receive 409 while the first request is in flight and may retry later.
Keys identify an operation, not a request-body hash: reuse a key only for the same request.
Reusing it with another body for the same operation replays the earlier response. The scaffold
does not detect that misuse. A process failure after a write but before response recording can
leave a claim in flight; this local exercise does not establish crash-safe exactly-once delivery.

## What the checks verify

| Check | What it looks at |
|---|---|
| exactly one version | `/openapi.json` publishes one `/api/v2/` path, matching your recorded operation |
| v1 unbroken | the v1 reading and document responses keep their exact field sets and status codes |
| key required | a request with no `Idempotency-Key` header answers 400 |
| replay | the same key twice returns the same status and body, and PostgreSQL still holds exactly one row |
| new writes still work | a different key with a different payload writes a second row, so the mechanism is not a blanket block |
| durable claim | the completed claim is a row in `idempotency_claims`, so a replay survives a restart |
| one path only | the operation you did not choose answers 404 |

Run them with `poe versioning`, or the whole public gate with `poe verify`. Both rebuild the image
first, because your router runs inside the API container.

## Permitted paths

- `src/api/extensions/api_v2.py`
- `src/api/extensions/wiring.py`
- anything else you add under `src/api/extensions/`
- anything you add under `tests/student/`
- `submission.yaml`
