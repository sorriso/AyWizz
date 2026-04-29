# =============================================================================
# File: service.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c7_memory/service.py
# Description: Facade for the C7 Memory Service. Wires ingestion (parse +
#              chunk + embed + index), federated retrieval, entity-event
#              handlers, and the admin surface.
#
#              v2 (Phase F.2): hybrid retrieval. After the initial
#              vector scan + score, if a KG repo is wired and the graph
#              is non-empty for the project, expand the candidate pool
#              with chunks of source_ids reachable in 1 hop from the
#              top-K seeds (proposition A — pulls in chunks that
#              `scan_cap` may have cut off), then apply a multiplicative
#              boost to chunks whose source_id is graph-related to a
#              seed (proposition B — small ranking bump for
#              contextually-related-but-not-direct-vector matches).
#              Both knobs are configurable; default 1-hop, boost 1.3.
#
# @relation implements:R-400-020
# @relation implements:R-400-030
# @relation implements:R-400-031
# @relation implements:R-400-040
# @relation implements:R-400-042
# @relation implements:R-400-070
# @relation implements:R-400-071
# =============================================================================

from __future__ import annotations

import contextlib
import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status

from ay_platform_core.c7_memory.config import MemoryConfig
from ay_platform_core.c7_memory.db.repository import MemoryRepository
from ay_platform_core.c7_memory.embedding.base import EmbeddingProvider
from ay_platform_core.c7_memory.ingestion.chunker import chunk_text
from ay_platform_core.c7_memory.ingestion.parser import (
    ParseFailureError,
    UnsupportedMimeError,
    parse,
)
from ay_platform_core.c7_memory.kg.extractor import (
    KGExtractionError,
    extract_entities_and_relations,
)
from ay_platform_core.c7_memory.kg.repository import KGRepository
from ay_platform_core.c7_memory.models import (
    ChunkPublic,
    ChunkStatus,
    EntityEmbedRequest,
    IndexKind,
    KGExtractionResult,
    ParseStatus,
    QuotaStatus,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResponse,
    SourceIngestRequest,
    SourceListResponse,
    SourcePublic,
)
from ay_platform_core.c7_memory.retrieval.similarity import cosine, snippet
from ay_platform_core.c7_memory.storage.minio_storage import MemorySourceStorage
from ay_platform_core.c8_llm.client import LLMGatewayClient


class MemoryService:
    """Public API of the Memory Service."""

    def __init__(
        self,
        config: MemoryConfig,
        repo: MemoryRepository,
        embedder: EmbeddingProvider,
        storage: MemorySourceStorage | None = None,
        kg_repo: KGRepository | None = None,
        llm_client: LLMGatewayClient | None = None,
    ) -> None:
        self._config = config
        self._repo = repo
        self._embedder = embedder
        # `storage` is optional: tests that don't exercise the upload
        # endpoint can pass None. The /sources/upload route requires
        # storage to be present and 503's otherwise.
        self._storage = storage
        # Phase F.1 — KG extraction. Both `kg_repo` and `llm_client`
        # are required for the extract endpoint; absent → 503.
        self._kg_repo = kg_repo
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Ingestion (admin/test direct path — C12 upload still goes via NATS
    # in production; this lets operators and integration tests ingest
    # pre-parsed content without spinning up the full pipeline)
    # ------------------------------------------------------------------

    async def ingest_source(
        self, payload: SourceIngestRequest, *, tenant_id: str
    ) -> SourcePublic:
        """Ingest a source whose CONTENT is already a UTF-8 string.

        Used by C12 webhooks and tests. The string is round-tripped
        through the parser registry to apply MIME-specific text shaping
        (e.g. markdown frontmatter strip). For binary uploads (PDF /
        DOCX) use `ingest_uploaded_source` instead.
        """
        await self._enforce_quota(tenant_id, payload.project_id, payload.size_bytes)

        try:
            text = parse(payload.mime_type, payload.content.encode("utf-8"))
        except UnsupportedMimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
            ) from exc
        except ParseFailureError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

        return await self._index_parsed_source(
            tenant_id=tenant_id,
            project_id=payload.project_id,
            source_id=payload.source_id,
            mime_type=payload.mime_type,
            uploaded_by=payload.uploaded_by,
            size_bytes=payload.size_bytes,
            parsed_text=text,
        )

    async def ingest_uploaded_source(
        self,
        *,
        tenant_id: str,
        project_id: str,
        source_id: str,
        mime_type: str,
        uploaded_by: str,
        content_bytes: bytes,
    ) -> SourcePublic:
        """Phase B of v1 plan — multipart-uploaded source.

        Persists the raw bytes in MinIO (audit + re-parse), then runs
        the same parse → chunk → embed → index pipeline as
        `ingest_source`. Requires `storage` to be wired (otherwise
        503).
        """
        if self._storage is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "blob storage not configured — POST /sources/upload "
                    "requires MinIO to be available"
                ),
            )
        size_bytes = len(content_bytes)
        if size_bytes > self._config.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"upload exceeds max_upload_bytes "
                    f"({self._config.max_upload_bytes} bytes)"
                ),
            )
        await self._enforce_quota(tenant_id, project_id, size_bytes)

        try:
            text = parse(mime_type, content_bytes)
        except UnsupportedMimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
            ) from exc
        except ParseFailureError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

        # Persist the raw blob BEFORE indexing so a downstream failure
        # leaves the operator with the original file to retry from.
        await self._storage.put_source_blob(
            tenant_id=tenant_id,
            project_id=project_id,
            source_id=source_id,
            data=content_bytes,
            mime_type=mime_type,
        )

        public = await self._index_parsed_source(
            tenant_id=tenant_id,
            project_id=project_id,
            source_id=source_id,
            mime_type=mime_type,
            uploaded_by=uploaded_by,
            size_bytes=size_bytes,
            parsed_text=text,
        )

        # Auto KG extraction (gap UX #3) — when C7 is wired with both
        # a KG repo and an LLM client AND the config opts in
        # (`C7_AUTO_EXTRACT_KG_ON_UPLOAD=True`, default), trigger KG
        # extraction on the freshly indexed source. Best-effort: a
        # failure here SHALL NOT cause the upload to fail (the source
        # row + chunks are already persisted; KG can be re-extracted
        # later via the explicit endpoint).
        if (
            self._config.auto_extract_kg_on_upload
            and self._kg_repo is not None
            and self._llm is not None
        ):
            with contextlib.suppress(Exception):
                await self.extract_kg(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source_id=source_id,
                )
        return public

    async def ingest_conversation_turn(
        self,
        *,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        turn_id: str,
        user_message: str,
        assistant_reply: str,
        actor_id: str,
        **_forward_auth_kwargs: Any,
    ) -> SourcePublic:
        # `**_forward_auth_kwargs` mirrors `retrieve()` — keeps the call
        # signature compatible with `RemoteMemoryService` so callers
        # (C3 _rag_stream) don't need to branch on which variant is
        # wired.
        """Phase E of v1 plan — index a conversation turn into the
        CONVERSATIONS index so follow-up questions can retrieve prior
        exchanges as context.

        The user/assistant pair is concatenated into a single text body
        (one chunk per ~chunk_token_size words) so retrieve sees the
        full exchange as a single semantic unit. Source row is tagged
        `mime_type=text/plain`, `uploaded_by=conv:{actor_id}` for
        operator audit; quota is enforced same as upload.
        """
        body = (
            f"User: {user_message.strip()}\n\n"
            f"Assistant: {assistant_reply.strip()}"
        )
        size_bytes = len(body.encode("utf-8"))
        await self._enforce_quota(tenant_id, project_id, size_bytes)
        return await self._index_parsed_source(
            tenant_id=tenant_id,
            project_id=project_id,
            source_id=f"conv:{conversation_id}:{turn_id}",
            mime_type="text/plain",
            uploaded_by=f"conv:{actor_id}",
            size_bytes=size_bytes,
            parsed_text=body,
            index_kind=IndexKind.CONVERSATIONS,
        )

    async def _index_parsed_source(
        self,
        *,
        tenant_id: str,
        project_id: str,
        source_id: str,
        mime_type: str,
        uploaded_by: str,
        size_bytes: int,
        parsed_text: str,
        index_kind: IndexKind = IndexKind.EXTERNAL_SOURCES,
    ) -> SourcePublic:
        """Shared post-parse pipeline used by `ingest_source`,
        `ingest_uploaded_source`, and `ingest_conversation_turn`.
        Chunks the text, embeds the chunks, and persists rows under
        `index_kind` (default `EXTERNAL_SOURCES`; `CONVERSATIONS` for
        Phase E conversation memory)."""
        # Synthesise a SourceIngestRequest-like payload for the helper
        # builders below. We use the typed model where it'd compose
        # cleanly; otherwise inline.
        synth_payload = SourceIngestRequest(
            source_id=source_id,
            project_id=project_id,
            mime_type=mime_type,  # type: ignore[arg-type]
            content="placeholder-not-stored",
            size_bytes=size_bytes,
            uploaded_by=uploaded_by,
        )

        chunks = chunk_text(
            parsed_text,
            token_size=self._config.chunk_token_size,
            overlap=self._config.chunk_overlap,
        )
        if not chunks:
            source_row = _source_row(
                payload=synth_payload,
                tenant_id=tenant_id,
                model_id=self._embedder.model_id,
                chunk_count=0,
                parse_status=ParseStatus.PARSED,
            )
            await self._repo.upsert_source(source_row)
            return _source_public(source_row)

        vectors = await self._embedder.embed_batch([c.text for c in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError(
                "embedder returned a different number of vectors than "
                "input chunks — adapter contract violation"
            )
        if any(len(v) != self._embedder.dimension for v in vectors):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "embedder produced a vector of unexpected dimension; "
                    "declared dim does not match actual output"
                ),
            )

        now = datetime.now(UTC).isoformat()
        chunk_rows: list[dict[str, Any]] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            content_hash = (
                "sha256:" + hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            )
            chunk_id = f"{source_id}:{chunk.index}"
            chunk_rows.append({
                "_key": f"{tenant_id}:{project_id}:{chunk_id}",
                "chunk_id": chunk_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "index": index_kind.value,
                "source_id": source_id,
                "entity_id": None,
                "entity_version": None,
                "chunk_index": chunk.index,
                "content": chunk.text,
                "content_hash": content_hash,
                "vector": vector,
                "model_id": self._embedder.model_id,
                "model_dim": self._embedder.dimension,
                "created_at": now,
                "status": ChunkStatus.ACTIVE.value,
                "metadata": {"mime_type": mime_type},
            })
        await self._repo.upsert_chunks(chunk_rows)
        source_row = _source_row(
            payload=synth_payload,
            tenant_id=tenant_id,
            model_id=self._embedder.model_id,
            chunk_count=len(chunks),
            parse_status=ParseStatus.INDEXED,
        )
        await self._repo.upsert_source(source_row)
        return _source_public(source_row)

    async def extract_kg(
        self,
        *,
        tenant_id: str,
        project_id: str,
        source_id: str,
    ) -> KGExtractionResult:
        """Phase F.1 — extract entities + relations from a previously
        ingested source via the C8 LLM gateway, then persist to the
        knowledge graph collections.

        Requires both `llm_client` and `kg_repo` to have been wired at
        construction time; absent → 503. The source must already be in
        Arango (POST /sources or POST /sources/upload before this).
        """
        if self._llm is None or self._kg_repo is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "KG extraction not configured — wire C8 LLMGatewayClient "
                    "and KGRepository to enable POST /sources/{sid}/extract-kg"
                ),
            )

        existing = await self._repo.get_source(tenant_id, project_id, source_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="source not found",
            )

        # Reconstruct the source's text from its persisted chunks. Cheap
        # for v1 sources (≤ a few MB); avoids re-parsing the raw blob.
        chunk_rows = await self._repo.scan_chunks(
            tenant_id=tenant_id,
            project_id=project_id,
            indexes=[IndexKind.EXTERNAL_SOURCES.value],
            model_id=self._embedder.model_id,
            include_deprecated=False,
            include_history=False,
            scan_cap=self._config.retrieval_scan_cap,
        )
        source_chunks = sorted(
            (c for c in chunk_rows if c.get("source_id") == source_id),
            key=lambda c: c.get("chunk_index", 0),
        )
        source_text = "\n\n".join(c["content"] for c in source_chunks).strip()

        try:
            entities, relations = await extract_entities_and_relations(
                llm_client=self._llm,
                source_text=source_text,
                tenant_id=tenant_id,
                project_id=project_id,
                source_id=source_id,
            )
        except KGExtractionError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM-based KG extraction failed: {exc}",
            ) from exc

        added_entities, added_relations = await self._kg_repo.persist(
            tenant_id=tenant_id,
            project_id=project_id,
            source_id=source_id,
            entities=entities,
            relations=relations,
        )
        return KGExtractionResult(
            source_id=source_id,
            entities_added=added_entities,
            relations_added=added_relations,
            entities=entities,
            relations=relations,
        )

    async def download_source(
        self, tenant_id: str, project_id: str, source_id: str,
    ) -> tuple[bytes, str, str]:
        """Fetch the raw bytes of a previously-uploaded source from
        MinIO. Returns `(bytes, mime_type, filename)` so the router
        can set Content-Type + Content-Disposition correctly.

        Errors:
          - 503 if MinIO storage isn't wired (e.g. test stack without
            blob storage).
          - 404 if the source row doesn't exist (wrong tenant/project,
            or source deleted).
          - 404 if the row exists but the MinIO object is missing
            (sources ingested via the JSON-only `POST /sources` path
            never wrote a blob; download is meaningless for those).
        """
        if self._storage is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "blob storage not configured — download requires "
                    "MinIO storage to be wired"
                ),
            )
        existing = await self._repo.get_source(tenant_id, project_id, source_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="source not found",
            )
        mime_type = str(existing["mime_type"])
        try:
            blob = await self._storage.get_source_blob(
                tenant_id=tenant_id,
                project_id=project_id,
                source_id=source_id,
                mime_type=mime_type,
            )
        except FileNotFoundError as exc:
            # Row present, blob absent — the source was ingested via
            # the JSON `POST /sources` endpoint which doesn't persist
            # to MinIO. Surface 404 rather than 500.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="source has no downloadable blob "
                "(ingested without upload)",
            ) from exc
        import mimetypes as _mt  # noqa: PLC0415 — keep module hot path lean
        ext = _mt.guess_extension(mime_type) or ""
        filename = f"{source_id}{ext}"
        return blob, mime_type, filename

    async def delete_source(
        self, tenant_id: str, project_id: str, source_id: str
    ) -> None:
        existing = await self._repo.get_source(tenant_id, project_id, source_id)
        if existing is None:
            # R-400-071: 404, not 403 — do not leak tenant boundaries.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="source not found"
            )
        await self._repo.delete_chunks_for_source(tenant_id, project_id, source_id)
        await self._repo.delete_source(tenant_id, project_id, source_id)

    async def list_sources(
        self, tenant_id: str, project_id: str
    ) -> SourceListResponse:
        rows = await self._repo.list_sources(tenant_id, project_id)
        return SourceListResponse(sources=[_source_public(r) for r in rows])

    async def get_source(
        self, tenant_id: str, project_id: str, source_id: str
    ) -> SourcePublic:
        row = await self._repo.get_source(tenant_id, project_id, source_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="source not found"
            )
        return _source_public(row)

    # ------------------------------------------------------------------
    # Entity embedding (R-400-030) — triggered by requirements events.
    # Exposed as a method so C5 event consumers (or tests) can call it
    # directly; in production an async worker would dequeue from NATS
    # and invoke this path.
    # ------------------------------------------------------------------

    async def embed_entity(
        self, payload: EntityEmbedRequest, *, tenant_id: str
    ) -> ChunkPublic:
        vector = await self._embedder.embed_one(payload.content)
        if len(vector) != self._embedder.dimension:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="embedder produced vector of unexpected dimension",
            )

        if payload.preserve_history:
            await self._repo.mark_entity_superseded(
                tenant_id, payload.project_id, payload.entity_id, payload.entity_version
            )

        now = datetime.now(UTC).isoformat()
        content_hash = "sha256:" + hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
        chunk_id = f"{payload.entity_id}@v{payload.entity_version}"
        row: dict[str, Any] = {
            "_key": f"{tenant_id}:{payload.project_id}:{chunk_id}",
            "chunk_id": chunk_id,
            "tenant_id": tenant_id,
            "project_id": payload.project_id,
            "index": IndexKind.REQUIREMENTS.value,
            "source_id": None,
            "entity_id": payload.entity_id,
            "entity_version": payload.entity_version,
            "chunk_index": 0,
            "content": payload.content,
            "content_hash": content_hash,
            "vector": vector,
            "model_id": self._embedder.model_id,
            "model_dim": self._embedder.dimension,
            "created_at": now,
            "status": ChunkStatus.ACTIVE.value,
            "metadata": dict(payload.metadata),
        }
        await self._repo.upsert_chunk(row)
        return _chunk_public(row)

    # ------------------------------------------------------------------
    # Retrieval (R-400-040)
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        payload: RetrievalRequest,
        *,
        tenant_id: str,
        **_forward_auth_kwargs: Any,
    ) -> RetrievalResponse:
        # `**_forward_auth_kwargs` swallows `user_id` / `user_roles`
        # passed by callers that share their signature with
        # `RemoteMemoryService.retrieve` — the in-process variant
        # already trusts its `tenant_id` arg, so the headers are
        # informational here. Keeping the kwargs ensures the two
        # implementations are call-compatible.
        started = time.monotonic()
        # R-400-042: the query is embedded with the ACTIVE embedder; we
        # only compare against stored chunks that used the same model.
        query_vector = await self._embedder.embed_one(payload.query)

        rows = await self._repo.scan_chunks(
            tenant_id=tenant_id,
            project_id=payload.project_id,
            indexes=[ix.value for ix in payload.indexes],
            model_id=self._embedder.model_id,
            include_deprecated=payload.include_deprecated,
            include_history=payload.include_history,
            scan_cap=self._config.retrieval_scan_cap,
        )
        # Apply post-scan filters (metadata + history) — kept Python-side
        # so the AQL scan stays simple and the repository remains reusable.
        filtered = [
            r for r in rows if _row_matches_filters(r, payload)
        ]

        weights = payload.weights or {}

        def _cosine_weighted(row: dict[str, Any]) -> float:
            raw = cosine(query_vector, list(row["vector"]))
            multiplier = weights.get(IndexKind(row["index"]), 1.0)
            return raw * multiplier

        scored: list[tuple[dict[str, Any], float]] = [
            (row, _cosine_weighted(row)) for row in filtered
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)

        # ----------------------------------------------------------------
        # Phase F.2 — KG expansion (hybrid retrieval).
        # Active iff a KG repo is wired AND the initial top-K seeds have
        # source_ids that the graph knows about. Two effects combined:
        #   (A) pool widening — chunks of graph-neighbour source_ids that
        #       the `scan_cap` cut off are fetched directly and added to
        #       the candidate pool.
        #   (B) ranking boost — chunks whose source_id is reachable in
        #       the graph from a seed source_id get their score
        #       multiplied by `kg_expansion_boost` (default 1.3). Pure-
        #       vector ranking still wins for clearly more relevant
        #       direct matches; graph signal only nudges borderline.
        # ----------------------------------------------------------------
        if self._kg_repo is not None and scored:
            scored = await self._apply_kg_expansion(
                scored=scored,
                payload=payload,
                tenant_id=tenant_id,
                cosine_fn=_cosine_weighted,
            )

        top = scored[: payload.top_k]

        hits = [
            RetrievalHit(
                chunk_id=row["chunk_id"],
                index=IndexKind(row["index"]),
                score=score,
                content=row["content"],
                snippet=snippet(row["content"]),
                source_id=row.get("source_id"),
                entity_id=row.get("entity_id"),
                entity_version=row.get("entity_version"),
                metadata=dict(row.get("metadata", {})),
            )
            for row, score in top
        ]
        return RetrievalResponse(
            retrieval_id=str(uuid.uuid4()),
            request=payload,
            hits=hits,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def _apply_kg_expansion(
        self,
        *,
        scored: list[tuple[dict[str, Any], float]],
        payload: RetrievalRequest,
        tenant_id: str,
        cosine_fn: Any,
    ) -> list[tuple[dict[str, Any], float]]:
        """Phase F.2 hybrid expansion. Returns a re-sorted scored list
        with (A) extra chunks pulled from graph-neighbour source_ids
        and (B) boosted scores for chunks whose source_id is graph-
        related to a top-K seed."""
        assert self._kg_repo is not None  # invariant — caller checked
        top_seeds = scored[: payload.top_k]
        seed_source_ids = sorted({
            sid for row, _ in top_seeds
            if (sid := row.get("source_id")) is not None
        })
        if not seed_source_ids:
            return scored

        neighbour_source_ids = await self._kg_repo.find_neighbor_source_ids(
            tenant_id=tenant_id,
            project_id=payload.project_id,
            seed_source_ids=seed_source_ids,
            depth=self._config.kg_expansion_depth,
        )
        if not neighbour_source_ids:
            return scored

        # Cap the new source_ids we'll bring in (proposition A) — bound
        # the cost of the extra fetch + scoring round.
        capped_neighbours = sorted(set(neighbour_source_ids))[
            : self._config.kg_expansion_neighbour_cap
        ]
        already_seen = {
            sid for row, _ in scored
            if (sid := row.get("source_id")) is not None
        }
        extra_source_ids = [s for s in capped_neighbours if s not in already_seen]
        if extra_source_ids:
            extra_rows = await self._repo.fetch_chunks_for_source_ids(
                tenant_id=tenant_id,
                project_id=payload.project_id,
                source_ids=extra_source_ids,
                indexes=[ix.value for ix in payload.indexes],
                model_id=self._embedder.model_id,
                include_deprecated=payload.include_deprecated,
                include_history=payload.include_history,
            )
            extra_filtered = [r for r in extra_rows if _row_matches_filters(r, payload)]
            scored = scored + [(row, cosine_fn(row)) for row in extra_filtered]

        # Proposition B: boost any chunk whose source_id is in the graph-
        # neighbour set (including the just-added extras). Seeds
        # themselves are NOT boosted (they're already at the top by
        # vector similarity; double-counting would hide cosine signal).
        neighbour_set = set(capped_neighbours)
        boost = self._config.kg_expansion_boost
        if boost != 1.0:
            scored = [
                (row, score * boost
                 if row.get("source_id") in neighbour_set else score)
                for row, score in scored
            ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Quota (R-400-024)
    # ------------------------------------------------------------------

    async def quota(self, tenant_id: str, project_id: str) -> QuotaStatus:
        totals = await self._repo.quota_totals(tenant_id, project_id)
        return QuotaStatus(
            project_id=project_id,
            bytes_used=totals["bytes_used"],
            bytes_limit=self._config.default_quota_bytes,
            chunk_count=totals["chunk_count"],
            source_count=totals["source_count"],
        )

    async def _enforce_quota(
        self, tenant_id: str, project_id: str, incoming_bytes: int
    ) -> None:
        totals = await self._repo.quota_totals(tenant_id, project_id)
        if totals["bytes_used"] + incoming_bytes > self._config.default_quota_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"project quota exceeded: {totals['bytes_used']} + "
                    f"{incoming_bytes} > {self._config.default_quota_bytes}"
                ),
            )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _source_row(
    *,
    payload: SourceIngestRequest,
    tenant_id: str,
    model_id: str,
    chunk_count: int,
    parse_status: ParseStatus,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "_key": f"{tenant_id}:{payload.project_id}:{payload.source_id}",
        "tenant_id": tenant_id,
        "project_id": payload.project_id,
        "source_id": payload.source_id,
        "minio_raw_path": None,
        "minio_parsed_path": None,
        "minio_chunks_path": None,
        "mime_type": payload.mime_type,
        "size_bytes": payload.size_bytes,
        "uploaded_by": payload.uploaded_by,
        "uploaded_at": now,
        "parse_status": parse_status.value,
        "parse_error": None,
        "chunk_count": chunk_count,
        "model_id": model_id,
    }


def _source_public(row: dict[str, Any]) -> SourcePublic:
    return SourcePublic(
        source_id=row["source_id"],
        project_id=row["project_id"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        uploaded_by=row["uploaded_by"],
        uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
        parse_status=ParseStatus(row["parse_status"]),
        parse_error=row.get("parse_error"),
        chunk_count=row.get("chunk_count", 0),
        model_id=row.get("model_id"),
    )


def _chunk_public(row: dict[str, Any]) -> ChunkPublic:
    return ChunkPublic(
        chunk_id=row["chunk_id"],
        project_id=row["project_id"],
        index=IndexKind(row["index"]),
        source_id=row.get("source_id"),
        entity_id=row.get("entity_id"),
        entity_version=row.get("entity_version"),
        chunk_index=row["chunk_index"],
        content=row["content"],
        content_hash=row["content_hash"],
        model_id=row["model_id"],
        model_dim=row["model_dim"],
        created_at=datetime.fromisoformat(row["created_at"]),
        status=ChunkStatus(row["status"]),
        metadata=dict(row.get("metadata", {})),
    )


def _row_matches_filters(row: dict[str, Any], payload: RetrievalRequest) -> bool:
    """Post-scan filtering: metadata + history gating.

    - `include_history=False` (default): for each entity_id, only the
      latest active version. Deprecated chunks are governed by
      `include_deprecated`.
    - `filters`: simple key/value match against row['metadata'] and
      top-level fields.
    """
    # History: when False, drop superseded requirement-entity chunks.
    if (
        not payload.include_history
        and row.get("entity_id") is not None
        and row.get("status") == ChunkStatus.SUPERSEDED.value
    ):
        return False
    # Metadata filter: every declared key SHALL match.
    for key, expected in payload.filters.items():
        actual = row.get(key)
        if actual is None:
            actual = row.get("metadata", {}).get(key)
        if actual != expected:
            return False
    return True


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_service(request: Request) -> MemoryService:
    svc = getattr(request.app.state, "memory_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="memory service not initialised",
        )
    return svc  # type: ignore[no-any-return]
