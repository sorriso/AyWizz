// =============================================================================
// File: types.ts
// Version: 7
// Path: ay_platform_ui/lib/types.ts
// Description: Wire-format type definitions for the platform's public
//              bootstrap surface — `/runtime-config.json` (static, served
//              from this app's origin) and `/ux/config` (dynamic, served
//              by C2). snake_case fields match the Python wire format
//              verbatim so there's no mapping layer to keep in sync.
//
//              v7 : adds `user_color` to `UserPreferences*` and
//              `StageEvent` for the C3 SSE pipeline-progress
//              channel (named `stage` events emitted by `_rag_stream`).
//
//              v6 : `Project` carries the effective per-project
//              `system_prompt` + `system_prompt_is_default` flag.
//              New `UserPreferences*` types mirror C2's
//              `/api/v1/users/me/preferences`. The UX fetches user
//              prefs at login and the active project at navigation,
//              forwards both prompts on every chat message.
//
//              v5 (2026-05-11) : adds C3 (conversations + messages),
//              C5 (requirements documents + entities), C6
//              (validation runs + findings) wire types.
//
//              v4 (2026-05-11) : adds `Source`, `SourceList`,
//              `ParseStatus`, `SUPPORTED_MIME_TYPES` (C7 sources).
//
//              v3 (2026-05-11) : adds `Project` + `ProjectList` types
//              (wire shape of C2's `GET /api/v1/projects`).
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
  /** API tier image build stamp — baked at docker build time and
   *  surfaced by C2 so the UX footer can show which image the API
   *  is running. Free-form string (ISO timestamp / git sha / semver).
   *  Optional in the type so a deployment running an older C2 that
   *  doesn't emit the field still parses without crashing. */
  build_version?: string;
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

/** A single project record served by C2's `GET /api/v1/projects` and
 *  `GET /api/v1/projects/{pid}`. `profile` selects the production-
 *  domain pipeline (currently only `code` ; resolved via
 *  lib/profiles/registry). `system_prompt` is the EFFECTIVE addendum
 *  prepended to chat messages on this project (override OR C2
 *  default) ; `system_prompt_is_default` flags whether an override
 *  has been stored — the settings page uses it to render a 'Using
 *  default' badge + 'Reset to default' button only when meaningful. */
export interface Project {
  project_id: string;
  tenant_id: string;
  name: string;
  profile: string;
  created_at: string;
  created_by: string;
  system_prompt: string;
  system_prompt_is_default: boolean;
}

/** Response body of `GET /api/v1/projects`. */
export interface ProjectList {
  items: Project[];
}

/** Body of `PATCH /api/v1/projects/{pid}`. Per-field semantics :
 *  - omitted / `undefined`     → no change.
 *  - `null`                    → equivalent to omitted (server treats
 *                                missing & null identically).
 *  - empty string `""`         → clear the override (revert to C2
 *                                default).
 *  - non-empty string          → set the override. */
export interface ProjectUpdate {
  name?: string | null;
  system_prompt?: string | null;
}

// ===========================================================================
// C2 — Self-service user preferences
// ===========================================================================

/** Response of `GET /api/v1/users/me/preferences` — effective values
 *  the chat client should forward to C3, plus the `is_default` flag
 *  the preferences page uses to render a 'Reset to default' button.
 *
 *  `trigram` / `user_color` are the user's stored overrides or null
 *  when they rely on the UI defaults. `user_prompt` is ALWAYS
 *  populated — falling back to `C2_DEFAULT_USER_PROMPT` when no
 *  override is set. */
export interface UserPreferencesResponse {
  trigram: string | null;
  user_prompt: string;
  user_prompt_is_default: boolean;
  user_color: string | null;
}

/** Body of `PUT /api/v1/users/me/preferences`. Per-field semantics
 *  mirror `ProjectUpdate` — null / undefined leaves the value
 *  untouched ; empty string clears the override ; non-empty sets it. */
export interface UserPreferencesUpdate {
  trigram?: string | null;
  user_prompt?: string | null;
  user_color?: string | null;
}

// ===========================================================================
// C3 — Chat SSE pipeline progress events
// ===========================================================================

/** One named `event: stage` payload emitted by C3's RAG stream. The
 *  UX accumulates these next to the assistant avatar as a live
 *  timeline ; once `[DONE]` arrives the timeline collapses behind a
 *  `+` toggle. `running` events arrive first ; the matching `done`
 *  event arrives with `duration_ms` (and optional `stats`).
 *
 *  Known `name` values today : `retrieve`, `generate`, `done` ;
 *  the UI treats unknown names by falling back to `label` so the
 *  protocol can grow without an UX rev. */
export interface StageEvent {
  name: string;
  status: "running" | "done";
  label: string;
  duration_ms?: number;
  stats?: Record<string, unknown>;
}

/** Parse status of a C7 source — mirrors `ParseStatus` server-side
 *  (`c7_memory.models.ParseStatus`). The UX shows a colored badge
 *  per status ; `failed` surfaces `parse_error` in a callout.
 *  Pipeline order : pending → parsed → indexed (or failed at any
 *  step). `indexed` is the terminal happy state — chunks embedded
 *  + searchable. */
export type ParseStatus = "pending" | "parsed" | "indexed" | "failed";

/** A single source record (parsed file or pasted document) served by
 *  C7's `GET /api/v1/memory/projects/{pid}/sources`. */
export interface Source {
  source_id: string;
  project_id: string;
  mime_type: string;
  size_bytes: number;
  uploaded_by: string;
  uploaded_at: string;
  parse_status: ParseStatus;
  parse_error: string | null;
  chunk_count: number;
  model_id: string | null;
}

/** Response body of `GET /api/v1/memory/projects/{pid}/sources`.
 *  Server returns `{ "sources": [...] }` (not `items`). */
export interface SourceList {
  sources: Source[];
}

// ===========================================================================
// C3 — Conversations
// ===========================================================================

export type MessageRole = "user" | "assistant";

/** A single conversation as exposed by C3 (`ConversationPublic`). */
export interface Conversation {
  id: string;
  owner_id: string;
  project_id: string | null;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationList {
  conversations: Conversation[];
}

export interface ConversationResponse {
  conversation: Conversation;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  /** Pipeline timeline persisted alongside the message (assistant
   *  messages only ; null on user messages and on legacy messages
   *  saved before the server gained this field). Same shape as the
   *  live `StageEvent` so the chat page can render them through the
   *  same components on navigation / reload. */
  stages?: StageEvent[] | null;
}

export interface MessageList {
  messages: Message[];
}

// ===========================================================================
// C5 — Requirements (documents + entities)
// ===========================================================================

/** Document slug record (e.g. "300-SPEC-REQUIREMENTS-MGMT"). The list
 *  endpoint returns metadata only ; pull individual docs by slug to get
 *  the rendered Markdown content. */
export interface RequirementDocument {
  slug: string;
  version: number;
  status: string;
  language: string;
  updated_at: string;
  size_bytes?: number;
}

export interface RequirementDocumentList {
  documents: RequirementDocument[];
}

/** Full document body with rendered Markdown content. */
export interface RequirementDocumentDetail {
  slug: string;
  version: number;
  status: string;
  content: string;
  language: string;
  updated_at: string;
}

/** A typed requirement entity (R-/E-/D-/T-/Q- prefix). */
export interface RequirementEntity {
  entity_id: string;
  type: string;
  version: number;
  status: string;
  category?: string;
  source_slug?: string;
  // Free-form payload from the YAML block — keys vary by entity type.
  payload: Record<string, unknown>;
}

export interface RequirementEntityList {
  entities: RequirementEntity[];
}

// ===========================================================================
// C6 — Validation
// ===========================================================================

export type ValidationRunStatus = "queued" | "running" | "completed" | "failed";
export type FindingSeverity = "info" | "warning" | "error" | "critical";

export interface ValidationRun {
  run_id: string;
  project_id: string;
  domain: string;
  status: ValidationRunStatus;
  started_at: string;
  completed_at: string | null;
  total_findings: number;
}

export interface Finding {
  finding_id: string;
  run_id: string;
  check_id: string;
  severity: FindingSeverity;
  title: string;
  message: string;
  location: string | null;
}

export interface FindingPage {
  findings: Finding[];
  total: number;
  limit: number;
  offset: number;
}

/** Plugin descriptor returned by `GET /api/v1/validation/plugins`. */
export interface ValidationPlugin {
  plugin_id: string;
  domain: string;
  version: string;
  description: string;
}

/** MIME types accepted by C7's upload endpoint (R-400-024). Anything
 *  else yields 415. Source : `c7_memory.ingestion.parser` registry. */
export const SUPPORTED_MIME_TYPES = {
  "text/plain": { ext: [".txt"], label: "Plain text" },
  "text/markdown": { ext: [".md", ".markdown"], label: "Markdown" },
  "text/html": { ext: [".html", ".htm"], label: "HTML" },
  "application/pdf": { ext: [".pdf"], label: "PDF" },
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
    ext: [".docx"],
    label: "Word (DOCX)",
  },
} as const;

export type SupportedMimeType = keyof typeof SUPPORTED_MIME_TYPES;

/** Map a filename to its expected MIME type via extension. Returns
 *  null for unsupported extensions — caller surfaces a UX error
 *  instead of trying to upload. */
export function mimeTypeFromFilename(filename: string): SupportedMimeType | null {
  const lower = filename.toLowerCase();
  for (const [mime, info] of Object.entries(SUPPORTED_MIME_TYPES)) {
    if (info.ext.some((ext) => lower.endsWith(ext))) {
      return mime as SupportedMimeType;
    }
  }
  return null;
}
