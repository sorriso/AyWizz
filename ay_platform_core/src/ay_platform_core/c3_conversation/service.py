# =============================================================================
# File: service.py
# Version: 2
# Path: ay_platform_core/src/ay_platform_core/c3_conversation/service.py
# Description: C3 Conversation Service facade.
#              Orchestrates CRUD and the SSE message-send flow.
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
    return MessagePublic(
        id=UUID(doc["id"]),
        conversation_id=UUID(doc["conversation_id"]),
        role=MessageRole(doc["role"]),
        content=doc["content"],
        timestamp=doc["timestamp"],
    )


class ConversationService:
    def __init__(
        self,
        repo: ConversationRepository,
        *,
        memory_service: MemoryService | None = None,
        llm_client: LLMGatewayClient | None = None,
        rag_top_k: int = 5,
        rag_history_turns: int = 6,
    ) -> None:
        self._repo = repo
        # Phase D wiring — optional. When BOTH are provided AND the
        # conversation has a project_id, `send_message_stream` runs the
        # RAG pipeline; otherwise it falls back to the static stub.
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
                user_message=content,
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
        user_message: str,
    ) -> AsyncIterator[str]:
        async def _generate() -> AsyncIterator[str]:
            # 1. Retrieve top-K chunks from C7.
            assert self._memory is not None  # narrowed in caller
            assert self._llm is not None
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
            )
            context_block = _format_retrieved_chunks(retrieval.hits)

            # 2. Build prompt: system + context + recent history + user.
            history_msgs = await self._recent_history_messages(
                conversation_id, exclude_id=None,
            )
            messages: list[ChatMessage] = [
                ChatMessage(
                    role=ChatRole.SYSTEM,
                    content=_RAG_SYSTEM_PROMPT.format(
                        project_id=project_id,
                        context=context_block,
                    ),
                ),
                *history_msgs,
                ChatMessage(role=ChatRole.USER, content=user_message),
            ]

            # 3. Stream from C8 LLM gateway. Each yielded chunk is an
            #    OpenAI SSE event; we extract `choices[0].delta.content`
            #    and re-emit as a plain SSE for the C3 client.
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
            yield "data: [DONE]\n\n"

            # 4. Persist the assistant reply.
            full_reply = "".join(collected_tokens).strip()
            if full_reply:
                assistant_msg = await self._repo.append_message(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=full_reply,
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
    "You are an assistant for project {project_id}. Use the following "
    "retrieved excerpts from the project's source documents to answer "
    "the user's question. If the excerpts do not contain the answer, "
    "say so honestly rather than fabricating.\n\n"
    "Retrieved context:\n{context}"
)


def _format_retrieved_chunks(hits: list[Any]) -> str:
    """Render a list of `RetrievalHit` into a numbered context block.
    Empty list → a placeholder so the LLM sees "no context"."""
    if not hits:
        return "(no relevant excerpts retrieved from the project's sources)"
    lines: list[str] = []
    for i, hit in enumerate(hits, start=1):
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
