<!-- =============================================================================
File: SESSION-STATE.md
Version: 47
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

**Last updated:** 2026-05-21 (**DocGen versioning + UI tranche DONE : live-docs per-AI-response version `(vN)`, version-history viewer (read-at-ref), drag-and-drop tree, chain-of-thought inline detail, versioned "open in working area (vN)" links, full-width resizable persisted 3-pane working area. Backend CI 1528 green (cov 86.96%). V1 functional remainder agreed = C6 stubs #3/#8 + LiteLLM deploy/per-agent routing (Q-100-021) + prod K8s/CI/HTTPS. Next : V2 scoping (OpenHands `generate` harness / Graphiti bi-temporal memory).**).

---

## 1. Current stage

**Étape 1 — Backbone components: DONE.** (C1..C9, C12 shipped + deployable via `e2e_stack.sh dev`.)

**Étape 2a — UX chat polish: DONE.** (Full record in `sessions/2026-05-12-ux-chat-finalisation.md`.)

**Étape 2b — Project artifacts + DocGen : IN PROGRESS (near V1 close).** Pass 1/2.1/2.2 + Generate-E2E + Phase 2.C chat-direct DocGen + Increment 3 (tab-nav state) = DONE. **DocGen versioning + UI tranche = DONE** (2026-05-21) : live-docs per-AI-response version (turn-tagged Gitea commits → `vN`), version-history viewer (`?ref=<sha>` + per-file `git/commits?path`), drag-and-drop tree relocation, expandable chain-of-thought tool detail, versioned "open in working area" links below the response, full-width mouse-resizable 3-pane working area persisted in prefs. Remaining for V1 close — see §5.

---

## 2. Components status

| Component | Status | Notes |
|---|---|---|
| C1 Gateway | **done** | Traefik v3, `routers.yml`. |
| C2 Auth | **done** | prefs (trigram/user_prompt/user_color) + project system_prompt. |
| C3 Conversation | **done** | RAG + chat-direct DocGen tool-loop. SSE unified `event: inline` (now carries per-tool `arguments` + resulting `version`); per-response `X-Turn-Id` for version batching; persisted `MessagePublic.events`. |
| C4 Orchestrator | **done / artifacts in progress** | Run state machine + code plugin + document CRUD (`live-docs` run). Per-file `ArtifactNode.version` + `read_document_at_ref` + `git/commits?path` (R-200-147 history). |
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
- **Governance** : CLAUDE.md v16 + `.claude/settings.json` v14. §10 test-debug / §11 coverage / §5.7 shell / §4.6 env-tiers / §5.2 sed-ban.
- **Validation philosophy** (2026-05-19, §5.3 v16) : human-in-the-loop applies at **decision gates** (architecture, plans, todos, semantic env changes per §4.6, new specs, contract changes), NOT at **execution gates** for read-only / test / lint / build / analysis commands. The `settings.json` allow-list scope reflects this distinction and expands over time as new lecture-only / test-only commands prove safe and frequent. Composed shell (`&&`, `2>&1 | tail`, heredoc-with-write) remains §5.7-banned regardless of whether the underlying tools are allowlisted — the matcher sees the chain as one unit.
- **Catalog-driven CI** : `tests/e2e/auth_matrix/_catalog.py` SOT ; coherence pins route↔catalog↔coverage.
- **UX architecture** : runtime-config 2 tiers ; `(protected)/` auth gate ; build-stamp footer ; session-revoked redirect.
- **Artifacts UX** (2026-05-12) : transparent backend (MinIO/Gitea proxied) ; profile-aware section ; MinIO `orchestrator/c4-artifacts/{tenant}/{project}/{run}/{path}`.
- **D-015 DocGen v1 = chat-direct** (2026-05-16) : `create/update/read/list/delete_document` tools mutate the artifact surface from C3 chat. v2 = synthesis-v4/OpenHands (future). ADR in `999-SYNTHESIS.md`.
- **Live-docs versioning = batched per AI response** (2026-05-21, R-200-147) : C3 mints one `response_turn_id` per turn → forwarded as `X-Turn-Id` → C4 embeds `[turn:<id>]` in the Gitea commit message. `ArtifactNode.version` = count of DISTINCT turn ids in a file's history (N writes in one response = one bump). History viewer reads content at a SHA via Gitea `contents?ref=` (`read_document_at_ref`) ; MinIO keeps only latest. Stateless (derived from Gitea, no new store). Inline log is pure chain-of-thought ; modified-doc deep-links moved below the response with `(vN)`.
- **Unified inline-event pipeline** (2026-05-19) : `StageRecord`+`ToolCallRecord` → one `InlineEvent` (discriminated `kind`) ; one persisted `MessagePublic.events` audit ledger (read-time shim projects legacy v3 `stages`, no data migration) ; one SSE channel `event: inline` ; one `<InlineLog>` formatter-registry (add a kind = add a formatter). Registered-contract change (§8.4) ; tests adapted (§10.4).
- **C8 robustness** (2026-05-19) : `ChatMessage.content` is Optional (OpenAI spec: `content:null` on a tool-call message) ; `chat_completion` retries HTTP 429 ≤3× honouring `Retry-After`/`retry_after_seconds` (cap 20 s).
- **Dev DocGen LLM = hosted tool-calling, opt-in** (2026-05-19, **semantic env change §4.6**) : 4 local Ollama models (qwen2.5:3b, qwen2.5-coder:7b, llama3.1:8b, hermes3:8b) + Gemini-free + OpenRouter-`:free` all proved unfit for reliable agentic tool-calling (modes logged in journal). Dev `C8_GATEWAY_URL` → Anthropic OpenAI-compat (`https://api.anthropic.com/v1`, `claude-haiku-4-5`). **Cost policy** : pytest e2e stays on `mock_llm` (deterministic, zero cost — unchanged) ; reverting the 2 `.env.dev` lines restores Ollama 3B for cost-free non-DocGen dev ; the hosted key is opt-in only for the DocGen tool-loop. Proper long-term fix = per-agent C8 routing (Q-100-021).
- **Tier-2 `.env.secret`** (2026-05-19) : `C3_C8_BEARER_TOKEN` (provider API key) loaded LAST in c3/c4 dev-override `env_file` with `required:false` (absent → Ollama/pytest unaffected). Git-ignored, operator-authored, never committed. Dev `ollama` resource envelope raised to 12 GB / 4 CPU (root cause of recurring `signal: killed` = the 2 GB container cap, not the Docker VM).
- **Increment 3a — cross-nav UI store** (2026-05-19, DONE & validated) : `WorkspaceProvider` (`app/(protected)/workspace-store.tsx`) mounted above the router → per-project Tier-1 UI state (active conversation, selected run/doc, **per-conversation** composer draft) survives tab navigation + F5 (`sessionStorage`). Mirror pattern (restore-once on hydration, persist on change). Conversations tab : list page shows a USER-INITIATED "↩ Resume last conversation" link (an earlier auto-`router.replace` was a TRAP — the list became unreachable ; reverted). `composerDrafts` keyed by conversation id (a project-level single draft bled into freshly-created conversations — fixed via `setDraft(projectId, convId, text)` functional-setState action). Strict two-tier split : this store is UI-only ; the audit trail stays the server-side `events` ledger.
- **Increment 3b — provider owns the SSE loop** (2026-05-19, DONE & validated) : the SSE send-loop + per-conversation live runtime (`streaming`/`liveAssistant`/`liveEvents`/`turnSeq`) live in the provider behind `useConvRuntime` (`useSyncExternalStore` — a streamed token re-renders ONLY the active chat, not the whole protected subtree). A live generation keeps running and stays observable when the chat surface unmounts on tab nav / route change ; consumers refetch canonical rows on `turnSeq` (works after a remount too). Wired on BOTH surfaces : ChatSidebar (Working area) + Conversations `[cid]` page. Schema-migration lesson : the `sessionStorage` key is **versioned** (`aywizz.workspace.ui.v2`) and `loadAll` normalises every project slice on read — non-critical UI state must NEVER crash a page on a stale browser format.

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

**DocGen versioning + UI tranche = DONE** (2026-05-21, see §1/§3). **V1 functional remainder agreed with operator (2026-05-21)** — close these to call V1 done :
1. **C6** : 2 of 9 MUST checks still stubs (#3, #8) — need machine-readable specs.
2. **C8 / LiteLLM** : deploy the proxy + per-agent routing (Q-100-021 : `c3-docgen`→hosted tool-calling, rest→local Ollama). Closing this removes the paid-key dependency for dev DocGen.
3. **Prod** : HTTPS + K8s prod manifests, K8sDispatcher wired (vs InProcess fallback), Arango migrations, CI GitHub Actions.

Optional V1 UX backlog (non-blocking) : project-creation UI, members mgmt, admin tenant/users, run resume/retry. (Doc-version compare is now partly served by the history viewer.)

**Next focus : V2 scoping** — `references/aywiz-architecture-synthesis-v4.md` features : **OpenHands** as the `generate`-phase agentic harness (encapsulated `pipeline/generate_engine.py`, gated on POC Q13) and **Graphiti** bi-temporal memory (KG L2/L3 + iterative retrieval, D-016). Decide sequencing (OpenHands first vs Graphiti first).

**Reserve (intellectual honesty)** : the Anthropic API is **paid** — every dev DocGen turn bills tokens (Haiku keeps it cheap). `.env.secret` is git-ignored. Ollama/OpenRouter remain offline/free fallbacks (revert the two `.env.dev` lines).

---

## 6. Sessions archive

Latest entries (most recent first):
- `.claude/sessions/2026-05-21-docgen-versioning-and-ui-tranche.md` — **DocGen versioning + 6-feature UI tranche + V1/V2 boundary review**. Live-docs per-AI-response `(vN)` (turn-tagged commits, `ArtifactNode.version`), version-history viewer (`read_document_at_ref` + `git/commits?path`), drag-and-drop tree, expandable chain-of-thought tool detail (`done_event.arguments`), versioned "open in working area (vN)" links below the response (`DocumentRef.version`), full-width resizable persisted 3-pane working area. Contract additions : ArtifactNode/DocumentRef/InlineEvent. Backend CI 1528 green (86.96%). V1 functional remainder agreed (C6 stubs / LiteLLM deploy / prod) ; next = V2 scoping.
- `.claude/sessions/2026-05-19-validation-philosophy-and-npx.md` — Validation philosophy codified in §3 + CLAUDE.md v16 §5.3 (decision vs execution gates). `settings.json` v14 allowlists `npx biome check/ci/format`, `npx tsc`, `npx eslint`, `npx prettier --check`. `--write` semantics covered by wildcard, consistent with existing `npm run format` opt-in.
- `.claude/sessions/2026-05-19-increment-3-cross-nav-state-and-sse-ownership.md` — **Increment 3 (3a + 3b) DONE & validated**. `WorkspaceProvider` Tier-1 store (per-project, per-conversation drafts, sessionStorage v2 with normalisation) + provider-owned SSE loop (`useConvRuntime`/`useWorkspaceSend`, `useSyncExternalStore`) wired on Working area + Conversations `[cid]`. Operator-caught regressions in-stream : list auto-resume trap reverted to user-initiated link ; draft bleed fixed via keyed map ; sessionStorage schema-migration safety codified.
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
