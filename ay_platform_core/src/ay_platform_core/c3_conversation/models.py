# =============================================================================
# File: models.py
# Version: 3
# Path: ay_platform_core/src/ay_platform_core/c3_conversation/models.py
# Description: Pydantic v2 data contracts for C3 Conversation Service.
#              ConversationPublic and MessagePublic are registered as
#              platform contracts (consumed by C1, C4, future UI).
#
#              v3: `StageRecord` + `MessagePublic.stages` persist the
#              pipeline timeline (retrieve / generate / done phases
#              with durations + stats) alongside the assistant message.
#              The UX re-renders the same chip + collapsible panel on
#              navigation / reload, where previously the timeline was
#              transient (client-only `liveStages` state).
#
#              v2: `MessageRequest` carries optional `user_prompt` and
#              `project_prompt` fields. The UX fetches these from C2
#              at session start (user prefs) / project navigation
#              (project settings) and forwards them per-message so C3
#              can prepend both ahead of the RAG context block.
# @relation R-100-003 D-008
# =============================================================================

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


# ---------------------------------------------------------------------------
# Public contracts (exposed via contract registry)
# ---------------------------------------------------------------------------


class ConversationPublic(BaseModel):
    """Public view of a conversation — no internal metadata."""

    id: UUID
    owner_id: str
    project_id: str | None = None
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class StageRecord(BaseModel):
    """One pipeline phase persisted alongside an assistant message.
    Mirrors the SSE `event: stage` payload emitted during the live
    stream so the UX can re-render the same chip + timeline after a
    page reload — without this, the timeline was transient (client-
    only state) and disappeared on navigation. Only `done` events are
    stored ; the `running` events are intermediate signals for the
    live UI and have no `duration_ms`."""

    name: str
    status: Literal["running", "done"] = "done"
    label: str
    duration_ms: int | None = None
    stats: dict[str, Any] | None = None


class MessagePublic(BaseModel):
    """Public view of a single message."""

    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    timestamp: datetime
    stages: list[StageRecord] | None = Field(
        default=None,
        description="Pipeline timeline captured during the SSE stream "
        "(assistant messages only). None for user messages and for "
        "legacy assistant messages persisted before this field was "
        "introduced.",
    )


# ---------------------------------------------------------------------------
# Internal model (includes ArangoDB _key, soft-delete flag)
# ---------------------------------------------------------------------------


class ConversationInternal(BaseModel):
    """Full conversation record as stored in ArangoDB."""

    id: UUID
    owner_id: str
    project_id: str | None = None
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    deleted: bool = False


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


class ConversationCreate(BaseModel):
    title: str = Field(default="New Conversation", max_length=255)
    project_id: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    project_id: str | None = None


class MessageRequest(BaseModel):
    """User-sent message + optional behavioural prompts forwarded by
    the UX. `user_prompt` and `project_prompt` are the EFFECTIVE
    values resolved by C2 (override OR default) and are prepended in
    that order to the system prompt the LLM receives, BEFORE the RAG
    context block. Either field is optional ; missing/empty values
    are silently dropped from the assembled prompt."""

    content: str = Field(min_length=1)
    user_prompt: str | None = Field(default=None, max_length=4000)
    project_prompt: str | None = Field(default=None, max_length=4000)


class ConversationListResponse(BaseModel):
    conversations: list[ConversationPublic]


class ConversationResponse(BaseModel):
    conversation: ConversationPublic


class MessageListResponse(BaseModel):
    messages: list[MessagePublic]


class MessageResponse(BaseModel):
    message: MessagePublic
