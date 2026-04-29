// =============================================================================
// File: navbar.test.tsx
// Version: 1
// Path: ay_platform_ui/tests/integration/navbar.test.tsx
// Description: Integration tests for <Navbar>. Brand from ConfigProvider,
//              user info from AuthProvider claims, logout button
//              clears auth + redirects.
// =============================================================================

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/app/auth-provider";
import { ConfigProvider } from "@/app/providers";
import { Navbar } from "@/components/navbar";

import { fakeJWT } from "../helpers/msw-handlers";

const { mockRouter } = vi.hoisted(() => ({
  mockRouter: {
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
}));

beforeEach(() => {
  mockRouter.push.mockClear();
});

const NOW = Math.floor(Date.now() / 1000);

function seedAuthenticated(claims: Record<string, unknown> = {}): void {
  const token = fakeJWT({
    sub: "user-alice",
    username: "alice",
    tenant_id: "tenant-x",
    roles: ["project_editor"],
    exp: NOW + 3600,
    iat: NOW,
    ...claims,
  });
  window.localStorage.setItem("aywizz.token", token);
}

function renderNavbar() {
  return render(
    <ConfigProvider>
      <AuthProvider>
        <Navbar />
      </AuthProvider>
    </ConfigProvider>,
  );
}

describe("Navbar rendering", () => {
  it("renders nothing while AuthProvider is not authenticated", async () => {
    // No token seeded → AuthProvider hydrates as anonymous → navbar
    // returns null per its defensive guard.
    const { container } = renderNavbar();
    // Wait long enough for any potential async render.
    await waitFor(() => {
      // Should NOT contain a header element.
      expect(container.querySelector("header")).toBeNull();
    });
  });

  it("renders brand short_name from ConfigProvider once authenticated", async () => {
    seedAuthenticated();
    renderNavbar();

    await waitFor(() => {
      expect(screen.getByText("AyWizz")).toBeInTheDocument();
    });
    // Brand link points at the dashboard.
    const link = screen.getByRole("link", { name: /aywizz/i });
    expect(link).toHaveAttribute("href", "/dashboard");
  });

  it("renders username + tenant + roles from JWT claims", async () => {
    seedAuthenticated({
      username: "platform-admin",
      tenant_id: "acme-prod",
      roles: ["tenant_manager", "admin"],
    });
    renderNavbar();

    await waitFor(() => {
      expect(screen.getByText("platform-admin")).toBeInTheDocument();
    });
    // Tenant + roles surface in the small subline.
    expect(screen.getByText(/acme-prod/)).toBeInTheDocument();
    expect(screen.getByText(/tenant_manager, admin/)).toBeInTheDocument();
  });

  it("falls back to sub when username is absent", async () => {
    seedAuthenticated({ username: undefined });
    renderNavbar();

    await waitFor(() => {
      expect(screen.getByText("user-alice")).toBeInTheDocument();
    });
  });

  it('shows "no roles" when the roles claim is empty', async () => {
    seedAuthenticated({ roles: [] });
    renderNavbar();

    await waitFor(() => {
      expect(screen.getByText(/no roles/)).toBeInTheDocument();
    });
  });
});

describe("Navbar logout", () => {
  it("clears localStorage AND redirects to /login on Sign out click", async () => {
    seedAuthenticated();
    renderNavbar();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /sign out/i }));

    expect(window.localStorage.getItem("aywizz.token")).toBeNull();
    expect(mockRouter.push).toHaveBeenCalledWith("/login");
  });
});
