<!-- =============================================================================
File: SESSION-STATE.md
Version: 39
Path: .claude/SESSION-STATE.md
Description: Current project state. Single source of truth for "where are we".
             Updated in place at the end of each significant session.
             Read by Claude Code at session start to restore context.

Discipline: this file SHALL NOT exceed 150 lines.
            When approaching the limit, archive the outdated portions into
            a new .claude/sessions/YYYY-MM-DD-<slug>.md entry and trim here.

Autonomous write policy: per CLAUDE.md v15 §9.1, Claude MAY write this
            file autonomously only for trivial deltas (date bump,
            §6 archive append, cosmetic fixes). All other changes
            require explicit user validation of the diff.
============================================================================= -->

# Project State — ay_monorepo

**Last updated:** 2026-05-14 (**Tranche A done : tolerant parser + tolerant status (synonyms + assume-DONE-when-output-present) + `block_reason` surfaced in UI. 1291 backend tests green.**).

---

## 1. Current stage

**Étape 1 — Backbone components: DONE.** (C1..C9, C12 all shipped + deployable stack via `e2e_stack.sh dev` with Ollama wired.)

**Étape 2a — UX chat polish: DONE.** (Per-user prefs + per-project system prompt + SSE stage events + persisted timeline + one-click new conversation + auto-rename + user-color bubble + build-stamp footer. Full record in `sessions/2026-05-12-ux-chat-finalisation.md`.)

**Étape 2b — Project artifacts surface : IN PROGRESS.** Pass 1 = DONE (read-only MinIO surface). Pass 2.1 = DONE (Gitea bundled + per-project provisioning). Pass 2.2 = DONE (push at completion + GET /git/commits proxy). **Pass Generate-E2E = DONE backend (1268 tests green) + UI (Pipeline page wired to POST /orchestrator/runs + Gate A approval + auto-redirect to Code source) ; stack rebuild blocked on docker overlay 100% — needs host-side `docker system prune -af`.** Pass 2.3 = optional external mirror (future). Pass 3 = codegen/docgen profile split (future).

---

## 2. Components status

| Component | Status | Notes |
|---|---|---|
| C1 Gateway | **done** | Traefik v3. Hot-reload via `infra/c1_gateway/dynamic/routers.yml` v4. |
| C2 Auth Service | **done** | Tenants/projects/users + new in May 2026 : preferences (trigram, user_prompt, user_color), project system_prompt, project GET/PATCH. |
| C3 Conversation | **done** | RAG-with-Ollama wired in dev. SSE `event: stage` channel + persisted `MessagePublic.stages`. Fallback general-knowledge prompt when 0 relevant hits. |
| C4 Orchestrator | **done (state machine) / in progress (artifacts)** | Run state machine + code-domain plugin shipped. Artifacts API new pass — see §5. |
| C5 Requirements | **done (v1.5)** | CRUD + tailoring + history + reindex + reconcile + Markdown export. |
| C6 Validation | **done (v1.5)** | 9 MUST checks (7 real, 2 stubs). |
| C7 Memory | **done** | Federated retrieval, Ollama embedder, hybrid KG retrieve (Phase F.2). |
| C8 LLM Gateway | **done (client side)** | LiteLLM proxy deferred ; mock_llm or Ollama via `C8_GATEWAY_URL`. |
| C9 MCP | **done** | 8 tools (5 C5 read-only + 3 C6 read+trigger). |
| C12 Workflow Engine | **deployed** | n8n via Traefik `/uploads/*`. |
| **UX (Next.js)** | **done (chat journey)** | Login + projects list + project shell + sources / conversations / requirements / validation / preferences / project settings. Pipeline timeline chip + persisted via C3. Build-stamp footer in navbar. **Artifacts section coming.** |

---

## 3. Active decisions (beyond specs)

- **Architecture** : Python 3.13, src layout. Monorepo (`requirements/` + `ay_platform_core/` + `infra/` + `ay_platform_ui/`). B1 architecture (single `ay-api:local` image × N containers via `COMPONENT_MODULE`). Single Arango DB `platform` with per-component collections. 3 credential classes (R-100-118 v2). LiteLLM = C8 = HTTP-only (R-800-011).
- **Governance** : CLAUDE.md v20 + `.claude/settings.json` v13. Test debug §10 / coverage §11 / matcher-friendly shell §5.7 / env-file 2 tiers §4.6 / sed-ban §5.2.
- **Catalog-driven CI invariants** : `tests/e2e/auth_matrix/_catalog.py` SOT for every HTTP route × 5 dimensions. Coherence tests pin `route_catalog ↔ live FastAPI routes` and `catalog ↔ functional coverage`.
- **UX architecture** : runtime-config 2 tiers (`/runtime-config.json` static + `/ux/config` dynamic). `ConfigProvider` + `AuthProvider` Client Components. JWT decode manual base64url + skew 30s. `(protected)/` route group with auth gate. URL-preservation `?redirect=` round-trip cross-reauth with `sanitizeRedirect()`.
- **Build versioning** (2026-05-12) : both Dockerfiles bake an ISO `BUILD_VERSION` build-arg ; exposed via `/ux/config.build_version` (API) + `NEXT_PUBLIC_BUILD_VERSION` (UI). Displayed as a 2-line block in the navbar.
- **Session-revoked redirect** (2026-05-12) : module-level `setSessionRevokedHandler()` in `apiClient` ; `AuthProvider` registers a handler that flips state to `anonymous` ; protected gate redirects to `/login`. Avoids per-page raw 401 surfaces.
- **Artifacts UX decisions** (2026-05-12, **NEW**) : transparent backend (no link to MinIO / Gitea UIs — everything proxied through our endpoints). Single generic profile section `artifacts` with per-profile label (Code source for `code`/`codegen` ; Documents générés for `doc`/`docgen`). MinIO storage convention `orchestrator/c4-artifacts/{tenant_id}/{project_id}/{run_id}/{path}`. Monaco-editor for preview (lazy-loaded). Pass 1 ships read-only (UI ↔ MinIO via new C4 endpoints + seeded demo data) ; Pass 2 ships Gitea-bundled with auto per-project repo + service account + optional external-mirror remote ; Pass 3 splits the `code` profile into `codegen` / `docgen`.
- **Docker disk hygiene** (2026-05-12, **NEW**) : Docker Desktop's overlayfs fills fast under iterative `e2e_stack.sh dev` rebuilds. Documented workaround : `docker system prune -af` to free ~10 GB when overlayfs hits 100%. `docker prune` remains deny-listed in settings.json so the user runs it from the host.

---

## 4. Open questions

- **600-SPEC** still scaffold (code-domain quality engine beyond vertical coherence).
- **LiteLLM proxy deployment** (`infra/c8_gateway/k8s/` + Redis + ESO) deferred until a deployment push.
- **C5 outstanding** : import endpoint 501, ReqIF + point-in-time deferred to v2.
- **C7 ML adapters** : sentence-transformers + OpenAI embedders behind optional extras.
- **C6 stubs** #3 (interface-signature-drift) / #8 (data-model-drift) need machine-readable specs.
- **Q-100-016** : trace context propagation into K8s Jobs (C15 runtime). Open until C15.
- **Q-100-017** : workflow synthesis sampling + rétention en prod (Loki/ES).
- **Q-100-018** : dashboard layer for workflow synthesis (Grafana panels or standalone UI).
- **Q-100-019** : Turbopack incompat avec bake+symlink → `next dev --webpack` workaround.
- **Q-100-020 (NEW 2026-05-12)** : credential storage for Gitea service-accounts (Pass 2). Currently planned as plain field in `c2_project_secrets` ; needs KMS / vault when prod overlay lands. Document the threat-model assumption explicitly when Pass 2 starts.

---

## 5. Next planned action

**ACTIVE WORK : Generate-phase end-to-end + structural fixes (DONE backend ; awaiting browser retest).**

Generate-phase plumbing (R-200-150..152) :
- Spec §5.15 in 200-SPEC-PIPELINE-AGENT.md + `OrchestratorService` v2 wiring + dispatcher GENERATE prompt v2 + `main.py` v3 + UI Pipeline page + lib/types.ts v8 + apiClient v7. All landed in the earlier slice of this session.

Structural fixes added today after the 2026-05-13 browser test surfaced BLOCKED-at-brainstorm :
- **Root cause #1** : `c4` was reading only `.env.test` so its `C8_GATEWAY_URL` pointed at `mock_llm:8000` even in the dev stack. Fix : add `c4` to `docker-compose.dev.override.yml` v4 with `.env.dev` appended (routes to real Ollama).
- **Root cause #2** : qwen2.5:3b wraps its JSON in ```json fences and adds prose — the strict `json.loads(content)` in dispatcher v2 collapsed every call to BLOCKED. Fix : `in_process.py` v3 tolerant parser. Three fallback strategies (strict / markdown-fence-stripped / brace-balanced scan respecting string literals) before declaring the envelope unparseable.
- **Root cause #3** : mock_llm was implicitly part of the dev stack — masking the routing bug above. Fix : `docker-compose.yml` puts mock_llm under `profiles: [test]` ; dev stack no longer starts it ; c4's `depends_on: mock_llm` removed.
- **Structural test surface (the user's explicit ask "why no test caught this?")** :
  - `tests/unit/c4_orchestrator/test_dispatcher.py` v2 : `TestTolerantEnvelopeExtraction` (6 cases — fence with/without tag, prose around JSON, nested braces in string literals, generate-phase fenced files envelope, no-JSON-at-all still BLOCKS).
  - `tests/integration/c4_orchestrator/test_generate_materialisation.py` : new `test_pipeline_completes_with_fenced_llm_output` driving the full pipeline against a mock that emits ```json fences — would have caught the qwen2.5:3b output shape in CI.
  - `tests/coherence/test_compose_dev_profile.py` v1 (new file, 3 tests) : (a) mock_llm SHALL be in profile `test` ; (b) no service depends_on mock_llm ; (c) every C8-calling service (c2/c3/c4) has `.env.dev` in dev override. Test (c) FAILED on first run, pinning exactly the routing bug — now green.

**Backend CI : 1284 passed, 0 failure** (was 1268 + 6 ES/Loki testcontainer crashes due to disk-full ; now 16 new tests added + ES/Loki recovered).

**Tranche A complete (2026-05-14)** :
- A.1 diagnostic logging in dispatcher v3 surfaced the actual qwen2.5:3b output (envelope WITHOUT `status` key + `output` carrying malformed code string).
- A.2 `block_reason: str | None` added to `RunPublic` (models v2 + service `_public` projection + service `_run_blocked` enriched with `completion.blocker.reason`). UI lib/types v9 + Pipeline page renders the reason in a `<pre>` block instead of the misleading three-fix-rule message.
- A.3 dispatcher v4 : (i) synonyms map (`completed/success/ok/...` → DONE ; `error/failed/...` → BLOCKED) ; (ii) graceful fallback — when status unknown AND `output` non-empty, assume DONE. Strict BLOCK kept only when status unknown AND output empty/missing. 7 new unit tests (`TestTolerantStatusInference`).
- Backend CI : 1291 passed, 0 failure.

**Plan agreed with user (un par un, ordered)** :
- Tranche A : 1, 2, 3 → **DONE**.
- Tranche B : 4 (project creation UI), 5 (members), 6 (admin tenant/users), 7 (resume/retry), 8 (Monaco + diff), 9 (SSE phase events).
- Tranche C : 10 (LiteLLM proxy + cost), 11 (K8s sub-agent dispatcher), 12 (HTTPS + K8s prod manifests), 14 (Arango migrations), 16 (CI GitHub Actions).
- Tranche D : polish (empty states, skeletons, toasts, i18n, mobile).
- Skipped : ~~#13 SSO~~ (pas d'infra), ~~#15 specs~~ (à traiter avec `aywiz-architecture-synthesis-v4.md`).

**Next action** : user retests Pipeline in browser ; if it COMPLETES we move to B.4 (project creation UI).

---

## 6. Sessions archive

Latest entries (most recent first):
- `.claude/sessions/2026-05-12-ux-chat-finalisation.md` — **UX chat finalisation 2026-05-09 → 2026-05-12**. C2 prefs (trigram + user_prompt + user_color) + project system_prompt + GET/PATCH `/projects/{pid}`. C3 SSE stage events + persisted `MessagePublic.stages` + no-hits fallback prompt + auto-rename + user_prompt/project_prompt forward. UI chat journey : right-aligned user bubbles tinted by user_color, pipeline chip + collapsible panel, one-click new conversation, build-stamp footer in navbar, session-revoked auto-redirect. Backend CI 1243 verts (only the 6 pre-existing Loki/ES testcontainer errors remain). UI lint+typecheck+vitest all green.
- `.claude/sessions/2026-04-29-ux-validation-and-url-preservation.md` — UX validation pipeline + URL preservation cross-reauth.
- `.claude/sessions/2026-04-29-ux-phase-4a-auth-shell.md` — UX Phase 4a auth-aware shell.
- `.claude/sessions/2026-04-29-ux-bootstrap-and-frontend.md` — UX bootstrap end-to-end (Phases 1+2+3).
- `.claude/sessions/2026-04-29-ux-gaps-fill.md` — File download `/blob`, tenant_manager bootstrap, auto KG extraction.
- `.claude/sessions/2026-04-28-c3-remote-services-and-security-layer.md` — RemoteMemoryService + AuthGuardMiddleware defense-in-depth.
- `.claude/sessions/2026-04-28-k8s-system-tests.md` — Tier `system_k8s` pytest opt-in.
- `.claude/sessions/2026-04-28-infra-k8s-bootstrap.md` — Infra refactor OCI labels + K8s bootstrap.
- _Earlier 2026-04-22..28 entries_ : see git log + `sessions/` directory. Cover backbone components (C1..C9, C12), CI/CD, observability, auth-matrix framework, Plan v1 phases A→F.

---

## 7. Maintenance rules

- This file SHALL remain ≤ 150 lines.
- Claude SHALL propose an update at end of any session introducing a decision, completing a stage, or changing §5.
- User validates before each write (no silent edits) except for trivial deltas allowed by `CLAUDE.md` v15 §9.1.
