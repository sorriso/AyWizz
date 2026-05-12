# =============================================================================
# File: service.py
# Version: 5
# Path: ay_platform_core/src/ay_platform_core/c3_conversation/service.py
# Description: C3 Conversation Service facade.
#              Orchestrates CRUD and the SSE message-send flow.
#
#              v5: when retrieval surfaces no chunk above the
#              relevance threshold, the system prompt switches to the
#              `_GENERAL_SYSTEM_PROMPT` variant (no "Retrieved context"
#              block). Small models otherwise tried to reconcile their
#              answer with an empty/irrelevant context and hallucinated
#              bridges (e.g. "Paris as capital of the Hispanic kingdom"
#              for "capitale de l'Espagne").
#
#              v4: the pipeline timeline emitted as SSE `event: stage`
#              payloads is now also collected in-process and persisted
#              alongside the assistant message (`stages` field).
#              `_msg_doc_to_public` reads it back so a navigation /
#              refresh re-renders the same chip + collapsible panel
#              the operator saw live. Only `done` events are stored
#              (the `running` intermediate signals exist only for the
#              live UX).
#
#              v3: `send_message_stream` accepts optional `user_prompt`
#              and `project_prompt` (resolved by C2 and forwarded by the
#              UX). When present, they are prepended in order ahead of
#              the RAG retrieval section in the assembled system
#              message, so they outrank any RAG/context instructions.
#
#              v2 (Phase D of v1 plan): the message-send flow now does
#              RAG when the conversation has a project_id AND the
#              service was wired with a MemoryService + LLMGatewayClient.
#              Pipeline: persist user message → C7 retrieve top-K
#              chunks → build (system + context + history + user)
#              prompt → C8 streaming chat completion → SSE → persist
#              assistant reply. Wiring is opt-in: tests/components
#              that don't need RAG can pass `memory_service=None` and
#              `llm_client=None` and the original stub fallback runs.
# @relation R-100-003 R-100-074 D-008
# =============================================================================

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from ay_platform_core.c3_conversation.db.repository import ConversationRepository
from ay_platform_core.c3_conversation.models import (
    ConversationCreate,
    ConversationInternal,
    ConversationPublic,
    ConversationUpdate,
    MessagePublic,
    MessageRole,
)
from ay_platform_core.c7_memory.models import IndexKind, RetrievalRequest
from ay_platform_core.c7_memory.remote import RemoteMemoryService
from ay_platform_core.c7_memory.service import MemoryService
from ay_platform_core.c8_llm.client import LLMGatewayClient
from ay_platform_core.c8_llm.models import ChatCompletionRequest, ChatMessage, ChatRole


def _doc_to_public(doc: dict[str, Any]) -> ConversationPublic:
    return ConversationPublic(
        id=UUID(doc["id"]),
        owner_id=doc["owner_id"],
        project_id=doc.get("project_id"),
        title=doc["title"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        message_count=doc.get("message_count", 0),
    )


def _doc_to_internal(doc: dict[str, Any]) -> ConversationInternal:
    return ConversationInternal(
        id=UUID(doc["id"]),
        owner_id=doc["owner_id"],
        project_id=doc.get("project_id"),
        title=doc["title"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        message_count=doc.get("message_count", 0),
        deleted=doc.get("deleted", False),
    )


def _msg_doc_to_public(doc: dict[str, Any]) -> MessagePublic:
    # `stages` is optional — absent on user messages and on legacy
    # assistant messages persisted before the field existed. Pydantic
    # validates per-item when present, so a corrupt stage entry would
    # raise here ; we let it propagate (caller surfaces a 500 ; better
    # than silently dropping malformed timeline data).
    raw_stages = doc.get("stages")
    return MessagePublic(
        id=UUID(doc["id"]),
        conversation_id=UUID(doc["conversation_id"]),
        role=MessageRole(doc["role"]),
        content=doc["content"],
        timestamp=doc["timestamp"],
        stages=raw_stages if raw_stages else None,
    )


class ConversationService:
    def __init__(
        self,
        repo: ConversationRepository,
        *,
        memory_service: MemoryService | RemoteMemoryService | None = None,
        llm_client: LLMGatewayClient | None = None,
        rag_top_k: int = 5,
        rag_history_turns: int = 6,
    ) -> None:
        self._repo = repo
        # Phase D wiring — optional. When BOTH are provided AND the
        # conversation has a project_id, `send_message_stream` runs the
        # RAG pipeline; otherwise it falls back to the static stub.
        # `MemoryService` is the in-process variant (test stack);
        # `RemoteMemoryService` is the HTTP variant (K8s production).
        # Both expose the same retrieve()/ingest_conversation_turn()
        # surface — ConversationService is agnostic to the choice.
        self._memory = memory_service
        self._llm = llm_client
        self._rag_top_k = rag_top_k
        self._rag_history_turns = rag_history_turns

    # ------------------------------------------------------------------
    # Access guard
    # ------------------------------------------------------------------

    async def _require_access(
        self, conversation_id: UUID, user_id: str
    ) -> dict[str, Any]:
        doc = await self._repo.get_conversation(conversation_id)
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
        if doc["owner_id"] != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        return doc

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_conversations(self, user_id: str) -> list[ConversationPublic]:
        docs = await self._repo.list_conversations(user_id)
        return [_doc_to_public(d) for d in docs]

    async def create_conversation(
        self, user_id: str, payload: ConversationCreate
    ) -> ConversationPublic:
        doc = await self._repo.create_conversation(
            owner_id=user_id,
            title=payload.title,
            project_id=payload.project_id,
        )
        return _doc_to_public(doc)

    async def get_conversation(
        self, conversation_id: UUID, user_id: str
    ) -> ConversationPublic:
        doc = await self._require_access(conversation_id, user_id)
        return _doc_to_public(doc)

    async def update_conversation(
        self, conversation_id: UUID, user_id: str, payload: ConversationUpdate
    ) -> ConversationPublic:
        await self._require_access(conversation_id, user_id)
        updates: dict[str, Any] = {}
        if payload.title is not None:
            updates["title"] = payload.title
        if payload.project_id is not None:
            updates["project_id"] = payload.project_id
        doc = await self._repo.update_conversation(conversation_id, updates)
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
        return _doc_to_public(doc)

    async def delete_conversation(
        self, conversation_id: UUID, user_id: str
    ) -> None:
        await self._require_access(conversation_id, user_id)
        await self._repo.soft_delete_conversation(conversation_id)

    async def list_messages(
        self, conversation_id: UUID, user_id: str
    ) -> list[MessagePublic]:
        await self._require_access(conversation_id, user_id)
        docs = await self._repo.list_messages(conversation_id)
        return [_msg_doc_to_public(d) for d in docs]

    # ------------------------------------------------------------------
    # Message send → SSE stream (C4 stub)
    # ------------------------------------------------------------------

    async def send_message_stream(
        self,
        conversation_id: UUID,
        user_id: str,
        content: str,
        *,
        tenant_id: str | None = None,
        user_roles: str = "project_editor",
        user_prompt: str | None = None,
        project_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Persist the user message and yield SSE chunks for the
        assistant reply.

        Two paths:

        - **RAG path** (Phase D): when this service has been wired with
          BOTH a `MemoryService` and an `LLMGatewayClient`, AND the
          conversation has a `project_id`, AND a `tenant_id` was
          propagated from the request, retrieve the top-K relevant
          chunks from C7, build a (system + context + history + user)
          prompt, and stream the LLM response from C8.
        - **Stub path** (legacy): if any wire is missing, fall back to
          the deterministic placeholder reply that earlier versions
          shipped — preserves backward compat with tests that don't
          care about the LLM.
        """
        conv = await self._require_access(conversation_id, user_id)

        # Persist user message FIRST so a downstream LLM failure still
        # leaves the user's input in the history.
        await self._repo.append_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
        )

        project_id = conv.get("project_id")
        if (
            self._memory is not None
            and self._llm is not None
            and project_id
            and tenant_id
        ):
            return self._rag_stream(
                conversation_id=conversation_id,
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
                user_roles=user_roles,
                user_message=content,
                user_prompt=user_prompt,
                project_prompt=project_prompt,
            )
        return self._stub_stream(conversation_id)

    def _stub_stream(self, conversation_id: UUID) -> AsyncIterator[str]:
        stub_reply = (
            "RAG / LLM not wired in this deployment. "
            "Your message has been saved; configure C7 + C8 to enable "
            "automatic responses."
        )

        async def _generate() -> AsyncIterator[str]:
            for word in stub_reply.split():
                yield f"data: {word} \n\n"
                await asyncio.sleep(0)
            yield "data: [DONE]\n\n"
            await self._repo.append_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=stub_reply,
            )

        return _generate()

    def _rag_stream(
        self,
        *,
        conversation_id: UUID,
        project_id: str,
        tenant_id: str,
        user_id: str,
        user_roles: str,
        user_message: str,
        user_prompt: str | None,
        project_prompt: str | None,
    ) -> AsyncIterator[str]:
        async def _generate() -> AsyncIterator[str]:
            # The SSE protocol mixes two event kinds :
            #   - default `message` events (no `event:` line) carry the
            #     streamed LLM tokens — legacy clients keep working
            #     unchanged because that's exactly the v1 contract.
            #   - named `event: stage` events carry JSON describing
            #     macro-level pipeline progress (retrieval, generation,
            #     persistence). New clients render a live timeline next
            #     to the assistant avatar ; old clients ignore them
            #     (per SSE spec: unknown event types fall through to
            #     the default `message` listener which our token parser
            #     ignores because the data is JSON, not plain text).
            t_start = time.perf_counter()

            # Collect `done` stage payloads as we emit them so they can
            # be persisted alongside the assistant message — the UX
            # uses these to re-render the chip + timeline on navigation
            # / refresh (where the live SSE stream is gone). `running`
            # events are intermediate signals for the live UI only,
            # never stored.
            collected_stages: list[dict[str, Any]] = []

            def _emit(
                *,
                name: str,
                status: str,
                label: str,
                duration_ms: int | None = None,
                stats: dict[str, Any] | None = None,
            ) -> str:
                payload: dict[str, Any] = {
                    "name": name,
                    "status": status,
                    "label": label,
                }
                if duration_ms is not None:
                    payload["duration_ms"] = duration_ms
                if stats is not None:
                    payload["stats"] = stats
                if status == "done":
                    collected_stages.append(payload)
                return (
                    "event: stage\n"
                    f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
                )

            # 1. Retrieval phase.
            assert self._memory is not None  # narrowed in caller
            assert self._llm is not None
            t_retrieve = time.perf_counter()
            yield _emit(
                name="retrieve",
                status="running",
                label="Searching project sources",
            )
            retrieval = await self._memory.retrieve(
                RetrievalRequest(
                    project_id=project_id,
                    query=user_message,
                    indexes=[
                        IndexKind.EXTERNAL_SOURCES,
                        IndexKind.CONVERSATIONS,
                    ],
                    top_k=self._rag_top_k,
                ),
                tenant_id=tenant_id,
                user_id=user_id,
                user_roles=user_roles,
            )
            retrieve_ms = int((time.perf_counter() - t_retrieve) * 1000)
            hits_total, hits_relevant, top_score = _hit_stats(retrieval.hits)
            context_block = _format_retrieved_chunks(retrieval.hits)
            yield _emit(
                name="retrieve",
                status="done",
                label=(
                    f"{hits_relevant}/{hits_total} relevant chunk"
                    f"{'s' if hits_relevant != 1 else ''}"
                ),
                duration_ms=retrieve_ms,
                stats={
                    "hits_total": hits_total,
                    "hits_relevant": hits_relevant,
                    "top_score": top_score,
                },
            )

            # 2. Build prompt: (optional user_prompt + project_prompt
            #    preamble) + RAG system instructions + recent history
            #    + user.
            history_msgs = await self._recent_history_messages(
                conversation_id, exclude_id=None,
            )
            system_content = _assemble_system_prompt(
                project_id=project_id,
                context=context_block,
                user_prompt=user_prompt,
                project_prompt=project_prompt,
                # No relevant hits → switch to the general-knowledge
                # variant which drops the "Retrieved context" framing
                # entirely. Small models confabulate when given an
                # empty/irrelevant context block.
                has_relevant_hits=hits_relevant > 0,
            )
            messages: list[ChatMessage] = [
                ChatMessage(role=ChatRole.SYSTEM, content=system_content),
                *history_msgs,
                ChatMessage(role=ChatRole.USER, content=user_message),
            ]

            # 3. Generation phase — stream from C8 LLM gateway. Each
            #    yielded chunk is an OpenAI SSE event ; we extract
            #    `choices[0].delta.content` and re-emit as a plain SSE
            #    message event for the C3 client.
            t_generate = time.perf_counter()
            yield _emit(
                name="generate",
                status="running",
                label="Asking the language model",
            )
            request = ChatCompletionRequest(messages=messages, stream=True)
            collected_tokens: list[str] = []
            async with self._llm.chat_completion_stream(
                request,
                agent_name="c3-rag",
                session_id=str(conversation_id),
                tenant_id=tenant_id,
                project_id=project_id,
            ) as chunks:
                async for chunk in chunks:
                    delta = _extract_delta_content(chunk)
                    if delta:
                        collected_tokens.append(delta)
                        # SSE escape: replace any embedded newlines
                        # so they don't break the SSE framing.
                        safe = delta.replace("\n", "\\n")
                        yield f"data: {safe}\n\n"
            generate_ms = int((time.perf_counter() - t_generate) * 1000)
            total_tokens = sum(len(t) for t in collected_tokens)  # char count
            yield _emit(
                name="generate",
                status="done",
                label=f"{total_tokens} chars generated",
                duration_ms=generate_ms,
                stats={"chars": total_tokens, "deltas": len(collected_tokens)},
            )

            total_ms = int((time.perf_counter() - t_start) * 1000)
            yield _emit(
                name="done",
                status="done",
                label="Reply ready",
                duration_ms=total_ms,
            )
            yield "data: [DONE]\n\n"

            # 4. Persist the assistant reply along with the pipeline
            #    timeline so a navigation / refresh re-renders the same
            #    chip + collapsible panel the operator saw live.
            full_reply = "".join(collected_tokens).strip()
            if full_reply:
                assistant_msg = await self._repo.append_message(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=full_reply,
                    stages=collected_stages,
                )
                # 5. Phase E — feed the turn back into C7 so follow-up
                #    questions can retrieve it. Best-effort: a memory
                #    failure here SHALL NOT break the user-facing reply
                #    (the SSE stream has already emitted [DONE]).
                turn_id = (
                    str(assistant_msg["id"])
                    if isinstance(assistant_msg, dict) and "id" in assistant_msg
                    else f"t-{datetime.now(UTC).isoformat()}"
                )
                # Conversation memory loop is opportunistic; quota /
                # embedder hiccups SHALL NOT propagate to the caller
                # whose SSE stream has already closed with [DONE].
                with contextlib.suppress(Exception):
                    await self._memory.ingest_conversation_turn(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        conversation_id=str(conversation_id),
                        turn_id=turn_id,
                        user_message=user_message,
                        assistant_reply=full_reply,
                        actor_id=str(conversation_id),
                        # Remote variant raises NotImplementedError here
                        # in v1; the suppress() catches it so chat
                        # streaming is unaffected.
                        user_id=user_id,
                        user_roles=user_roles,
                    )

        return _generate()

    async def _recent_history_messages(
        self,
        conversation_id: UUID,
        *,
        exclude_id: UUID | None,
    ) -> list[ChatMessage]:
        """Fetch the last N messages and convert to OpenAI-style chat
        messages for the LLM prompt. The just-persisted user message
        is omitted (we add it explicitly in the prompt builder)."""
        rows = await self._repo.list_messages(conversation_id)
        # `rows` are persisted in chronological order (oldest first);
        # take the LAST `rag_history_turns * 2` items so we keep both
        # sides of recent exchanges.
        recent = rows[-(self._rag_history_turns * 2 + 1) :-1]  # drop the just-saved user message
        out: list[ChatMessage] = []
        for row in recent:
            role = MessageRole(row["role"])
            chat_role = ChatRole.USER if role == MessageRole.USER else ChatRole.ASSISTANT
            out.append(ChatMessage(role=chat_role, content=row["content"]))
        return out

    # ------------------------------------------------------------------
    # Expert mode events (NATS stub — R-100-074)
    # ------------------------------------------------------------------

    @staticmethod
    async def expert_mode_stream() -> AsyncIterator[str]:
        """SSE stream for pipeline telemetry events.

        Returns a single 'unavailable' event per R-100-074: when NATS is
        not yet deployed, expert mode is declared unavailable rather than
        silently dropping events.
        """
        yield 'data: {"type":"unavailable","reason":"pipeline telemetry not yet implemented"}\n\n'


def get_service(repo: ConversationRepository) -> ConversationService:
    return ConversationService(repo)


# ---------------------------------------------------------------------------
# Phase D helpers — RAG prompt assembly + LLM stream parsing
# ---------------------------------------------------------------------------


_RAG_SYSTEM_PROMPT = (
    "You are a helpful assistant for project {project_id}.\n\n"
    "You draw on two sources of knowledge :\n"
    "1. The retrieved excerpts from the project's source documents "
    "(shown below) — AUTHORITATIVE for project-specific questions ; "
    "cite which excerpt ([1], [2]…) you used.\n"
    "2. Your general world knowledge — use freely for general questions "
    "(geography, common facts, language, code patterns, etc.) when the "
    "excerpts don't cover the topic.\n\n"
    "When answering :\n"
    "- For project-specific questions, prefer the retrieved excerpts and "
    "cite them.\n"
    "- For general / out-of-corpus questions, answer directly from your "
    "training — don't refuse just because the excerpts don't cover it.\n"
    "- If the answer mixes both, combine them naturally and indicate "
    "which part came from the project sources.\n"
    "- Respond in the same language as the user's question.\n\n"
    "Retrieved context :\n{context}"
)


_GENERAL_SYSTEM_PROMPT = (
    "You are a helpful assistant for project {project_id}.\n\n"
    "The project's source documents do not cover this question, so "
    "answer from your general knowledge alone. Be precise and concise. "
    "If you don't know the answer, say so plainly — do NOT invent.\n"
    "Respond in the same language as the user's question."
)
"""Fallback system prompt used when retrieval surfaced no chunks above
`_RAG_MIN_SCORE`. Drops the "Retrieved context" framing entirely —
small models (qwen2.5:3b on CPU) otherwise try to reconcile their
answer with the empty/irrelevant context block and produce
hallucinated bridges ("Paris as capital of the Hispanic kingdom…"
for "capitale de l'Espagne" being the canonical observed failure
mode). Keeping the user / project behavioural preambles on top of
this prompt is still correct — they aren't tied to retrieval."""


def _assemble_system_prompt(
    *,
    project_id: str,
    context: str,
    user_prompt: str | None,
    project_prompt: str | None,
    has_relevant_hits: bool,
) -> str:
    """Compose the LLM system message in the user-mandated order :
    user behavioural prompt → project behavioural prompt → RAG
    instructions + context (or a general-knowledge variant when no
    retrieved chunk cleared the relevance threshold). Empty / None
    preambles are silently skipped so the LLM sees a clean prompt
    without empty section headers."""
    sections: list[str] = []
    user_clean = (user_prompt or "").strip()
    if user_clean:
        sections.append(f"[User instructions]\n{user_clean}")
    project_clean = (project_prompt or "").strip()
    if project_clean:
        sections.append(f"[Project instructions]\n{project_clean}")
    if has_relevant_hits:
        sections.append(
            _RAG_SYSTEM_PROMPT.format(project_id=project_id, context=context),
        )
    else:
        sections.append(_GENERAL_SYSTEM_PROMPT.format(project_id=project_id))
    return "\n\n".join(sections)


_RAG_MIN_SCORE = 0.4
"""Minimum cosine similarity for a retrieved chunk to be included in
the LLM context. Below this threshold the chunk is statistically
unrelated to the user's query — keeping it in the prompt confuses
small models (they latch onto the irrelevant excerpts instead of
falling back to general knowledge). The 0.4 threshold is empirical
for `all-minilm` embeddings ; tune per embedding adapter when
swapping models."""


def _format_retrieved_chunks(hits: list[Any]) -> str:
    """Render a list of `RetrievalHit` into a numbered context block.
    Filters out hits below `_RAG_MIN_SCORE` — the LLM should fall back
    to general knowledge when nothing relevant is found rather than
    hallucinating against weak hits.

    Empty list (after filtering) → a placeholder so the prompt's
    'answer from general knowledge' branch fires."""
    if not hits:
        return "(no excerpts retrieved from the project's sources)"
    relevant = [h for h in hits if getattr(h, "score", 0.0) >= _RAG_MIN_SCORE]
    if not relevant:
        return (
            "(no excerpts above the relevance threshold — the retrieved "
            "chunks scored below "
            f"{_RAG_MIN_SCORE} cosine similarity, treat as no project context)"
        )
    lines: list[str] = []
    for i, hit in enumerate(relevant, start=1):
        # Hits are RetrievalHit Pydantic instances; access by attribute.
        snippet = getattr(hit, "content", "") or ""
        # Trim long chunks so the prompt stays within model context.
        snippet = snippet.strip()
        if len(snippet) > 800:
            snippet = snippet[:800] + "…"
        source = getattr(hit, "source_id", None) or "unknown"
        score = getattr(hit, "score", 0.0)
        lines.append(f"[{i}] (source={source}, score={score:.3f})\n{snippet}")
    return "\n\n".join(lines)


def _hit_stats(hits: list[Any]) -> tuple[int, int, float]:
    """Summarise a retrieval-hit list for the stage event. Returns
    `(total, above_threshold, top_score)`. `top_score` is rounded to
    3 decimals so the JSON payload stays small."""
    total = len(hits)
    above = sum(1 for h in hits if getattr(h, "score", 0.0) >= _RAG_MIN_SCORE)
    top = max((getattr(h, "score", 0.0) for h in hits), default=0.0)
    return total, above, round(float(top), 3)


def _extract_delta_content(chunk: dict[str, Any]) -> str:
    """Pull the streamed token text out of an OpenAI-shaped chunk.

    Defensive: chunk may lack `choices` (final usage event), or the
    delta may be empty (role-only first event). Returns "" in those
    cases so the caller can simply concatenate.
    """
    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    return content if isinstance(content, str) else ""
