"""
Schemathesis contract tests: fuzz the CRUD surface of the API against its own
OpenAPI schema (no 5xx allowed, responses must match the declared schema).

AI-backed endpoints are excluded — they call external model providers and are
covered by the mocked tests in test_recipes.py.
"""
from __future__ import annotations

import pytest
import schemathesis
from hypothesis import settings
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import response_schema_conformance
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.database import get_session
from app.main import app

_AI_PATHS = r"(from-url|from-text|enhance|suggest|recommend)"

schema = schemathesis.openapi.from_asgi("/openapi.json", app).exclude(
    path_regex=_AI_PATHS
)


@pytest.fixture(autouse=True)
def _in_memory_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.pop(get_session, None)
    SQLModel.metadata.drop_all(engine)


@schema.parametrize()
@settings(max_examples=20, deadline=None)
def test_api_contract(case):
    response = case.call()
    # Some Pydantic validators (blank-string / whitespace rules) are stricter
    # than the published OpenAPI schema, so schema-compliant fuzzed input may
    # legitimately get a 422 — don't fail on positive-data rejection.
    case.validate_response(
        response,
        checks=[not_a_server_error, response_schema_conformance],
    )
