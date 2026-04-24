# =============================================================================
# File: test_service.py
# Version: 1
# Path: ay_platform_core/tests/unit/c3_conversation/test_service.py
# Description: Unit tests for ConversationService — mocked repository.
#              Covers CRUD access control, soft-delete, SSE generation,
#              and expert-mode stub.
# =============================================================================

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from ay_platform_core.c3_conversation.models import (
    ConversationCreate,
    ConversationUpdate,
)
from ay_platform_core.c3_conversation.service import ConversationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_A = "user-a"
USER_B = "user-b"


def _make_conv_doc(owner_id: str = USER_A, deleted: bool = False) -> dict[str, Any]:
    conv_id = uuid4()
    now = datetime.now(UTC).isoformat()
    return {
        "id": str(conv_id),
        "owner_id": owner_id,
        "project_id": None,
        "title": "Test conversation",
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
        "deleted": deleted,
    }


def _make_msg_doc(conv_id: UUID) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "conversation_id": str(conv_id),
        "role": "user",
        "content": "hello",
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _make_repo(**overrides: Any) -> MagicMock:
    repo = MagicMock()
    repo.list_conversations = AsyncMock(return_value=[])
    repo.create_conversation = AsyncMock(return_value=_make_conv_doc())
    repo.get_conversation = AsyncMock(return_value=None)
    repo.update_conversation = AsyncMock(return_value=None)
    repo.soft_delete_conversation = AsyncMock(return_value=None)
    repo.list_messages = AsyncMock(return_value=[])
    repo.append_message = AsyncMock(return_value=_make_msg_doc(uuid4()))
    for k, v in overrides.items():
        setattr(repo, k, v)
    return repo


# ---------------------------------------------------------------------------
# list_conversations
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_conversations_returns_public_models() -> None:
    doc = _make_conv_doc()
    repo = _make_repo(list_conversations=AsyncMock(return_value=[doc]))
    svc = ConversationService(repo)
    result = await svc.list_conversations(USER_A)
    assert len(result) == 1
    assert str(result[0].id) == doc["id"]
    assert result[0].owner_id == USER_A


# ---------------------------------------------------------------------------
# create_conversation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_conversation() -> None:
    doc = _make_conv_doc()
    repo = _make_repo(create_conversation=AsyncMock(return_value=doc))
    svc = ConversationService(repo)
    result = await svc.create_conversation(USER_A, ConversationCreate(title="My conv"))
    assert result.title == doc["title"]
    assert result.owner_id == USER_A


# ---------------------------------------------------------------------------
# get_conversation — access control
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_conversation_owner_allowed() -> None:
    doc = _make_conv_doc(owner_id=USER_A)
    repo = _make_repo(get_conversation=AsyncMock(return_value=doc))
    svc = ConversationService(repo)
    result = await svc.get_conversation(UUID(doc["id"]), USER_A)
    assert str(result.id) == doc["id"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_conversation_other_user_forbidden() -> None:
    doc = _make_conv_doc(owner_id=USER_A)
    repo = _make_repo(get_conversation=AsyncMock(return_value=doc))
    svc = ConversationService(repo)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_conversation(UUID(doc["id"]), USER_B)
    assert exc_info.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_conversation_not_found_raises_404() -> None:
    repo = _make_repo(get_conversation=AsyncMock(return_value=None))
    svc = ConversationService(repo)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_conversation(uuid4(), USER_A)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# update_conversation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_conversation_title() -> None:
    doc = _make_conv_doc(owner_id=USER_A)
    updated = {**doc, "title": "New title"}
    repo = _make_repo(
        get_conversation=AsyncMock(return_value=doc),
        update_conversation=AsyncMock(return_value=updated),
    )
    svc = ConversationService(repo)
    result = await svc.update_conversation(
        UUID(doc["id"]), USER_A, ConversationUpdate(title="New title")
    )
    assert result.title == "New title"


# ---------------------------------------------------------------------------
# delete_conversation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_conversation_calls_soft_delete() -> None:
    doc = _make_conv_doc(owner_id=USER_A)
    soft_delete = AsyncMock()
    repo = _make_repo(
        get_conversation=AsyncMock(return_value=doc),
        soft_delete_conversation=soft_delete,
    )
    svc = ConversationService(repo)
    await svc.delete_conversation(UUID(doc["id"]), USER_A)
    soft_delete.assert_called_once_with(UUID(doc["id"]))


# ---------------------------------------------------------------------------
# send_message_stream (SSE)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_stream_yields_sse_chunks() -> None:
    doc = _make_conv_doc(owner_id=USER_A)
    repo = _make_repo(get_conversation=AsyncMock(return_value=doc))
    svc = ConversationService(repo)
    stream = await svc.send_message_stream(UUID(doc["id"]), USER_A, "hello")
    chunks: list[str] = []
    async for chunk in stream:
        chunks.append(chunk)
    assert any(c.startswith("data: ") for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_stream_persists_user_message() -> None:
    doc = _make_conv_doc(owner_id=USER_A)
    append = AsyncMock(return_value=_make_msg_doc(UUID(doc["id"])))
    repo = _make_repo(
        get_conversation=AsyncMock(return_value=doc),
        append_message=append,
    )
    svc = ConversationService(repo)
    stream = await svc.send_message_stream(UUID(doc["id"]), USER_A, "hello")
    async for _ in stream:
        pass
    # First call: user message
    first_call = append.call_args_list[0]
    assert first_call.kwargs["role"] == "user"
    assert first_call.kwargs["content"] == "hello"


# ---------------------------------------------------------------------------
# expert_mode_stream (NATS stub)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_expert_mode_stream_yields_unavailable_event() -> None:
    chunks: list[str] = []
    async for chunk in ConversationService.expert_mode_stream():
        chunks.append(chunk)
    assert len(chunks) == 1
    assert '"type":"unavailable"' in chunks[0]
