# =============================================================================
# File: repository.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c2_auth/db/repository.py
# Description: ArangoDB access layer for C2-owned collections.
#              All public methods are async, wrapping python-arango
#              (synchronous) with asyncio.to_thread(). R-100-012.
#
# @relation implements:R-100-012
# =============================================================================

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from arango import ArangoClient  # type: ignore[attr-defined]
from arango.database import StandardDatabase

from ay_platform_core.c2_auth.models import SessionInfo, UserInternal

# C2-owned ArangoDB collections (prefixed to avoid cross-component collisions)
COLL_USERS = "c2_users"
COLL_TENANTS = "c2_tenants"
COLL_ROLE_ASSIGNMENTS = "c2_role_assignments"
COLL_SESSIONS = "c2_sessions"


class AuthRepository:
    """Async data-access layer for C2 Auth Service.

    Wraps python-arango synchronous calls via asyncio.to_thread() so the
    FastAPI event loop is never blocked. The public interface is fully async;
    migrate to python-arango-async at this boundary when needed.
    """

    def __init__(self, db: StandardDatabase) -> None:
        self._db = db

    @classmethod
    def from_config(
        cls,
        url: str,
        db_name: str,
        username: str,
        password: str,
    ) -> AuthRepository:
        client = ArangoClient(hosts=url)
        db: StandardDatabase = client.db(db_name, username=username, password=password)
        return cls(db)

    # ---- Initialisation -----------------------------------------------------

    def _ensure_collections_sync(self) -> None:
        for name in (COLL_USERS, COLL_TENANTS, COLL_ROLE_ASSIGNMENTS, COLL_SESSIONS):
            if not self._db.has_collection(name):
                self._db.create_collection(name)

    async def ensure_collections(self) -> None:
        """Create C2-owned collections if absent. Safe to call multiple times."""
        await asyncio.to_thread(self._ensure_collections_sync)

    # ---- Users --------------------------------------------------------------

    def _get_user_by_username_sync(self, username: str) -> UserInternal | None:
        cursor = self._db.aql.execute(
            "FOR u IN @@col FILTER u.username == @username LIMIT 1 RETURN u",
            bind_vars={"@col": COLL_USERS, "username": username},
        )
        docs = list(cursor)  # type: ignore[arg-type]
        if not docs:
            return None
        return UserInternal.model_validate(docs[0])

    async def get_user_by_username(self, username: str) -> UserInternal | None:
        return await asyncio.to_thread(self._get_user_by_username_sync, username)

    def _get_user_by_id_sync(self, user_id: str) -> UserInternal | None:
        doc: dict[str, Any] | None = self._db.collection(COLL_USERS).get(user_id)  # type: ignore[assignment]
        if doc is None:
            return None
        return UserInternal.model_validate(doc)

    async def get_user_by_id(self, user_id: str) -> UserInternal | None:
        return await asyncio.to_thread(self._get_user_by_id_sync, user_id)

    def _insert_user_sync(self, user: UserInternal) -> None:
        doc = user.model_dump(mode="json")
        doc["_key"] = user.user_id
        self._db.collection(COLL_USERS).insert(doc)

    async def insert_user(self, user: UserInternal) -> None:
        await asyncio.to_thread(self._insert_user_sync, user)

    def _update_user_sync(self, user_id: str, patch: dict[str, Any]) -> None:
        self._db.collection(COLL_USERS).update({"_key": user_id, **patch})

    async def update_user(self, user_id: str, patch: dict[str, Any]) -> None:
        await asyncio.to_thread(self._update_user_sync, user_id, patch)

    def _increment_failed_attempts_sync(self, user_id: str) -> int:
        """Atomic AQL increment — avoids TOCTOU under concurrent login attempts."""
        result = self._db.aql.execute(
            """
            FOR u IN @@col
                FILTER u._key == @key
                UPDATE u WITH {failed_attempts: u.failed_attempts + 1} IN @@col
                RETURN NEW.failed_attempts
            """,
            bind_vars={"@col": COLL_USERS, "key": user_id},
        )
        counts = list(result)  # type: ignore[arg-type]
        return int(counts[0]) if counts else 0

    async def increment_failed_attempts(self, user_id: str) -> int:
        return await asyncio.to_thread(self._increment_failed_attempts_sync, user_id)

    def _reset_failed_attempts_sync(self, user_id: str) -> None:
        self._db.collection(COLL_USERS).update(
            {"_key": user_id, "failed_attempts": 0, "locked_until": None}
        )

    async def reset_failed_attempts(self, user_id: str) -> None:
        await asyncio.to_thread(self._reset_failed_attempts_sync, user_id)

    def _lock_user_sync(self, user_id: str, locked_until: datetime) -> None:
        self._db.collection(COLL_USERS).update(
            {"_key": user_id, "locked_until": locked_until.isoformat()}
        )

    async def lock_user(self, user_id: str, locked_until: datetime) -> None:
        await asyncio.to_thread(self._lock_user_sync, user_id, locked_until)

    # ---- Sessions -----------------------------------------------------------

    def _insert_session_sync(
        self,
        jti: str,
        user_id: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._db.collection(COLL_SESSIONS).insert(
            {
                "_key": jti,
                "user_id": user_id,
                "issued_at": issued_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "active": True,
            }
        )

    async def insert_session(
        self,
        jti: str,
        user_id: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        await asyncio.to_thread(self._insert_session_sync, jti, user_id, issued_at, expires_at)

    def _get_session_sync(self, jti: str) -> dict[str, Any] | None:
        result: dict[str, Any] | None = self._db.collection(COLL_SESSIONS).get(jti)  # type: ignore[assignment]
        return result

    async def get_session(self, jti: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_session_sync, jti)

    def _deactivate_session_sync(self, jti: str) -> None:
        self._db.collection(COLL_SESSIONS).update({"_key": jti, "active": False})

    async def deactivate_session(self, jti: str) -> None:
        await asyncio.to_thread(self._deactivate_session_sync, jti)

    def _list_active_sessions_sync(self) -> list[dict[str, Any]]:
        cursor = self._db.aql.execute(
            "FOR s IN @@col FILTER s.active == true SORT s.issued_at DESC RETURN s",
            bind_vars={"@col": COLL_SESSIONS},
        )
        return list(cursor)  # type: ignore[arg-type]

    async def list_active_sessions(self) -> list[SessionInfo]:
        raw = await asyncio.to_thread(self._list_active_sessions_sync)
        return [
            SessionInfo(
                session_id=s["_key"],
                user_id=s["user_id"],
                issued_at=datetime.fromisoformat(s["issued_at"]),
                expires_at=datetime.fromisoformat(s["expires_at"]),
                active=s["active"],
            )
            for s in raw
        ]

    # ---- Project scopes (RBAC) ----------------------------------------------

    def _get_project_scopes_sync(self, user_id: str) -> dict[str, list[str]]:
        cursor = self._db.aql.execute(
            "FOR r IN @@col FILTER r.user_id == @uid RETURN r",
            bind_vars={"@col": COLL_ROLE_ASSIGNMENTS, "uid": user_id},
        )
        scopes: dict[str, list[str]] = {}
        for row in cursor:  # type: ignore[union-attr]
            scopes.setdefault(row["project_id"], []).append(row["role"])
        return scopes

    async def get_project_scopes(self, user_id: str) -> dict[str, list[str]]:
        return await asyncio.to_thread(self._get_project_scopes_sync, user_id)
