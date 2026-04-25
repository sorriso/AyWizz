// =============================================================================
// File: platform.ts
// Version: 1
// Path: ay_platform_ui/lib/platform.ts
// Description: Tiny shims over the platform HTTP surface. Keeps the
//              gateway base URL + fetch semantics in one place so page
//              components don't reinvent them.
// =============================================================================

export type PlatformAuthConfig = {
  mode: "none" | "local" | "sso";
  // Optional: C2 exposes additional hints we surface verbatim. Tagged as
  // unknown so the UI doesn't rely on undocumented fields.
  [key: string]: unknown;
};

/**
 * Fetches `/auth/config` from the platform gateway. Server-rendered pages
 * call this at request time; the result is NOT cached beyond the current
 * request to keep auth-mode toggles observable without a UI rebuild.
 */
export async function fetchAuthConfig(): Promise<PlatformAuthConfig | null> {
  try {
    const res = await fetch("/auth/config", { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as PlatformAuthConfig;
  } catch {
    // A dev environment without a reachable gateway should not crash the
    // page — render a degraded state instead.
    return null;
  }
}
