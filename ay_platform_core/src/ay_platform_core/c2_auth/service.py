# =============================================================================
# File: service.py
# Version: 1
# Path: ay_platform_core/src/ay_platform_core/c2_auth/service.py
# Description: C2 Auth Service facade. Orchestrates pluggable auth modes,
#              JWT issuance/verification, and user management.
#
# @relation implements:R-100-030
# @relation implements:R-100-038
# @relation implements:R-100-073
# =============================================================================

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache

import jwt
from fastapi import HTTPException, status

from ay_platform_core.c2_auth.config import AuthConfig
from ay_platform_core.c2_auth.db.repository import AuthRepository
from ay_platform_core.c2_auth.models import (
    AuthConfigResponse,
    JWTClaims,
    LoginRequest,
    RBACProjectRole,
    ResetPasswordRequest,
    SessionInfo,
    TokenResponse,
    UserCreateRequest,
    UserInternal,
    UserPublic,
    UserStatus,
    UserUpdateRequest,
)
from ay_platform_core.c2_auth.modes.base import AuthMode
from ay_platform_core.c2_auth.modes.local_mode import LocalMode
from ay_platform_core.c2_auth.modes.none_mode import NoneMode
from ay_platform_core.c2_auth.modes.sso_mode import SSOMode

_FORBIDDEN_ENVIRONMENTS = {"production", "staging"}


class AuthService:
    """Facade for C2 Auth Service operations.

    Owns JWT issuance, verification, session tracking, and user CRUD.
    Auth mode selection is pluggable (none / local / sso). R-100-030.

    @relation implements:R-100-030
    @relation implements:R-100-038
    """

    def __init__(
        self,
        config: AuthConfig,
        repo: AuthRepository | None = None,
    ) -> None:
        # R-100-032: fail fast if none mode is used in prod/staging.
        if (
            config.auth_mode == "none"
            and config.platform_environment in _FORBIDDEN_ENVIRONMENTS
        ):
            raise RuntimeError(
                f"Auth mode 'none' is forbidden in "
                f"'{config.platform_environment}' environment. "
                "Set AUTH_MODE=local or AUTH_MODE=sso."
            )
        self._config = config
        self._repo = repo
        self._mode: AuthMode = self._build_mode()

    # ---- Internal helpers ---------------------------------------------------

    def _build_mode(self) -> AuthMode:
        match self._config.auth_mode:
            case "none":
                return NoneMode(self._config)
            case "local":
                if self._repo is None:
                    raise RuntimeError("AuthRepository required for auth_mode='local'")
                return LocalMode(self._repo)
            case "sso":
                return SSOMode()

    def _signing_key(self) -> str:
        if self._config.jwt_algorithm == "HS256":
            return self._config.jwt_secret_key
        return self._config.jwt_private_key

    def _verification_key(self) -> str:
        if self._config.jwt_algorithm == "HS256":
            return self._config.jwt_secret_key
        return self._config.jwt_public_key

    def _sign_jwt(self, claims: JWTClaims) -> str:
        payload = claims.model_dump(mode="json")
        return jwt.encode(payload, self._signing_key(), algorithm=self._config.jwt_algorithm)

    def _decode_jwt(self, token: str) -> JWTClaims:
        try:
            payload = jwt.decode(
                token,
                self._verification_key(),
                algorithms=[self._config.jwt_algorithm],
                audience="platform",
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            ) from None
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
            ) from exc
        return JWTClaims(**payload)

    def _require_repo(self) -> AuthRepository:
        if self._repo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This operation requires auth_mode='local'",
            )
        return self._repo

    # ---- Public API ---------------------------------------------------------

    def config_response(self) -> AuthConfigResponse:
        return AuthConfigResponse(auth_mode=self._config.auth_mode)

    async def issue_token(self, request: LoginRequest) -> TokenResponse:
        """Authenticate credentials and return a signed JWT. R-100-038."""
        user = await self._mode.authenticate(request)
        now = datetime.now(UTC)
        jti = str(uuid.uuid4())
        exp_ts = int(now.timestamp()) + self._config.token_ttl_seconds
        expires_at = datetime.fromtimestamp(exp_ts, tz=UTC)

        # Fetch project-scoped roles if a repository is available.
        project_scopes_raw: dict[str, list[str]] = {}
        if self._repo is not None:
            project_scopes_raw = await self._repo.get_project_scopes(user.user_id)

        project_scopes: dict[str, list[RBACProjectRole]] = {
            pid: [RBACProjectRole(r) for r in roles]
            for pid, roles in project_scopes_raw.items()
        }

        claims = JWTClaims(
            sub=user.user_id,
            iat=int(now.timestamp()),
            exp=exp_ts,
            jti=jti,
            auth_mode=self._config.auth_mode,
            tenant_id=user.tenant_id,
            roles=user.roles,
            project_scopes=project_scopes,
            name=user.name,
            email=user.email,
        )
        token = self._sign_jwt(claims)

        # Persist session for stateful revocation (none mode skips DB).
        if self._repo is not None:
            await self._repo.insert_session(jti, user.user_id, now, expires_at)

        return TokenResponse(access_token=token, expires_in=self._config.token_ttl_seconds)

    async def verify_token(self, token: str) -> JWTClaims:
        """Decode and validate JWT, checking active session. R-100-073."""
        claims = self._decode_jwt(token)

        # Stateful revocation check: jti must exist and be active. (A-6 plan)
        if self._repo is not None:
            session = await self._repo.get_session(claims.jti)
            if session is None or not session.get("active", False):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session has been revoked",
                )
        return claims

    async def logout(self, jti: str) -> None:
        """Mark session inactive (token remains syntactically valid until exp)."""
        if self._repo is not None:
            await self._repo.deactivate_session(jti)

    # ---- User CRUD (local mode only) ----------------------------------------

    async def create_user(self, request: UserCreateRequest) -> UserPublic:
        repo = self._require_repo()
        user_id = str(uuid.uuid4())
        argon2id_hash = LocalMode.hash_password(request.password)
        user = UserInternal(
            user_id=user_id,
            username=request.username,
            tenant_id=request.tenant_id,
            roles=request.roles,
            status=UserStatus.ACTIVE,
            created_at=datetime.now(UTC),
            name=request.name,
            email=request.email,
            argon2id_hash=argon2id_hash,
        )
        await repo.insert_user(user)
        return UserPublic.model_validate(user.model_dump())

    async def get_user(self, user_id: str) -> UserPublic:
        repo = self._require_repo()
        user = await repo.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return UserPublic.model_validate(user.model_dump())

    async def update_user(self, user_id: str, request: UserUpdateRequest) -> UserPublic:
        repo = self._require_repo()
        existing = await repo.get_user_by_id(user_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        patch: dict[str, object] = {}
        if request.roles is not None:
            patch["roles"] = [r.value for r in request.roles]
        if request.status is not None:
            patch["status"] = request.status.value
        if request.name is not None:
            patch["name"] = request.name
        if request.email is not None:
            patch["email"] = request.email

        if patch:
            await repo.update_user(user_id, patch)

        updated = await repo.get_user_by_id(user_id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return UserPublic.model_validate(updated.model_dump())

    async def disable_user(self, user_id: str) -> None:
        repo = self._require_repo()
        existing = await repo.get_user_by_id(user_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        await repo.update_user(user_id, {"status": UserStatus.DISABLED.value})

    async def reset_password(self, user_id: str, request: ResetPasswordRequest) -> None:
        """Admin-only password reset. No self-service in v1. R-100-035."""
        repo = self._require_repo()
        existing = await repo.get_user_by_id(user_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        new_hash = LocalMode.hash_password(request.new_password)
        await repo.update_user(user_id, {"argon2id_hash": new_hash})
        await repo.reset_failed_attempts(user_id)

    # ---- Session management (admin only) ------------------------------------

    async def list_sessions(self) -> list[SessionInfo]:
        repo = self._require_repo()
        return await repo.list_active_sessions()

    async def revoke_session(self, session_id: str) -> None:
        repo = self._require_repo()
        await repo.deactivate_session(session_id)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _build_cached_service() -> AuthService:
    """Build and cache the singleton AuthService from environment config."""
    config = AuthConfig()
    repo: AuthRepository | None = None
    if config.auth_mode != "none":
        repo = AuthRepository.from_config(
            config.arango_url,
            config.arango_db_name,
            config.arango_username,
            config.arango_password,
        )
    return AuthService(config, repo)


def get_service() -> AuthService:
    """FastAPI dependency. Override via app.dependency_overrides in tests."""
    return _build_cached_service()
