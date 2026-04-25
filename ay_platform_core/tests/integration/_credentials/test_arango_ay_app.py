# =============================================================================
# File: test_arango_ay_app.py
# Version: 1
# Path: ay_platform_core/tests/integration/_credentials/test_arango_ay_app.py
# Description: End-to-end usability test for the dedicated ArangoDB app
#              user `ay_app` (R-100-118 v2). Replays the bootstrap logic
#              that `arangodb_init` performs in the compose stack:
#                1. Create the shared application database.
#                2. Create the `ay_app` user with a known password.
#                3. Grant `rw` on the database and on every collection.
#              Then connects AS `ay_app` and verifies that:
#                - CRUD on collections in the granted database succeeds
#                  (the runtime credential is genuinely usable).
#                - The same operations on a foreign database (where
#                  `ay_app` has no grant) are rejected.
#
# @relation implements:R-100-118
# =============================================================================

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from arango import ArangoClient  # type: ignore[attr-defined]
from arango.exceptions import ArangoServerError
from tests.fixtures.containers import ArangoEndpoint, cleanup_arango_database

pytestmark = pytest.mark.integration

_AY_APP_PASSWORD = "ay-app-integration-test-password"


@pytest.fixture(scope="function")
def app_db(arango_container: ArangoEndpoint) -> Iterator[tuple[str, str]]:
    """Bootstrap an isolated `(db_name, ay_app_username)` pair.

    Mirrors what `arangodb_init` does in the compose stack:
      - Create the database.
      - Create the user with the agreed password.
      - Grant `rw` on the database and on every collection.
    Tears down both the database and the user at the end.
    """
    suffix = uuid.uuid4().hex[:8]
    db_name = f"platform_test_{suffix}"
    user_name = f"ay_app_test_{suffix}"

    client = ArangoClient(hosts=arango_container.url)
    sys_db = client.db(
        "_system",
        username=arango_container.username,
        password=arango_container.password,
    )

    sys_db.create_database(db_name)
    sys_db.create_user(username=user_name, password=_AY_APP_PASSWORD, active=True)
    sys_db.update_permission(
        username=user_name, permission="rw", database=db_name
    )
    sys_db.update_permission(
        username=user_name,
        permission="rw",
        database=db_name,
        collection="*",
    )

    try:
        yield (db_name, user_name)
    finally:
        try:
            sys_db.delete_user(user_name, ignore_missing=True)
        except ArangoServerError:
            pass
        cleanup_arango_database(arango_container, db_name)


class TestArangoAyAppUsability:
    """The `ay_app` user SHALL be a working app credential, not just an
    object that exists. Every operation a backbone component performs at
    runtime is exercised here against the same code path components use."""

    def test_can_create_collection_and_round_trip_a_document(
        self,
        arango_container: ArangoEndpoint,
        app_db: tuple[str, str],
    ) -> None:
        db_name, user_name = app_db
        client = ArangoClient(hosts=arango_container.url)
        db = client.db(db_name, username=user_name, password=_AY_APP_PASSWORD)

        coll_name = f"items_{uuid.uuid4().hex[:6]}"
        coll = db.create_collection(coll_name)
        try:
            doc_meta = coll.insert({"_key": "k1", "value": 42})
            assert doc_meta["_key"] == "k1"

            fetched = coll.get("k1")
            assert fetched is not None
            assert fetched["value"] == 42

            coll.delete("k1")
            assert coll.get("k1") is None
        finally:
            db.delete_collection(coll_name, ignore_missing=True)

    def test_can_run_aql_against_granted_database(
        self,
        arango_container: ArangoEndpoint,
        app_db: tuple[str, str],
    ) -> None:
        db_name, user_name = app_db
        client = ArangoClient(hosts=arango_container.url)
        db = client.db(db_name, username=user_name, password=_AY_APP_PASSWORD)

        coll_name = f"aql_{uuid.uuid4().hex[:6]}"
        coll = db.create_collection(coll_name)
        try:
            coll.insert({"_key": "a", "n": 1})
            coll.insert({"_key": "b", "n": 2})
            cursor = db.aql.execute(
                "FOR d IN @@col FILTER d.n >= @threshold "
                "SORT d._key RETURN d._key",
                bind_vars={"@col": coll_name, "threshold": 2},
            )
            assert list(cursor) == ["b"]  # type: ignore[arg-type]
        finally:
            db.delete_collection(coll_name, ignore_missing=True)

    def test_cannot_access_a_foreign_database(
        self,
        arango_container: ArangoEndpoint,
        app_db: tuple[str, str],
    ) -> None:
        """Authorization scope is enforced: `ay_app` has rw on its own DB,
        no permissions at all on a sibling DB."""
        _, user_name = app_db

        # Spin up a second database to which `ay_app` has NO grants.
        foreign_db_name = f"foreign_test_{uuid.uuid4().hex[:8]}"
        client = ArangoClient(hosts=arango_container.url)
        sys_db = client.db(
            "_system",
            username=arango_container.username,
            password=arango_container.password,
        )
        sys_db.create_database(foreign_db_name)

        try:
            # Connecting itself succeeds (auth is db-scoped lazily); the
            # subsequent call SHALL raise.
            foreign_handle = client.db(
                foreign_db_name, username=user_name, password=_AY_APP_PASSWORD
            )
            with pytest.raises(ArangoServerError):
                foreign_handle.collections()
        finally:
            cleanup_arango_database(arango_container, foreign_db_name)

    def test_wrong_password_is_rejected(
        self,
        arango_container: ArangoEndpoint,
        app_db: tuple[str, str],
    ) -> None:
        db_name, user_name = app_db
        client = ArangoClient(hosts=arango_container.url)
        bad = client.db(db_name, username=user_name, password="not-the-password")
        with pytest.raises(ArangoServerError):
            # Any privileged call surfaces the auth failure.
            bad.collections()
