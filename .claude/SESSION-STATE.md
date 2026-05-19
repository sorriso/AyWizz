<!-- =============================================================================
File: SESSION-STATE.md
Version: 42
Path: .claude/SESSION-STATE.md
Description: Current project state. Single source of truth for "where are we".
             Updated in place at the end of each significant session.
             Read by Claude Code at session start to restore context.

Discipline: this file SHALL NOT exceed 150 lines.
            When approaching the limit, archive the outdated portions into
            a new .claude/sessions/YYYY-MM-DD-<slug>.md entry and trim here.

Autonomous write policy: per CLAUDE.md §9.1, Claude MAY write this
            file autonomously only for trivial deltas (date bump,
            §6 archive append, cosmetic fixes). All other changes
            require explicit user validation of the diff.
============================================================================= -->

# Project State — ay_monorepo

**Last updated:** 2026-05-19 (**Phase 2.C DocGen chat-direct DONE & validated e2e : create+modify a document via chat works (Claude Haiku). Unified inline-event pipeline. Backend CI 1332 green (cov 87.95%).**).

---

## 1. Current stage

**Étape 1 — Backbone components: DONE.** (C1..C9, C12 shipped + deployable via `e2e_stack.sh dev`.)

**Étape 2a — UX chat polish: DONE.** (Full record in `sessions/2026-05-12-ux-chat-finalisation.md`.)

**Étape 2b — Project artifacts + DocGen : IN PROGRESS.** Pass 1/2.1/2.2 + Generate-E2E = DONE. **Phase 2.C DocGen chat-direct = DONE & operator-validated e2e** (C4 document CRUD + C3 tool-loop + UNIFIED inline-event pipeline + dev LLM routed to a hosted tool-calling model). Remaining: Increment 3 (tab-nav state survival) — see §5.

---

## 2. Components status

| Component | Status | Notes |
|---|---|---|
| C1 Gateway | **done** | Traefik v3, `routers.yml`. |
| C2 Auth | **done** | prefs (trigram/user_prompt/user_color) + project system_prompt. |
| C3 Conversation | **done** | RAG + chat-direct DocGen tool-loop. SSE unified `event: inline`; persisted `MessagePublic.events` audit ledger (legacy `stages` shim). |
| C4 Orchestrator | **done / artifacts in progress** | Run state machine + code plugin + document CRUD (`live-docs` run). |
| C5 Requirements | **done (v1.5)** | CRUD + tailoring + history + reindex + export. |
| C6 Validation | **done (v1.5)** | 9 MUST checks (7 real, 2 stubs). |
| C7 Memory | **done** | Federated retrieval, Ollama embedder, hybrid KG. |
| C8 LLM Gateway | **done (client side)** | `ChatMessage.content` Optional ; bounded 429 retry. LiteLLM proxy deferred. |
| C9 MCP | **done** | 8 tools. |
| C12 Workflow | **deployed** | n8n via Traefik. |
| **UX (Next.js)** | **done (chat+DocGen)** | Profiles code/docgen. Working area 3-pane + Documents tree. `<InlineLog>` unified renderer. |

---

## 3. Active decisions (beyond specs)

- **Architecture** : Python 3.13 src layout. Monorepo. B1 (single `ay-api:local` × N via `COMPONENT_MODULE`). Single Arango `platform`. LiteLLM=C8 HTTP-only (R-800-011).
- **Governance** : CLAUDE.md v20 + `.claude/settings.json`. §10 test-debug / §11 coverage / §5.7 shell / §4.6 env-tiers / §5.2 sed-ban.
- **Catalog-driven CI** : `tests/e2e/auth_matrix/_catalog.py` SOT ; coherence pins route↔catalog↔coverage.
- **UX architecture** : runtime-config 2 tiers ; `(protected)/` auth gate ; build-stamp footer ; session-revoked redirect.
- **Artifacts UX** (2026-05-12) : transparent backend (MinIO/Gitea proxied) ; profile-aware section ; MinIO `orchestrator/c4-artifacts/{tenant}/{project}/{run}/{path}`.
- **D-015 DocGen v1 = chat-direct** (2026-05-16) : `create/update/read/list/delete_document` tools mutate the artifact surface from C3 chat. v2 = synthesis-v4/OpenHands (future). ADR in `999-SYNTHESIS.md`.
- **Unified inline-event pipeline** (2026-05-19) : `StageRecord`+`ToolCallRecord` → one `InlineEvent` (discriminated `kind`) ; one persisted `MessagePublic.events` audit ledger (read-time shim projects legacy v3 `stages`, no data migration) ; one SSE channel `event: inline` ; one `<InlineLog>` formatter-registry (add a kind = add a formatter). Registered-contract change (§8.4) ; tests adapted (§10.4).
- **C8 robustness** (2026-05-19) : `ChatMessage.content` is Optional (OpenAI spec: `content:null` on a tool-call message) ; `chat_completion` retries HTTP 429 ≤3× honouring `Retry-After`/`retry_after_seconds` (cap 20 s).
- **Dev DocGen LLM = hosted tool-calling, opt-in** (2026-05-19, **semantic env change §4.6**) : 4 local Ollama models (qwen2.5:3b, qwen2.5-coder:7b, llama3.1:8b, hermes3:8b) + Gemini-free + OpenRouter-`:free` all proved unfit for reliable agentic tool-calling (modes logged in journal). Dev `C8_GATEWAY_URL` → Anthropic OpenAI-compat (`https://api.anthropic.com/v1`, `claude-haiku-4-5`). **Cost policy** : pytest e2e stays on `mock_llm` (deterministic, zero cost — unchanged) ; reverting the 2 `.env.dev` lines restores Ollama 3B for cost-free non-DocGen dev ; the hosted key is opt-in only for the DocGen tool-loop. Proper long-term fix = per-agent C8 routing (Q-100-021).
- **Tier-2 `.env.secret`** (2026-05-19) : `C3_C8_BEARER_TOKEN` (provider API key) loaded LAST in c3/c4 dev-override `env_file` with `required:false` (absent → Ollama/pytest unaffected). Git-ignored, operator-authored, never committed. Dev `ollama` resource envelope raised to 12 GB / 4 CPU (root cause of recurring `signal: killed` = the 2 GB container cap, not the Docker VM).

---

## 4. Open questions

- **600-SPEC** scaffold (code-domain quality engine).
- **LiteLLM proxy deployment** deferred.
- **C5** : import 501, ReqIF/point-in-time v2. **C7** ML adapters optional extras. **C6** stubs #3/#8 need machine-readable specs.
- **Q-100-016/017/018** : trace into K8s Jobs ; workflow-synthesis sampling/retention ; dashboard layer.
- **Q-100-019** : Turbopack incompat → `next dev --webpack`.
- **Q-100-020** : Gitea service-account credential storage → KMS/vault at prod.
- **Q-100-021 (NEW 2026-05-19)** : per-agent C8 routing so `c3-docgen` → hosted tool-calling model while everything else stays on local Ollama 3B (cost minimisation). Needs the C8 router / litellm `agent_routes` wired in dev (currently single global `C8_GATEWAY_URL`).

---

## 5. Next planned action

**Increment 3 (DEFERRED — next sizable piece)** : Tier-1 UI state persistence. A `WorkspaceProvider` mounted in `(protected)/layout.tsx` (survives route nav) holding per-project ephemeral UI state (active conversation, selected run/doc, composer draft) + `sessionStorage` hydration (survives F5) ; move the SSE send-loop into the provider so a live generation **continues across tab navigation**. NB: refresh-survival of the *audit trail* is already done (persisted `MessagePublic.events` ledger) — Increment 3 only adds live-flow + UI-state continuity.

**Then** : backlog Tranche B (project-creation UI, members, admin tenant/users, resume/retry, Monaco+diff) ; Tranche C (LiteLLM proxy+cost incl. Q-100-021 per-agent routing, K8s sub-agent dispatcher, HTTPS+K8s prod, Arango migrations, CI GH Actions) ; Tranche D polish.

**Reserve (intellectual honesty)** : the Anthropic API is **paid** — every dev DocGen turn bills tokens (Haiku keeps it cheap). `.env.secret` is git-ignored. Ollama/OpenRouter remain offline/free fallbacks (revert the two `.env.dev` lines).

---

## 6. Sessions archive

Latest entries (most recent first):
- `.claude/sessions/2026-05-19-docgen-2c-and-llm-provider-migration.md` — **Phase 2.C DocGen end-to-end + unified inline pipeline + LLM provider migration (2026-05-18→19)**. C4 document CRUD + C3 tool-loop validated (create+modify via chat, Claude Haiku). `InlineEvent`/`MessagePublic.events` unification (contract + `<InlineLog>` registry). C8 `content` Optional + 429 retry. Provider odyssey (4 local Ollama + Gemini-free + OpenRouter-`:free` → Anthropic OpenAI-compat). Tier-2 `.env.secret` mechanism + dev ollama 12 GB/4 CPU. UX (content-height panes, done-cue, Working-area fit). Backend CI 1332 green.
- `.claude/sessions/2026-05-12-ux-chat-finalisation.md` — UX chat finalisation 2026-05-09→12.
- `.claude/sessions/2026-04-29-ux-validation-and-url-preservation.md` — UX validation + URL preservation.
- `.claude/sessions/2026-04-29-ux-phase-4a-auth-shell.md` — UX Phase 4a auth shell.
- `.claude/sessions/2026-04-29-ux-bootstrap-and-frontend.md` — UX bootstrap end-to-end.
- `.claude/sessions/2026-04-29-ux-gaps-fill.md` — `/blob` download, tenant_manager bootstrap, auto KG.
- `.claude/sessions/2026-04-28-c3-remote-services-and-security-layer.md` — RemoteMemoryService + AuthGuard.
- _Earlier 2026-04-22..28_ : git log + `sessions/`. Backbone (C1..C9,C12), CI/CD, observability, auth-matrix, Plan v1 A→F.

---

## 7. Maintenance rules

- This file SHALL remain ≤ 150 lines.
- Claude SHALL propose an update at end of any session introducing a decision, completing a stage, or changing §5.
- User validates before each write (no silent edits) except trivial deltas per `CLAUDE.md` §9.1.
