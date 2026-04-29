// =============================================================================
// File: types.ts
// Version: 2
// Path: ay_platform_ui/lib/types.ts
// Description: Wire-format type definitions for the platform's public
//              bootstrap surface — `/runtime-config.json` (static, served
//              from this app's origin) and `/ux/config` (dynamic, served
//              by C2). snake_case fields match the Python wire format
//              verbatim so there's no mapping layer to keep in sync.
//
//              v2 (2026-04-29) : adds `DevCredential` + optional
//              `dev_credentials` field on `UxConfig`. Populated only
//              when C2's `C2_UX_DEV_MODE_ENABLED=true` AND
//              `C2_AUTH_MODE=local` ; null/absent in production.
// =============================================================================

/** Static deployment-time config served from the UI's `/public/` dir.
 *  Mountable as a K8s ConfigMap so the API URL can change without
 *  rebuilding the bundle. */
export interface RuntimeConfig {
  /** Base URL of the platform's public Traefik gateway. Empty = relative
   *  URLs (same-origin: Traefik in prod, Next.js dev rewrites in dev). */
  apiBaseUrl: string;
  /** Public-facing URL of the UI itself, used for OAuth redirects /
   *  webhook callbacks once those land. Optional in v1. */
  publicBaseUrl: string;
}

/** Brand identity served by C2 `/ux/config`. Skinnable per deployment
 *  via `C2_UX_BRAND_*` env vars. */
export interface BrandConfig {
  name: string;
  short_name: string;
  accent_color_hex: string;
}

/** Capability toggles served by C2 `/ux/config`. UX checks these
 *  before showing the corresponding affordances. */
export interface FeatureFlags {
  chat_enabled: boolean;
  kg_enabled: boolean;
  cross_tenant_enabled: boolean;
  file_download_enabled: boolean;
}

/** A single demo-seed credential surfaced for auto-fill on the login
 *  page. Returned by `/ux/config` only when C2's
 *  `C2_UX_DEV_MODE_ENABLED=true` AND `C2_AUTH_MODE=local` ; otherwise
 *  the parent field is null/absent. The plaintext password is
 *  intentional (well-known dev accounts) — production deployments
 *  never set the flag, so this never reaches a prod browser. */
export interface DevCredential {
  username: string;
  password: string;
  role_label: string;
  note: string | null;
}

/** Response body of `GET /ux/config`. */
export interface UxConfig {
  api_version: string;
  auth_mode: "none" | "local" | "sso";
  brand: BrandConfig;
  features: FeatureFlags;
  /** Demo credentials for auto-fill in dev mode. null/undefined in
   *  production. */
  dev_credentials?: DevCredential[] | null;
}

/** Combined config available to every Client Component via
 *  `useReadyConfig()`. */
export interface PlatformConfig {
  runtime: RuntimeConfig;
  ux: UxConfig;
}
