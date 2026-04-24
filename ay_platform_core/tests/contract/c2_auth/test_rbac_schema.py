# =============================================================================
# File: test_rbac_schema.py
# Version: 2
# Path: ay_platform_core/tests/contract/c2_auth/test_rbac_schema.py
# Description: Contract tests — RBAC roles match E-100-002 exactly.
# =============================================================================

from __future__ import annotations

from typing import ClassVar

import pytest

from ay_platform_core.c2_auth.models import RBACGlobalRole, RBACProjectRole


@pytest.mark.contract
class TestRBACGlobalRoleContract:
    """E-100-002: three global roles, exact string values."""

    EXPECTED_GLOBAL_ROLES: ClassVar[set[str]] = {"admin", "tenant_admin", "user"}

    def test_global_roles_exact_set(self) -> None:
        assert set(RBACGlobalRole) == self.EXPECTED_GLOBAL_ROLES

    def test_admin_value(self) -> None:
        assert RBACGlobalRole.ADMIN.value == "admin"

    def test_tenant_admin_value(self) -> None:
        assert RBACGlobalRole.TENANT_ADMIN.value == "tenant_admin"

    def test_user_value(self) -> None:
        assert RBACGlobalRole.USER.value == "user"

    def test_roles_are_str_enum(self) -> None:
        for role in RBACGlobalRole:
            assert isinstance(role, str)


@pytest.mark.contract
class TestRBACProjectRoleContract:
    """E-100-002: three project-scoped roles, exact string values."""

    EXPECTED_PROJECT_ROLES: ClassVar[set[str]] = {
        "project_owner", "project_editor", "project_viewer"
    }

    def test_project_roles_exact_set(self) -> None:
        assert set(RBACProjectRole) == self.EXPECTED_PROJECT_ROLES

    def test_owner_value(self) -> None:
        assert RBACProjectRole.OWNER.value == "project_owner"

    def test_editor_value(self) -> None:
        assert RBACProjectRole.EDITOR.value == "project_editor"

    def test_viewer_value(self) -> None:
        assert RBACProjectRole.VIEWER.value == "project_viewer"

    def test_roles_are_str_enum(self) -> None:
        for role in RBACProjectRole:
            assert isinstance(role, str)
