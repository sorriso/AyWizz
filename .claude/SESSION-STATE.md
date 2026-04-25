<!-- =============================================================================
File: SESSION-STATE.md
Version: 19
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

**Last updated:** 2026-04-24 (wrapper script path forms: CLAUDE.md v14→v15 §5.7 canonical path rule + §5.3 5-forms convention; settings v6→v7 adds 3 `./ay_platform_core/scripts/X` safety-net entries. Prior v18: env files discipline §4.6. Prior v17: Ollama default embedder, C5 import R-300-080, ay_platform_ui/ scaffold, traceability back-fill; 739 tests, coverage 90.75%, 125 distinct entity refs in src/.)

---

## 1. Current stage

**Étape 0 — Test infrastructure: DONE.**
**Étape 1 — First components: IN PROGRESS.**

- C2 Auth Service: **DONE**
- C1 Gateway: **DONE** (Traefik v3, `infra/c1_gateway/`)
- Coherence scripts: **DONE** (`scripts/checks/` × 5)
- C3 Conversation Service: **DONE**
- C5 Requirements Service: **DONE** (v1 + v1.5 upgrade: reindex, reconcile, Markdown export operational — import/ReqIF/point-in-time stubs remain).
- C8 LLM Gateway (Python-side): **DONE** — LiteLLM proxy is C8 itself; Python side = client + config schema + feature catalogs + validator + cost-tracker callback + infra shell.
- C4 Orchestrator: **DONE** — run state machine, code-domain plugin, e2e harness.
- C7 Memory Service: **DONE** — 400-SPEC v2 populated, zero-dep deterministic embedder, federated retrieval.
- C6 Validation Pipeline Registry: **DONE** — 700-SPEC v2 populated, plugin registry, code-domain plugin (9 MUST checks: 5 real + 4 stubs), ArangoDB + MinIO snapshots.
- C9 MCP Server: **DONE** — JSON-RPC 2.0 over HTTP, 8 tools (5 C5 read-only + 3 C6 read+trigger), no business logic. No dedicated spec needed (R-100-015).
- **Deployable stack**: shared Dockerfile (`infra/docker/Dockerfile.python-service`) + compose (`ay_platform_core/tests/docker-compose.yml`, 12 services including n8n/C12) + mock LLM (`_mock_llm`) + seeder (`ay_platform_core/scripts/seed_e2e.py`) + `tests/system/` tier + helper (`ay_platform_core/scripts/e2e_stack.sh`).
- C12 Workflow Engine: **DEPLOYED** — n8n 1.74 in compose, routed via Traefik `/uploads/*`, webhook endpoint prefix set to `uploads`. Workflow seeding is manual (user imports via `docker compose exec c12 n8n import:workflow`).

**Governance**: `CLAUDE.md` v15 (behaviour, conventions, permissions, spec-driven gen, session tracking, test debugging §10, matcher-friendly shell §5.7 + **canonical wrapper path forms**, `infra/` top-level §4.5, env files discipline §4.6, coverage discipline §11, `sed -i` ban §5.2, e2e test category §8.2, wrapper-script pattern §5.3 (**5-forms convention**)). `.claude/settings.json` v7 (`.env.*` deny refined; `export` allowed; 3 `./ay_platform_core/scripts/X` safety-net entries for wrappers; `sed -i` denied, `sed -n` allowed, `docker compose` denied). `ay_platform_core/pyproject.toml` v6.

---

## 2. Components status

| Component | Status | Notes |
|---|---|---|
| C1 Gateway | **done** | Traefik v3, `infra/c1_gateway/`. K8s YAML TBD. |
| C2 Auth Service | **done** | `c2_auth/`. 3 modes. `/auth/verify` emits X-User-Id/X-User-Roles/X-Platform-Auth-Mode. |
| C3 Conversation Service | **done** | `c3_conversation/`. ArangoDB, SSE, soft-delete. C4 stub. |
| C4 Orchestrator | **done** | `c4_orchestrator/`. Run state machine, code-domain plugin, e2e harness. |
| C5 Requirements Service | **done (v1.5)** | `c5_requirements/`. CRUD + tailoring + history + reindex + reconcile + Markdown export. Import + ReqIF + point-in-time still stubbed. |
| C6 Validation Pipeline | **done (v1.5)** | `c6_validation/`. 700-SPEC v3 populated. 9 MUST checks: **7 real** (added version-drift + cross-layer-coherence) + 2 stubs (#3 interface-signature-drift, #8 data-model-drift — need machine-readable E-* specs). Plugin registry, ArangoDB + MinIO snapshots. 600-SPEC still scaffold. |
| C7 Memory Service | **done** | `c7_memory/`. 400-SPEC v2 populated. Zero-dep deterministic embedder, federated retrieval, external-source ingestion. |
| C8 LLM Gateway | **done (client side)** | `c8_llm/`. Python client + config + validator + callback. LiteLLM proxy infra deferred. |
| C9 MCP Server | **done** | `c9_mcp/`. JSON-RPC 2.0 over HTTP, 8 tools backed by C5 + C6 (no business logic). Real integration tests round-trip via testcontainers. |

---

## 3. Active decisions (beyond specs)

- **Monorepo layout** — `requirements/` + `ay_platform_core/` + `infra/` + future `ay_platform_ui/` at root. `infra/` top-level per `CLAUDE.md` v14 §4.5.
- **Python 3.13**, src layout (`ay_platform_core/src/ay_platform_core/`).
- **C1 = Traefik** (Option A) — not Python. K8s manifests: raw YAML, not Helm. `/auth/*`→C2, `/api/v1/conversations/*`→C3, `/api/v1/orchestrator/*`→C4, `/api/v1/requirements/*`→C5, `/uploads/*`→C12.
- **C8 architectural policy** — LiteLLM is C8; internal components SHALL NOT import `litellm` as a library (R-800-011). Access via HTTP client only, with mandatory headers `X-Agent-Name`/`X-Session-Id`.
- **Coherence testing**: spec↔code (`@relation` markers) + code↔code (5 AST scripts in `scripts/checks/`).
- **Test debugging discipline** — `CLAUDE.md` §10 (A/B/C/D + 9 anti-patterns). **Coverage** — `CLAUDE.md` §11 (80% line blocking). **Matcher-friendly shell** — §5.7.
- **python-arango thread-safety** — the sync driver is NOT thread-safe across concurrent `asyncio.to_thread` calls. The C5 repository serialises all db access via `asyncio.Lock`; `insert(overwrite=True)` is used for upsert to avoid HTTP 412 `_rev` conflicts. Same pattern applicable to C4/C7 repositories.
- **End-to-end tests** — `CLAUDE.md` v14 §8.2 formalises `tests/e2e/`: golden-path cross-component workflows via FastAPI TestClient + testcontainers (one shared ArangoDB + one shared MinIO, mock C8 via ASGI). NOT gate-blocking. Real Traefik and K8s deployments are reserved for a future `tests/system/` tier. C4 introduces the first e2e suite (C1→C2→C3→C4→C5→C8).
- **`sed -i` banned for code edits** — `CLAUDE.md` v14 §5.2 + `.claude/settings.json` v6: `sed -i` and `sed --in-place` are denied. Any code modification SHALL go through Claude Code's native Edit / `str_replace` tool so diffs are visible in VS Code before acceptance. `sed -n` (read-only pattern extraction) remains available for diagnosis.
- **Wrapper-script pattern for destructive tooling** — `CLAUDE.md` v14 §5.3. Destructive tools (`docker compose`, `kubectl apply`, etc.) stay denied; intents that need them are encapsulated in purpose-specific shell wrappers under `ay_platform_core/scripts/` (`run_tests.sh`, `run_coherence_checks.sh`, `e2e_stack.sh`). The wrapper is the allowlisted entry point; the inner destructive call is a sub-process not matched by Claude Code. New wrappers SHALL be added to `settings.json` allow-list via the standard 4 forms (`./scripts/X`, `ay_platform_core/scripts/X`, `bash scripts/X`, `bash ay_platform_core/scripts/X`).
- **Canonical path forms for wrappers** — `CLAUDE.md` v15 §5.7 + `settings.json` v7. The VS Code matcher does not normalise leading `./`; the hybrid form `./ay_platform_core/scripts/X` fails to match the `ay_platform_core/scripts/X` pattern. Two canonical forms only: `./scripts/X` (cwd = `ay_platform_core/`) or `ay_platform_core/scripts/X` (cwd = monorepo root). Safety-net entries for the hybrid `./ay_platform_core/scripts/X` are allowlisted but Claude SHALL prefer the canonical forms. v7 updates the wrapper-pattern convention from 4 to 5 forms.
- **Environment files discipline** — `CLAUDE.md` v14 §4.6 + `.claude/settings.json` v6. Two tiers: (1) versioned non-secret (`.env.test`, `.env.dev`, `.env.development`, `.env.example`, `.env.template`) — Claude MAY read/edit via Edit tool; (2) sensitive (`.env`, `.env.local`, `.env.prod`, `.env.production`, `.env.secret`) — denied. Shell in-place writes (sed, heredoc, echo >>) remain banned per §5.2 — edits go through Edit with visible diff. **Semantic changes to Tier 1 files** (adapter switches, model IDs, feature toggles) are architectural decisions, not config tweaks; they require §3 tracing and possibly §8.1 (spec gap) — NOT silent edits.

---

## 4. Open questions

- **600-SPEC** still scaffold — code-domain quality engine (complexity, style, security scanners) beyond vertical coherence. Populate when quality push becomes a focus.
- **LiteLLM proxy deployment** — infra side (`infra/c8_gateway/k8s/`) + Redis + External Secrets Operator deferred until a deployment push.
- **C5 outstanding** — import endpoint still 501; ReqIF round-trip and point-in-time export deferred to v2.
- **C7 ML adapters** — v1 ships deterministic-hash-v1 (zero dep); sentence-transformers + OpenAI embedders behind optional extras, integration pending real rerank use case.
- **C6 stubs remaining (#3 interface-signature, #8 data-model-drift)** — both depend on machine-readable specs on `E-*` entities (not in corpus yet). #7 version-drift and #9 cross-layer-coherence closed in v1.5.

---

## 5. Next planned action

**Server side complete for v1; needs validation against real runtime.**

1. **Validate the compose stack**: `./ay_platform_core/scripts/e2e_stack.sh full` — must be run on a machine with docker. Surfaces any wiring/env-var gap not caught by unit/integration tests.
2. **When stack is green**: seed sample n8n workflow(s) for `/uploads/*` ingestion → C7, and add a system test end-to-end (file POST → C12 → C7 → retrieval).
3. **Deferred (future sessions)**: C15 sub-agent runtime (real K8s), C5 import endpoint (v2 per R-300-080), C6 stubs #3/#8 (need E-* machine-readable specs), `ay_platform_ui/` (Next.js frontend, per user directive "après server validé").

---

## 6. Sessions archive

Latest entries (most recent first):
- `.claude/sessions/2026-04-24-script-path-forms.md` — `CLAUDE.md` v15 §5.7 canonical wrapper path forms + §5.3 5-forms convention; `settings.json` v7 adds 3 `./ay_platform_core/scripts/X` safety-net entries.
- `.claude/sessions/2026-04-24-env-files-discipline.md` — `CLAUDE.md` v14 §4.6 (env files tiers & semantic-change gate) + `settings.json` v6 (`.env.*` deny affined, `export` allowed).
- `.claude/sessions/2026-04-23-e2e-stack-wrapper.md` — `CLAUDE.md` v13 §5.3 wrapper-script pattern + `settings.json` v5 allowlisting `e2e_stack.sh`.
- `.claude/sessions/2026-04-24-c12-v15-c9-realflow.md` — C12 n8n deployed, C6 #7/#9 stubs closed (real impls of version-drift + cross-layer-coherence), C9 contract + system tool-flow tests added. 620 tests, coverage 88.85%.
- `.claude/sessions/2026-04-24-e2e-stack-infra.md` — deployable docker-compose stack + app factories + mock LLM + seeder + `tests/system/` tier + helper script. All system traffic routes exclusively through Traefik (port 80).
- `.claude/sessions/2026-04-23-c9-mcp-server.md` — C9 MCP Server implementation. Stateless JSON-RPC 2.0 wrapper over C5 + C6 (8 tools). 596 tests, coverage 90.70%.
- `.claude/sessions/2026-04-23-c7-c6-validation-memory.md` — C7 Memory + C6 Validation Pipeline implementations. 400-SPEC + 700-SPEC populated. Global coverage 90.04%.
- `.claude/sessions/2026-04-23-governance-resync.md` — merge CLAUDE.md v11→v12 + settings v3→v4 into the post-C8/C5-v1.5 state produced by prior parallel Claude Code session.
- `.claude/sessions/2026-04-23-sed-ban-and-e2e-category.md` — `CLAUDE.md` v12 + `settings.json` v4. `sed -i` banned, `tests/e2e/` formalised.
- `.claude/sessions/2026-04-23-c8-c5v1.5-200spec.md` — C8 Python side + C5 v1.5 (reindex/reconcile/export) + 200-SPEC v2 populated.
- `.claude/sessions/2026-04-23-c5-requirements-service.md` — C5 full v1 implementation (CRUD + tailoring + history; reindex/import/export stubs).
- `.claude/sessions/2026-04-23-coverage-discipline.md` — `CLAUDE.md` v11 §11 + `pyproject.toml` v4 coverage gate.
- `.claude/sessions/2026-04-23-document-infra-top-level.md` — `CLAUDE.md` v10 documenting `infra/` top-level and its per-component structure.
- `.claude/sessions/2026-04-22-c3-conversation-service.md` — C3 full implementation, C4 stub, expert-mode stub.
- `.claude/sessions/2026-04-22-c1-gateway-traefik.md` — C1 Traefik v3 config, infra/c1_gateway/.
- `.claude/sessions/2026-04-22-c2-auth-service.md` — C2 full implementation.
- `.claude/sessions/2026-04-22-matcher-friendly-shell-discipline.md` — `CLAUDE.md` v8 §5.7.
- `.claude/sessions/2026-04-22-test-debugging-discipline.md` — `CLAUDE.md` v7 §10.
- `.claude/sessions/2026-04-22-setup-devcontainer-and-test-infra.md` — initial setup.

---

## 7. Maintenance rules

- This file SHALL remain ≤ 150 lines.
- Claude SHALL propose an update at end of any session introducing a decision, completing a stage, or changing §5.
- User validates before each write (no silent edits) except for trivial deltas allowed by `CLAUDE.md` v15 §9.1.
