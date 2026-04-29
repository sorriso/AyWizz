// =============================================================================
// File: navbar.tsx
// Version: 2
// Path: ay_platform_ui/components/navbar.tsx
// Description: Top header rendered on every protected page. Brand
//              (left) is read from the runtime config ; user menu
//              (right) is read from the auth provider's decoded JWT
//              claims. Logout button clears auth + redirects to login.
//
//              v2 (2026-04-29) : reads config defensively via
//              `useConfigState()` (not `useReadyConfig()`). The
//              protected layout gates on both bootstraps so this
//              component never sees an unready state in production,
//              but tests that mount the navbar directly without the
//              layout get a clean null render instead of a thrown
//              error. Hooks always run in the same order (no early
//              returns before useAuth/useRouter).
// =============================================================================

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAuth } from "@/app/auth-provider";
import { useConfigState } from "@/app/providers";

export function Navbar() {
  const router = useRouter();
  const configState = useConfigState();
  const { state, clearAuth } = useAuth();

  function handleLogout() {
    clearAuth();
    router.push("/login");
  }

  // Belt-and-braces guards : layout already gates, but rendering
  // outside the layout (e.g. in tests, or a future surface) shouldn't
  // throw.
  if (state.status !== "authenticated") return null;
  if (configState.status !== "ready") return null;

  const config = configState.config;
  const accent = config.ux.brand.accent_color_hex;
  const display = state.claims.username || state.claims.sub;
  const tenant = state.claims.tenant_id;
  const roles = state.claims.roles ?? [];

  return (
    <header
      className="border-b border-neutral-200 bg-white"
      style={{ borderTopColor: accent, borderTopWidth: 3 }}
    >
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
        <Link
          href="/dashboard"
          className="text-lg font-semibold tracking-tight"
          style={{ color: accent }}
        >
          {config.ux.brand.short_name}
        </Link>

        <div className="flex items-center gap-4 text-sm">
          <div className="text-right">
            <div className="font-medium text-neutral-900">{display}</div>
            <div className="text-xs text-neutral-500">
              {tenant ? `${tenant} · ` : ""}
              {roles.length > 0 ? roles.join(", ") : "no roles"}
            </div>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
