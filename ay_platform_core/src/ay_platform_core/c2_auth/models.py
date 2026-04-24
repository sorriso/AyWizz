# =============================================================================
# File: models.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c2_auth/models.py
# Description: Pydantic v2 models for C2 Auth Service public contracts.
#              JWTClaims implements E-100-001.
#              RBACGlobalRole / RBACProjectRole implement E-100-002.
#
# @relation implements:E-100-001
# @relation implements:E-100-002
# =============================================================================

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RBACGlobalRole(StrEnum):
    """Global platform roles embedded in JWT claims.roles. E-100-002.

    @relation implements:E-100-002
    """

    ADMIN = "admin"
    TENANT_ADMIN = "tenant_admin"
    USER = "user"


class RBACProjectRole(StrEnum):
    """Per-project roles embedded in JWT claims.project_scopes. E-100-002.

    @relation implements:E-100-002
    """

    OWNER = "project_owner"
    EDITOR = "project_editor"
    VIEWER = "project_viewer"


class UserStatus(StrEnum):
    """Lifecycle status of a platform user account."""

    ACTIVE = "active"
    DISABLED = "disabled"


class JWTClaims(BaseModel):
    """Platform-internal JWT claim set. All auth modes emit this structure.

    @relation implements:E-100-001
    @relation implements:R-100-038
    """

    iss: Literal["platform-auth"] = "platform-auth"
    sub: str
    aud: str = "platform"
    iat: int
    exp: int
    jti: str
    auth_mode: Literal["none", "local", "sso"]
    tenant_id: str
    roles: list[RBACGlobalRole]
    project_scopes: dict[str, list[RBACProjectRole]] = Field(default_factory=dict)
    name: str | None = None
    email: str | None = None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """JSON body for POST /auth/login."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Successful authentication response."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class AuthConfigResponse(BaseModel):
    """Response for GET /auth/config (public endpoint)."""

    auth_mode: Literal["none", "local", "sso"]


# ---------------------------------------------------------------------------
# User management models
# ---------------------------------------------------------------------------


class UserPublic(BaseModel):
    """User data safe for external exposure. Hash and lock fields excluded."""

    user_id: str
    username: str
    tenant_id: str
    roles: list[RBACGlobalRole]
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime
    name: str | None = None
    email: str | None = None


class UserInternal(UserPublic):
    """Full user record including credential hash. Never leaves repository layer."""

    model_config = ConfigDict(populate_by_name=True)

    argon2id_hash: str
    failed_attempts: int = 0
    locked_until: datetime | None = None


class UserCreateRequest(BaseModel):
    """Request body for POST /auth/users."""

    username: str
    password: str
    tenant_id: str
    roles: list[RBACGlobalRole] = Field(default_factory=lambda: [RBACGlobalRole.USER])
    name: str | None = None
    email: str | None = None


class UserUpdateRequest(BaseModel):
    """Request body for PATCH /auth/users/{user_id}."""

    roles: list[RBACGlobalRole] | None = None
    status: UserStatus | None = None
    name: str | None = None
    email: str | None = None


class ResetPasswordRequest(BaseModel):
    """Request body for POST /auth/users/{user_id}/reset-password."""

    new_password: str


class SessionInfo(BaseModel):
    """Active session record for admin visibility."""

    session_id: str
    user_id: str
    issued_at: datetime
    expires_at: datetime
    active: bool
