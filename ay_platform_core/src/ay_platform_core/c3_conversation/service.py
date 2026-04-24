# =============================================================================
# File: service.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c3_conversation/service.py
# Description: C3 Conversation Service facade.
#              Orchestrates CRUD and the SSE message-send flow.
#              C4 delegation is a stub until the orchestrator is implemented.
#              Expert-mode NATS subscription is a declared-unavailable stub
#              per R-100-074 (NATS degraded-mode behaviour).
# @relation R-100-003 R-100-074 D-008
# =============================================================================

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
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
    def __init__(self, repo: ConversationRepository) -> None:
        self._repo = repo

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
    ) -> AsyncIterator[str]:
        """Persist user message, yield SSE chunks for the assistant reply.

        C4 delegation is a stub: a static placeholder is streamed until
        the orchestrator is implemented. The stub reply is persisted so
        that message history remains consistent.
        """
        await self._require_access(conversation_id, user_id)

        # Persist user message
        await self._repo.append_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
        )

        # C4 stub — stream a deterministic placeholder reply
        stub_reply = (
            "C4 orchestrator is not yet implemented. "
            "Your message has been saved and will be processed "
            "once the pipeline is available."
        )

        async def _generate() -> AsyncIterator[str]:
            for word in stub_reply.split():
                yield f"data: {word} \n\n"
                await asyncio.sleep(0)  # yield control to event loop
            yield "data: [DONE]\n\n"

            # Persist assistant reply after stream completes
            await self._repo.append_message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=stub_reply,
            )

        return _generate()

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
