# =============================================================================
# File: repository.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c7_memory/kg/repository.py
# Description: ArangoDB persistence for the knowledge graph extracted by
#              `extractor.py` (Phase F.1 of v1 plan). Two collections:
#                - `memory_kg_entities` (vertex) — one row per
#                  (tenant_id, project_id, normalised entity name, type).
#                  Multiple sources mentioning the same entity converge.
#                - `memory_kg_relations` (edge) — directed `_from` →
#                  `_to`, attributed with the source(s) that mentioned
#                  the relation.
#
#              v2 (Phase F.2): adds `find_neighbor_source_ids` —
#              given a set of seed source_ids, find entities mentioning
#              them, traverse 1-hop on the edge collection, return the
#              source_ids of the neighbour entities. Used by
#              `MemoryService.retrieve` to expand the candidate pool
#              with graph-related sources beyond the vector scan window.
# =============================================================================

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase

from ay_platform_core.c7_memory.models import KGEntity, KGRelation

COLL_ENTITIES = "memory_kg_entities"
COLL_RELATIONS = "memory_kg_relations"


_ALLOWED_KEY_CHARS = re.compile(r"[^A-Za-z0-9_\-]")


def _sanitize_key_segment(value: str, *, max_len: int) -> str:
    """ArangoDB _key allows `[A-Za-z0-9_-:.@()+,=;$!*'%]`; lowest-common-
    denominator we keep alphanum + underscore + hyphen. Everything else
    becomes underscore. Trim to `max_len`."""
    cleaned = _ALLOWED_KEY_CHARS.sub("_", value.strip().lower())
    return cleaned[:max_len] or "_"


def _entity_key(tenant_id: str, project_id: str, entity: KGEntity) -> str:
    """Composite key. Lowercased + sanitised name + type so case- or
    whitespace-only variants converge. Tenant + project scope strict."""
    safe_tenant = _sanitize_key_segment(tenant_id, max_len=32)
    safe_project = _sanitize_key_segment(project_id, max_len=32)
    safe_type = _sanitize_key_segment(entity.type, max_len=32)
    safe_name = _sanitize_key_segment(entity.name, max_len=64)
    return f"{safe_tenant}-{safe_project}-{safe_type}-{safe_name}"


def _relation_key(
    tenant_id: str,
    project_id: str,
    subj_key: str,
    rel: str,
    obj_key: str,
) -> str:
    safe_tenant = _sanitize_key_segment(tenant_id, max_len=32)
    safe_project = _sanitize_key_segment(project_id, max_len=32)
    safe_rel = _sanitize_key_segment(rel, max_len=64)
    # Subject + object keys are already sanitised; we keep them as-is
    # (no second pass) and stitch with `__` separators.
    return f"{safe_tenant}-{safe_project}-{subj_key}__{safe_rel}__{obj_key}"


class KGRepository:
    """Async wrapper around python-arango (sync) for the KG collections."""

    def __init__(self, db: StandardDatabase) -> None:
        self._db = db

    def _ensure_collections_sync(self) -> None:
        if not self._db.has_collection(COLL_ENTITIES):
            self._db.create_collection(COLL_ENTITIES)
        if not self._db.has_collection(COLL_RELATIONS):
            self._db.create_collection(COLL_RELATIONS, edge=True)

    async def ensure_collections(self) -> None:
        await asyncio.to_thread(self._ensure_collections_sync)

    # ------------------------------------------------------------------
    # Persist a batch of entities + relations atomically per call.
    # ------------------------------------------------------------------

    def _persist_sync(
        self,
        *,
        tenant_id: str,
        project_id: str,
        source_id: str,
        entities: list[KGEntity],
        relations: list[KGRelation],
    ) -> tuple[int, int]:
        now = datetime.now(UTC).isoformat()
        ent_coll = self._db.collection(COLL_ENTITIES)
        rel_coll = self._db.collection(COLL_RELATIONS)

        # Build entity docs first so we can resolve relation `_from`/`_to`
        # by composite key (entities mentioned in relations may or may
        # not appear in the standalone `entities` list — be lenient).
        seen_keys: dict[tuple[str, str], str] = {}

        def _upsert_entity(entity: KGEntity) -> str:
            key = _entity_key(tenant_id, project_id, entity)
            if (entity.name, entity.type) in seen_keys:
                return seen_keys[(entity.name, entity.type)]
            doc = {
                "_key": key,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "name": entity.name,
                "type": entity.type,
                "source_ids": [source_id],
                "first_seen_at": now,
                "last_seen_at": now,
            }
            existing = cast("dict[str, Any] | None", ent_coll.get(key))
            if existing is None:
                ent_coll.insert(doc)
            else:
                # Merge source provenance + bump last_seen_at without
                # dropping older sources.
                src_ids = list(existing.get("source_ids", []))
                if source_id not in src_ids:
                    src_ids.append(source_id)
                ent_coll.update({
                    "_key": key,
                    "source_ids": src_ids,
                    "last_seen_at": now,
                })
            seen_keys[(entity.name, entity.type)] = key
            return key

        added_entities = 0
        for entity in entities:
            key = _upsert_entity(entity)
            after = cast("dict[str, Any]", ent_coll.get(key))
            if after.get("source_ids") == [source_id]:
                added_entities += 1

        added_relations = 0
        for rel in relations:
            subj_key = _upsert_entity(rel.subject)
            obj_key = _upsert_entity(rel.object)
            edge_key = _relation_key(
                tenant_id, project_id, subj_key, rel.relation, obj_key,
            )
            edge_doc = {
                "_key": edge_key,
                "_from": f"{COLL_ENTITIES}/{subj_key}",
                "_to": f"{COLL_ENTITIES}/{obj_key}",
                "tenant_id": tenant_id,
                "project_id": project_id,
                "relation": rel.relation,
                "source_id": source_id,
                "created_at": now,
            }
            if not rel_coll.has(edge_key):
                rel_coll.insert(edge_doc)
                added_relations += 1
        return added_entities, added_relations

    async def persist(
        self,
        *,
        tenant_id: str,
        project_id: str,
        source_id: str,
        entities: list[KGEntity],
        relations: list[KGRelation],
    ) -> tuple[int, int]:
        return await asyncio.to_thread(
            self._persist_sync,
            tenant_id=tenant_id,
            project_id=project_id,
            source_id=source_id,
            entities=entities,
            relations=relations,
        )

    # ------------------------------------------------------------------
    # Inspection (used by tests; useful for admin tooling later).
    # ------------------------------------------------------------------

    def _list_entities_for_source_sync(
        self, tenant_id: str, project_id: str, source_id: str
    ) -> list[dict[str, Any]]:
        cursor = cast("Cursor", self._db.aql.execute(
            "FOR e IN memory_kg_entities "
            "FILTER e.tenant_id == @tid AND e.project_id == @pid "
            "AND @sid IN e.source_ids "
            "RETURN e",
            bind_vars={"tid": tenant_id, "pid": project_id, "sid": source_id},
        ))
        return list(cursor)

    async def list_entities_for_source(
        self, tenant_id: str, project_id: str, source_id: str
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_entities_for_source_sync, tenant_id, project_id, source_id,
        )

    def _list_relations_for_source_sync(
        self, tenant_id: str, project_id: str, source_id: str
    ) -> list[dict[str, Any]]:
        cursor = cast("Cursor", self._db.aql.execute(
            "FOR r IN memory_kg_relations "
            "FILTER r.tenant_id == @tid AND r.project_id == @pid "
            "AND r.source_id == @sid "
            "RETURN r",
            bind_vars={"tid": tenant_id, "pid": project_id, "sid": source_id},
        ))
        return list(cursor)

    async def list_relations_for_source(
        self, tenant_id: str, project_id: str, source_id: str
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_relations_for_source_sync, tenant_id, project_id, source_id,
        )

    # ------------------------------------------------------------------
    # Phase F.2 — graph expansion at retrieve time.
    # ------------------------------------------------------------------

    def _find_neighbor_source_ids_sync(
        self,
        tenant_id: str,
        project_id: str,
        seed_source_ids: list[str],
        depth: int,
    ) -> list[str]:
        if not seed_source_ids or depth < 1:
            return []
        # Two-stage AQL:
        #   1. seed_entities = entities mentioning ANY seed source_id;
        #   2. ANY-direction 1..depth traversal returns neighbours
        #      (excluding the seed entities themselves via the path
        #      vertex predicate). The traversal is `ANY` because the
        #      semantic relevance of "graph proximity" is direction-
        #      agnostic — if A is "discovered_by" B, we want both
        #      directions of expansion.
        aql = """
        LET seeds = (
            FOR e IN memory_kg_entities
                FILTER e.tenant_id == @tid AND e.project_id == @pid
                FILTER LENGTH(INTERSECTION(e.source_ids, @sids)) > 0
                RETURN e
        )
        LET seed_keys = (FOR s IN seeds RETURN s._key)
        LET neighbour_source_ids = (
            FOR seed IN seeds
                FOR v IN 1..@depth ANY seed memory_kg_relations
                    FILTER v.tenant_id == @tid AND v.project_id == @pid
                    FILTER v._key NOT IN seed_keys
                    FOR sid IN v.source_ids
                        RETURN DISTINCT sid
        )
        RETURN neighbour_source_ids
        """
        bind_vars: dict[str, Any] = {
            "tid": tenant_id,
            "pid": project_id,
            "sids": seed_source_ids,
            "depth": depth,
        }
        cursor = cast(
            "Cursor", self._db.aql.execute(aql, bind_vars=bind_vars),
        )
        rows = list(cursor)
        if not rows:
            return []
        # The cursor yields a single row (the wrapping list comprehension).
        return [str(s) for s in rows[0]]

    async def find_neighbor_source_ids(
        self,
        tenant_id: str,
        project_id: str,
        seed_source_ids: list[str],
        depth: int = 1,
    ) -> list[str]:
        """Given a set of seed source_ids, return the source_ids of
        entities reachable within `depth` hops on the relation edge
        collection. Seed source_ids are excluded from the result —
        only NEW source provenance is returned. Result is unordered;
        callers SHALL apply their own cap if they want a bound."""
        return await asyncio.to_thread(
            self._find_neighbor_source_ids_sync,
            tenant_id,
            project_id,
            seed_source_ids,
            depth,
        )
