# =============================================================================
# File: models.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c3_conversation/models.py
# Description: Pydantic v2 data contracts for C3 Conversation Service.
#              ConversationPublic and MessagePublic are registered as
#              platform contracts (consumed by C1, C4, future UI).
# @relation R-100-003 D-008
# =============================================================================

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
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


class MessagePublic(BaseModel):
    """Public view of a single message."""

    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    timestamp: datetime


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
    content: str = Field(min_length=1)


class ConversationListResponse(BaseModel):
    conversations: list[ConversationPublic]


class ConversationResponse(BaseModel):
    conversation: ConversationPublic


class MessageListResponse(BaseModel):
    messages: list[MessagePublic]


class MessageResponse(BaseModel):
    message: MessagePublic
