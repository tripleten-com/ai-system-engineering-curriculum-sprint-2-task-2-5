"""Coldline.

===================

File:              tests/contract/test_api_versioning.py
Component:         Contract tests — API versioning and idempotency
Purpose:           Verify one added version, unbroken v1 contracts, and replay behavior.
Interacts With:    The running API and PostgreSQL
Sprint/Task:       Sprint 2 — Project 2 / Task 2.5
Concepts:          Versioning, idempotent writes, duplicate side effects
Tools:             Python 3.12, pytest, httpx, Docker Compose
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import yaml

from api.v2_contracts import (
    DOCUMENTS_OPERATION_ID,
    OPERATION_PATHS,
    READINGS_OPERATION_ID,
    SUPPORTED_OPERATION_IDS,
)
from tests.runtime_config import host_port

TASK_ROOT = Path(__file__).resolve().parents[2]
# Assessed: a fresh starter mounts no v2 router and is supposed to fail these.
# Runtime: they drive the running API and read PostgreSQL.
pytestmark = [pytest.mark.runtime, pytest.mark.assessed]

COMPOSE = (
    "docker",
    "compose",
    "--profile",
    "observability",
    "--profile",
    "localstack",
)
TENANT = "tenant-versioning"


def _api() -> str:
    """Return the API base URL, honoring the documented host-port override."""
    return f"http://localhost:{host_port('COLDLINE_API_HOST_PORT', 8000)}"


def _psql(statement: str) -> str:
    """Run one bounded psql statement and return its trimmed output."""
    result = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "coldline",
            "-d",
            "coldline",
            "-tAc",
            statement,
        ],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def selected_operation_id() -> str:
    """Return the recorded operation or fail with actionable guidance."""
    document = yaml.safe_load((TASK_ROOT / "submission.yaml").read_text(encoding="utf-8"))
    answers = document.get("answers") if isinstance(document, dict) else None
    recorded = answers.get("selected_operation_id", "") if isinstance(answers, dict) else ""
    if recorded not in SUPPORTED_OPERATION_IDS:
        pytest.fail(
            "answers.selected_operation_id must be one of "
            f"{list(SUPPORTED_OPERATION_IDS)}; found {recorded!r}"
        )
    return str(recorded)


def _document_payload(document_id: str) -> dict[str, Any]:
    """Return one version 2 document request body."""
    return {
        "document": {
            "document_id": document_id,
            "title": "Versioning procedure",
            "body": (
                "Record the operator badge and the time in the loading log. This body is "
                "long enough to produce more than one chunk."
            ),
            "access": {"tenant_id": TENANT, "access_tier": "standard"},
            "provenance": {
                "source_uri": f"s3://coldline-corpus/source/{document_id}.md",
                "custodian": "Versioning desk",
                "revision": "r1",
                "recorded_at": datetime(2026, 6, 1, tzinfo=UTC).isoformat(),
            },
        },
        "source_system": "dock-terminal-7",
    }


def _reading_payload(reading_id: str) -> dict[str, Any]:
    """Return one version 2 reading request body."""
    return {
        "reading": {
            "reading_id": reading_id,
            "shipment_id": "shipment-versioning",
            "temperature_c": 9.4,
            "allowed_min_c": 2.0,
            "allowed_max_c": 8.0,
            "recorded_at": datetime(2026, 6, 1, tzinfo=UTC).isoformat(),
        },
        "reported_by": "operator-4471",
    }


def _fixture(operation_id: str, suffix: str) -> tuple[str, dict[str, Any], str, int]:
    """Return the path, body, row-count query, and expected status for one operation."""
    if operation_id == DOCUMENTS_OPERATION_ID:
        document_id = f"ver-{suffix}"
        return (
            OPERATION_PATHS[operation_id],
            _document_payload(document_id),
            f"SELECT count(*) FROM documents WHERE document_id = '{document_id}'",
            201,
        )
    reading_id = f"ver-{suffix}"
    exception_query = (
        f"SELECT count(*) FROM exceptions WHERE reading->>'reading_id' = '{reading_id}'"
    )
    return OPERATION_PATHS[operation_id], _reading_payload(reading_id), exception_query, 202


def _cleanup(suffixes: list[str]) -> None:
    """Remove only the rows and claims this run created."""
    for suffix in suffixes:
        identifier = f"ver-{suffix}"
        _psql(f"DELETE FROM chunks WHERE document_id = '{identifier}'")
        _psql(f"DELETE FROM documents WHERE document_id = '{identifier}'")
        _psql(f"DELETE FROM exceptions WHERE reading->>'reading_id' = '{identifier}'")
    _psql("DELETE FROM idempotency_claims WHERE idempotency_key LIKE 'ver-key-%'")


def test_exactly_one_version_two_path_is_published() -> None:
    """One versioned extension, and it is the one recorded."""
    recorded = selected_operation_id()
    with httpx.Client(timeout=30.0) as client:
        try:
            schema = client.get(f"{_api()}/openapi.json")
        except httpx.HTTPError as exc:
            pytest.fail(f"could not reach the API at {_api()}: {exc}")
    assert schema.status_code == 200, schema.text
    published = sorted(path for path in schema.json()["paths"] if path.startswith("/api/v2/"))
    assert published, (
        "no /api/v2/ path is published, so no versioned extension is mounted; return a router "
        "from build_v2_router in src/api/extensions/wiring.py"
    )
    assert published == [OPERATION_PATHS[recorded]], (
        f"exactly one versioned path is expected for {recorded!r}; found {published}"
    )


def test_version_one_contracts_are_unbroken() -> None:
    """Existing consumers must keep working, byte for byte where it matters."""
    selected_operation_id()
    reading_id = f"v1-{uuid4().hex[:10]}"
    document_id = f"v1-{uuid4().hex[:10]}"
    try:
        with httpx.Client(timeout=30.0) as client:
            reading = client.post(
                f"{_api()}/api/v1/readings",
                json=_reading_payload(reading_id)["reading"],
            )
            assert reading.status_code == 202, reading.text
            body = reading.json()
            assert set(body) == {"exception_id", "state", "status_url"}, (
                f"the v1 reading response gained or lost a field: {sorted(body)}"
            )
            assert body["state"] == "QUEUED"

            document = client.post(
                f"{_api()}/api/v1/documents",
                json=_document_payload(document_id)["document"],
            )
            assert document.status_code == 201, document.text
            assert set(document.json()) == {"document", "chunk_ids"}, (
                f"the v1 document response gained or lost a field: {sorted(document.json())}"
            )

            # A v1 caller sends no idempotency key and must not be required to.
            assert "Idempotency-Key" not in reading.request.headers
    finally:
        _psql(f"DELETE FROM chunks WHERE document_id = '{document_id}'")
        _psql(f"DELETE FROM documents WHERE document_id = '{document_id}'")
        _psql(f"DELETE FROM exceptions WHERE reading->>'reading_id' = '{reading_id}'")


def test_the_versioned_write_requires_an_idempotency_key() -> None:
    """A protected write path must refuse a request that carries no key."""
    recorded = selected_operation_id()
    path, payload, _, _ = _fixture(recorded, f"nokey-{uuid4().hex[:8]}")
    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{_api()}{path}", json=payload)
    assert response.status_code == 400, (
        f"a request without an Idempotency-Key header returned {response.status_code}; the "
        "protected write path must reject it as a client error"
    )
    assert "Idempotency-Key" in response.json()["detail"]


def test_a_replayed_write_returns_the_stored_response_and_writes_once() -> None:
    """The whole point: the same key twice, one side effect."""
    recorded = selected_operation_id()
    suffix = f"replay-{uuid4().hex[:8]}"
    path, payload, count_query, expected_status = _fixture(recorded, suffix)
    key = f"ver-key-{uuid4().hex}"
    try:
        with httpx.Client(timeout=30.0) as client:
            first = client.post(f"{_api()}{path}", json=payload, headers={"Idempotency-Key": key})
            assert first.status_code == expected_status, first.text
            assert _psql(count_query) == "1", "the first request did not write exactly one row"

            second = client.post(f"{_api()}{path}", json=payload, headers={"Idempotency-Key": key})

        assert second.status_code == first.status_code, (
            f"the replay returned {second.status_code}, not the stored {first.status_code}"
        )
        assert second.json() == first.json(), (
            "the replay returned a different body than the stored response"
        )
        assert _psql(count_query) == "1", (
            "the replay performed a second write; the stored response must be returned "
            "without re-running the operation"
        )
    finally:
        _cleanup([suffix])


def test_a_different_key_still_performs_a_new_write() -> None:
    """Idempotency must not become a blanket block on writing."""
    recorded = selected_operation_id()
    first_suffix = f"newa-{uuid4().hex[:8]}"
    second_suffix = f"newb-{uuid4().hex[:8]}"
    path, first_payload, first_count, expected_status = _fixture(recorded, first_suffix)
    _, second_payload, second_count, _ = _fixture(recorded, second_suffix)
    try:
        with httpx.Client(timeout=30.0) as client:
            first = client.post(
                f"{_api()}{path}",
                json=first_payload,
                headers={"Idempotency-Key": f"ver-key-{uuid4().hex}"},
            )
            second = client.post(
                f"{_api()}{path}",
                json=second_payload,
                headers={"Idempotency-Key": f"ver-key-{uuid4().hex}"},
            )
        assert first.status_code == expected_status, first.text
        assert second.status_code == expected_status, second.text
        assert _psql(first_count) == "1"
        assert _psql(second_count) == "1", (
            "a distinct request with a distinct key was not written; the mechanism is "
            "blocking legitimate writes"
        )
    finally:
        _cleanup([first_suffix, second_suffix])


def test_the_claim_is_recorded_durably() -> None:
    """A replay after a restart must still work, so the claim has to be stored."""
    recorded = selected_operation_id()
    suffix = f"claim-{uuid4().hex[:8]}"
    path, payload, _, expected_status = _fixture(recorded, suffix)
    key = f"ver-key-{uuid4().hex}"
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{_api()}{path}", json=payload, headers={"Idempotency-Key": key}
            )
        assert response.status_code == expected_status, response.text

        stored = _psql(
            "SELECT operation_id || '|' || (completed_at IS NOT NULL)::text "
            f"FROM idempotency_claims WHERE idempotency_key = '{key}'"
        )
        assert stored == f"{recorded}|true", (
            f"the idempotency claim is not stored as a completed claim for {recorded!r}; "
            f"found {stored!r}. An in-memory claim cannot survive a restart."
        )
    finally:
        _cleanup([suffix])


def test_the_unselected_operation_was_not_also_implemented() -> None:
    """Exactly one write path is protected in this Task."""
    recorded = selected_operation_id()
    other = READINGS_OPERATION_ID if recorded == DOCUMENTS_OPERATION_ID else DOCUMENTS_OPERATION_ID
    suffix = f"other-{uuid4().hex[:8]}"
    path, payload, _, _ = _fixture(other, suffix)
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{_api()}{path}", json=payload)
    finally:
        # The probe writes nothing when the path is absent, which is the
        # expected outcome. Clean up anyway so a run that does write leaves the
        # database exactly as it found it.
        _cleanup([suffix])
    assert response.status_code == 404, (
        f"{path} answered {response.status_code}; this Task extends exactly one versioned "
        "endpoint, and the other must remain unpublished"
    )
