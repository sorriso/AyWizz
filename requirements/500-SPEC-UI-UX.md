---
document: 500-SPEC-UI-UX
version: 2
path: requirements/500-SPEC-UI-UX.md
language: en
status: draft
derives-from: [D-008, R-100-114]
---

# UI & UX Specification

> **STATUS: v2 (2026-05-11).** Populated with the entities + decisions
> covering Phases A-F of the v1 UX implementation (`ay_platform_ui/`).
> Scaffold-only sections are explicitly marked.

---

## 1. Purpose & Scope

This document specifies the AyWizz **frontend** (Next.js 16 + React 19
+ Tailwind v4) — what it renders, how it authenticates, how it routes,
and which backend contracts (C2/C3/C5/C6/C7) it consumes.

**In scope.**
- Auth shell + login flow (consumes C2 `/auth/login`, `/ux/config`).
- Project list + per-project shell with **profile-aware** sidebar.
- Per-section UX : Overview, Sources, Conversations, Requirements,
  Validation, Settings.
- Profile registry (v1 ships `code` only ; future profiles plug in
  without shell changes).
- Demo/dev mode affordances (auto-fill login panel, demo seed).

**Out of scope.**
- Visual design system (operational ; colours / spacing live in
  Tailwind tokens, not in this spec).
- Backend internals (live in `100/300/400/700/...-SPEC-*.md`).
- Native mobile apps (web-responsive only in v1).

---

## 2. Architecture overview

### 2.1 Routing tree

```
/                                      → anonymous landing OR /projects when auth
/login                                  → C2-driven login form
/profile                                → user self view (JWT claims)
/projects                               → list of accessible projects
/projects/[pid]                         → redirect → /[default section]
/projects/[pid]/overview                → quick-link cards per section
/projects/[pid]/sources                 → C7 sources list + upload
/projects/[pid]/sources/[sid]           → source detail + download/delete
/projects/[pid]/conversations           → C3 conversations list + new
/projects/[pid]/conversations/[cid]     → chat view with SSE stream
/projects/[pid]/requirements            → C5 documents list
/projects/[pid]/requirements/[slug]     → document detail (raw Markdown)
/projects/[pid]/validation              → C6 plugins list + kick-off form
/projects/[pid]/validation/[rid]        → run detail with polled findings
/projects/[pid]/settings                → placeholder (members + metadata)
```

All authenticated routes live under the route group `app/(protected)/`
(Next App Router idiom). The group's `layout.tsx` gates on both
`AuthState === "authenticated"` AND `ConfigState === "ready"`.

### 2.2 Bootstrap chain

Two-stage runtime config (no rebuild required to change either layer):
1. `/runtime-config.json` (mounted from K8s ConfigMap) — discovers
   `apiBaseUrl`.
2. `<apiBaseUrl>/ux/config` (served by C2) — discovers brand, feature
   flags, auth mode, optional `dev_credentials`.

`<ConfigProvider>` + `<AuthProvider>` Client Components hydrate the
state ; every page consumes via `useConfigState()` / `useAuth()`.

### 2.3 Profile-aware shell

A project's `profile` field (currently `"code"`) is mapped by
`lib/profiles/registry.ts` to a `ProfileDefinition` exposing the
sidebar sections in display order. Adding a profile = one import +
one entry in the registry — the shell stays profile-agnostic.

---

## 3. Functional requirements

#### R-500-001

```yaml
id: R-500-001
version: 1
status: approved
category: functional
derives-from: [R-100-114]
```

The UX SHALL serve the landing route `/projects` after a successful
login, listing every project accessible to the caller via
`GET /api/v1/projects`. Each row SHALL render the project's `profile`
as a badge ; unknown profiles SHALL render a neutral "Unknown
(profile_id)" tag rather than crash.

#### R-500-002

```yaml
id: R-500-002
version: 1
status: approved
category: functional
```

A project shell SHALL render a left **sidebar** listing the active
profile's sections in display order. The sidebar SHALL be collapsable
with 3 responsive modes :

- `< md` (< 768 px) : hidden by default, drawer overlay on burger tap.
- `md ≤ w < lg` (768 — 1023 px) : iconified (56 px) by default,
  tooltip on hover, expand on click.
- `≥ lg` (≥ 1024 px) : expanded (240 px) by default, collapse button
  toggles iconified.

The collapsed/expanded preference SHALL persist via `localStorage`
(`aywizz.sidebar.collapsed`).

#### R-500-003

```yaml
id: R-500-003
version: 1
status: approved
category: functional
```

The **Sources** section SHALL surface:
- A drag-and-drop + file-picker upload zone that derives `source_id`
  from the filename slug and `mime_type` from the extension. The UX
  SHALL reject unsupported extensions client-side (R-400-024 MIME
  registry) before invoking `POST /api/v1/memory/projects/{pid}/sources/upload`.
- A list of sources with parse-status badges (`pending` / `parsed` /
  `indexed` / `failed`), chunk count, uploader and timestamp.
- A per-source detail view with metadata and an **auth-aware
  download** affordance (Bearer + Blob via JS, not a naked
  `<a download>` — see D-500-001).
- A per-row **Delete** action (project_owner / admin only ; server
  enforces, the UX surfaces the failure if 403).

#### R-500-004

```yaml
id: R-500-004
version: 1
status: approved
category: functional
derives-from: [R-100-074]
```

The **Conversations** section SHALL surface :
- A list of the caller's conversations scoped to the active project
  (filtered client-side from `GET /api/v1/conversations`).
- A `New conversation` inline form.
- A chat view streaming the assistant reply via Server-Sent Events
  (`POST /api/v1/conversations/{cid}/messages`). The UX SHALL :
  - Optimistically render the user message before the network round-
    trip.
  - Display a transient "live" assistant message accumulating chunks.
  - Replace the optimistic state with the persisted server view once
    the stream terminates with the `[DONE]` sentinel.
  - Allow `Ctrl/Cmd + Enter` to send.

#### R-500-005

```yaml
id: R-500-005
version: 1
status: approved
category: functional
derives-from: [R-300-040]
```

The **Requirements** section SHALL be **read-only in v1**, listing
documents (slug, version, status, language) via
`GET /api/v1/projects/{pid}/requirements/documents` and rendering a
single document's raw Markdown content in a styled `<pre>` block.
Rich Markdown-to-HTML rendering is deferred (no new dep in v1) ;
the raw spec corpus is human-readable as-is.

#### R-500-006

```yaml
id: R-500-006
version: 1
status: approved
category: functional
derives-from: [R-700-010]
```

The **Validation** section SHALL surface a kick-off form selecting
one of the installed domains (`GET /api/v1/validation/plugins`),
trigger a run via `POST /api/v1/validation/runs` and navigate to a
run-detail page that polls `GET /runs/{rid}` until the run reaches
a terminal state (`completed` / `failed`). Findings SHALL be
rendered with severity badges (`info` / `warning` / `error` /
`critical`).

#### R-500-007

```yaml
id: R-500-007
version: 1
status: approved
category: security
derives-from: [R-100-118, E-100-002]
```

The UX SHALL expose a `/profile` page surfacing the caller's JWT
claims (username, display name, sub, email, tenant, auth mode,
global roles, per-project scopes, session expiration).

Demo credentials SHALL be surfaced on the login page as an
auto-fill panel **only** when both backend flags
`C2_AUTH_MODE=local` AND `C2_UX_DEV_MODE_ENABLED=true` are
asserted (defense in depth, R-100-118 v2). Production overlays
SHALL leave the second flag False.

---

## 4. Entities

#### E-500-001

```yaml
id: E-500-001
version: 1
status: approved
category: contract
```

**Profile registry** — single source of truth mapping
`Project.profile` (string) to a `ProfileDefinition` :

```ts
interface ProfileDefinition {
  id: string;             // wire value, matches Project.profile
  label: string;          // human-readable badge text
  tagline: string;        // shown on the overview header
  accentColorHex?: string;
  sections: ProfileSection[]; // sidebar order, first = default landing
}

interface ProfileSection {
  id: string;
  label: string;
  path: string;           // appended to /projects/[pid]/
  iconName: SectionIcon;  // closed enum, see lib/profiles/types.ts
  description?: string;
}
```

v1 ships only the `code` profile. The shell SHALL render an
"Unsupported profile" placeholder when `resolveProfile()` returns
null.

#### E-500-002

```yaml
id: E-500-002
version: 1
status: approved
category: contract
```

**Demo seed envelope** — the local manual-test stack provisions a
deterministic scenario at C2 lifespan (`_ensure_demo_seed`) :
- 1 tenant (`tenant-test`).
- 4 users : `superroot` (tenant_manager super-root), `tenant-admin`
  (admin of tenant-test), `project-editor`, `project-viewer`.
- 1 project (`project-test`, profile `code`).
- 2 project grants (editor + viewer on project-test).

After the stack is up, the companion script
`seed_demo_ux.py` populates :
- 2 sources in C7 (Markdown + plain text).
- 1 empty conversation in C3.
- 1 requirements document in C5 (`900-SPEC-DEMO`).

All seeding is idempotent. Both layers SHALL be gated by
`C2_DEMO_SEED_ENABLED=true`.

---

## 5. Decisions

#### D-500-001

```yaml
id: D-500-001
version: 1
status: approved
category: implementation
derives-from: [Q-100-019]
```

**Webpack in dev, Turbopack in build.** `next dev` is pinned to
`--webpack` (package.json v6+) because Turbopack rejects the
`node_modules` symlink that the bake+symlink devcontainer pattern
relies on. The production `Dockerfile.ui` builds with the default
Next 16 toolchain (no symlink at build time, no incompatibility).
Re-evaluate when Turbopack supports external symlinks.

#### D-500-002

```yaml
id: D-500-002
version: 1
status: approved
category: ux
```

**Auth-aware downloads.** Any blob accessed via `<a href={…}
download>` would NOT carry the Bearer token (browser navigation
strips it). The UX SHALL fetch the blob with `Authorization:
Bearer …` and trigger the download via `URL.createObjectURL()` +
synthetic anchor click. Same pattern as
`apiClient.downloadSourceBlob` ; reuse for any future blob
endpoint.

#### D-500-003

```yaml
id: D-500-003
version: 1
status: approved
category: ux
```

**SSE consumption without EventSource.** The native `EventSource`
API doesn't allow custom headers (Bearer token in particular). The
UX SHALL stream SSE via `fetch` + `ReadableStream.getReader()` +
`TextDecoder`, splitting events on the `\n\n` boundary, joining
`data:` lines per event, terminating on the `[DONE]` sentinel. See
`apiClient.sendMessageStream`.

---

## 6. Tests & validation

The UX SHALL maintain :
- Unit + integration tests via Vitest with 80% line coverage gate
  (mirror backend `--cov-fail-under=80`).
- Playwright E2E suite (`tests/e2e/`) mocking the backend via
  `page.route()`.
- Playwright **system** suite (`tests/system/`) against a real
  running stack (manual-test via `e2e_stack.sh dev`).

Each new section / profile entry SHALL include at least one
integration test exercising its happy path AND its empty/error
states.

---

## 7. Open questions

- **Q-500-001** : authoring UX for requirements (Phase E currently
  read-only) — paint editor in-browser vs roundtrip via local
  filesystem ? Tied to C5's PUT-with-If-Match contract.
- **Q-500-002** : multi-file upload in Sources (today : one file at
  a time). Same endpoint or a new batch endpoint on C7 ?
- **Q-500-003** : real Markdown rendering — `marked` or a Server
  Component MDX path ? Dep + bundle-size trade-off.
- **Q-500-004** : list-runs-by-project endpoint on C6 — required to
  surface a project's run history on the Validation page.
