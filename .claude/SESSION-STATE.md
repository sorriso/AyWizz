<!-- =============================================================================
File: SESSION-STATE.md
Version: 20
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

**Last updated:** 2026-04-25 (système de tests E2E débloqué — **907 tests verts** vs 693 hier soir. Switch `.env.test` AUTH_MODE=none→local + bootstrap admin alice/seed-password (`_ensure_local_admin`). Auth context propagation : ContextVars `current_user_id`/`current_user_roles`, middleware capture inbound X-User-*, `make_traced_client` injecte sur outbound — débloque MCP tool flows C9→C5/C6. C2 `/auth/verify` ajoute `X-Tenant-Id` ; Traefik authResponseHeaders étendu. `/auth/config` supporte HEAD. `admin_token` fixture session-scoped (résout 429 R-100-039). Wrapper `e2e_stack.sh seed` corrigé. Bilan : 672 unit/contract/coherence + 196 integration + 39 system + 1 xfail (n8n webhook hot-reload). Plus tôt aujourd'hui: CI/CD GitHub Actions + GHCR (D-014, R-100-123) ; R-100-122 port scheme ; `_observability` v2 ; workflow envelope synthesis (Q-100-014).

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
- **Deployable stack** — validated end-to-end 2026-04-25: ONE shared image `ay-api:local` (built from `infra/docker/Dockerfile.api`) consumed by 8 Python containers differing only by `COMPONENT_MODULE` runtime env (B1 architecture per R-100-114 v2 + R-100-117). Compose v5: `arangodb_init` + `minio_init` one-shots create the `platform` DB, the `ay_app` users with scoped permissions, and the four MinIO buckets; `c12_workflow_seed` imports n8n workflows via `--separate --input=/workflows`. Single `.env.test` v2 holds every variable exactly once (shared facts unprefixed, per-component facts `C{N}_*`). Helper `ay_platform_core/scripts/e2e_stack.sh` orchestrates up/down/seed/system. Smoke OK through Traefik (`/auth/config` 200, gated routes 401, dashboard 200).
- C12 Workflow Engine: **DEPLOYED** — n8n 1.74 in compose, routed via Traefik `/uploads/*`. Workflow seeder now automated (`--separate --input=<dir>`).

**Governance**: `CLAUDE.md` v16 (§4.5 tier-Dockerfiles formalised — `infra/docker/Dockerfile.api` for the Python tier, future `Dockerfile.ui`; complement to per-component `infra/<component>/docker/`). v15: canonical wrapper script path forms §5.7. `.claude/settings.json` v7. `ay_platform_core/pyproject.toml` v6.

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
- **B1 architecture for the Python tier** — R-100-114 v2 + R-100-117 + CLAUDE.md v16 §4.5. ONE shared image `ay-api:local` built from `infra/docker/Dockerfile.api` ; N containers consume it ; the component to start is selected at RUNTIME by env var `COMPONENT_MODULE` (no build-arg, no `--reload` baked into the image). Compose anchor `*api-service` factorises image / volumes / command / healthcheck. Production-grade `CMD` ; live-reload added by compose `command:` override only.
- **Single shared ArangoDB database** — R-100-012 v3. All components share the database `platform`. Isolation is enforced at the **collection** level (each component's collections are prefixed by its id, e.g. `c2_users`, `c4_runs`, `c7_chunks`) and at the runtime user level (R-100-118). The previous "1 DB per component" model in `.env.test` was a drift from `.env.example` and is removed.
- **Env-var single-source** — R-100-110 v2 + R-100-111 v2. Each variable appears exactly once per env file. Shared facts (`ARANGO_URL`, `ARANGO_DB`, `ARANGO_USERNAME`, `ARANGO_PASSWORD`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_SECURE`, `OLLAMA_URL`, `PLATFORM_ENVIRONMENT`) are read by every Settings class via `validation_alias`, no prefix. Per-component knobs (caps, timeouts, MinIO bucket, JWT, etc.) keep `C{N}_` prefix. Coherence test pinned at `tests/coherence/test_env_completeness.py`.
- **No root credentials at runtime** — R-100-118 v2. **Three credential classes** in the single env file: (a) backend bootstrap admin `ARANGO_ROOT_USERNAME/PASSWORD`, `MINIO_ROOT_USER/PASSWORD` (used only by Docker images at first boot + init containers; whitelisted `_INFRA_BOOTSTRAP_VARS` in coherence test); (b) app runtime `ARANGO_USERNAME=ay_app/ARANGO_PASSWORD`, `MINIO_ACCESS_KEY=ay_app/MINIO_SECRET_KEY` (read by every Settings via validation_alias); (c) app admin `C2_LOCAL_ADMIN_USERNAME/PASSWORD` (bootstrap by C2 lifespan when AUTH_MODE=local, ignored otherwise). Compose reads class (a) via `${VAR}` substitution with `--env-file` (e2e_stack.sh v3); healthcheck arangodb reads `$$ARANGO_ROOT_PASSWORD` from container env. n8n (C12) sits behind Traefik forward-auth; no inter-component creds for it.
- **Resource limits & reservations** — R-100-106 v2 (caps 4 vCPU / 8 GB internal tier + 8 vCPU / 16 GB platform-wide), R-100-119 (every long-running container declares both `limits` and `reservations`; one-shots exempt). Baseline applied in compose v6: Python services 0.4 CPU / 512 MB; arangodb 1.5 / 1.5G; ollama 2.0 / 2G; n8n 0.5 / 1G; minio 0.5 / 512M; Traefik 0.3 / 256M.
- **Test-tier observability collector** — R-100-120 (`_observability` module; ring-buffered Docker log streams; `/logs`/`/errors`/`/digest`/`/services`/`/clear` HTTP endpoints on host:8002; Python module `ay_platform_core/_observability/` riding on `ay-api:local`). R-100-121 forbids deploying any underscore-prefixed module in staging/production (mirror R-100-032). Compose service `_obs` runs as `user:root` because Docker socket mounted `:ro` — accepted as test-only; code limited to `containers.list()` + `container.logs()` (no exec/kill/run).
- **CI/CD platform** — D-014 + R-100-123. GitHub Actions sur `push main` : `ci-tests.yml` (jobs parallèles `tests` via `run_tests.sh ci` + `coherence` via `run_coherence_checks.sh`, tous deux bloquants, coverage gate `--cov-fail-under=80` via pyproject) ; `ci-build-images.yml` déclenché par `workflow_run` de ci-tests (success uniquement) → push `ghcr.io/<owner>/aywizz-api` `:latest`/`:main`/`:sha-<short>` depuis `infra/docker/Dockerfile.api` (contexte = racine monorepo per CLAUDE.md §4.5). Coverage badge optionnel via gist (`secrets.GIST_SECRET` + `vars.COVERAGE_GIST_ID`, step skippée si manquant). UI tier différé jusqu'à ce que `infra/docker/Dockerfile.ui` existe. AKS deploy out-of-scope.

---

## 4. Open questions

- **600-SPEC** still scaffold — code-domain quality engine (complexity, style, security scanners) beyond vertical coherence. Populate when quality push becomes a focus.
- **LiteLLM proxy deployment** — infra side (`infra/c8_gateway/k8s/`) + Redis + External Secrets Operator deferred until a deployment push.
- **C5 outstanding** — import endpoint still 501; ReqIF round-trip and point-in-time export deferred to v2.
- **C7 ML adapters** — v1 ships deterministic-hash-v1 (zero dep); sentence-transformers + OpenAI embedders behind optional extras, integration pending real rerank use case.
- **C6 stubs remaining (#3 interface-signature, #8 data-model-drift)** — both depend on machine-readable specs on `E-*` entities (not in corpus yet). #7 version-drift and #9 cross-layer-coherence closed in v1.5.

---

## 5. Next planned action

**Cycle observability complet livré (2026-04-25)** : phases 1 (logs JSON) + 2 (trace propagation + span_summary) + 3 (workflow envelope synthesiser, Q-100-014) + collector v2 (Docker events). Stack vert avec **16 services** capturés, `/workflows/<trace_id>` retournant l'enveloppe complète sur requête live.

**Suite proposée** :

1. **Audit spec ↔ implémentation ligne-par-ligne** — vérification systématique de chaque R-* avec annotation "implemented / partial / not-yet / divergent". `050-ARCHITECTURE-OVERVIEW.md` §9 a la vue agrégée mais ligne-par-ligne reste plus rigoureux. Session dédiée.
2. **Q-100-015 — K8s Loki/ES adapter** : porter la synthèse vers une ingestion d'un log store externe ; nécessaire avant les manifests K8s prod.
3. **Q-100-016 — trace propagation dans C15 Jobs** : à faire en même temps que C15 sub-agent runtime.
4. **Production K8s manifests** (R-100-060) : Helm/raw YAML par composant, avec `resources.limits/requests` (R-100-119), Secrets séparés admin/app (R-100-118 v2), NetworkPolicies, HPA.

**Différé long terme** : C15 sub-agent runtime (real K8s), C5 import endpoint (v2 per R-300-080), C6 stubs #3/#8 (need E-* machine-readable specs), `ay_platform_ui/` (Next.js frontend, après backend validé), production K8s manifests (R-100-060).

---

## 6. Sessions archive

Latest entries (most recent first):
- `.claude/sessions/2026-04-25-test-debt-resolution.md` — Système de tests E2E débloqué. `.env.test` AUTH_MODE=none→local + alice/seed-password bootstrap. Auth context propagation (X-User-Id/X-User-Roles/X-Tenant-Id via ContextVars + httpx hook). C2 `/auth/verify` ajoute X-Tenant-Id, Traefik authResponseHeaders étendu, HEAD support sur `/auth/config`. `admin_token` fixture session-scoped (rate-limit 429). Wrapper `e2e_stack.sh seed` corrigé. **907 tests verts** (672+196+39 +1 xfail n8n webhook hot-reload).
- `.claude/sessions/2026-04-25-ci-cd-github-actions.md` — CI/CD initial via GitHub Actions + GHCR. `.github/workflows/ci-tests.yml` (push main → run_tests.sh ci + run_coherence_checks.sh, parallèle) + `ci-build-images.yml` (workflow_run gated → push ghcr.io/<owner>/aywizz-api). 999-SYNTHESIS v4→v5 (D-014), 100-SPEC v10→v11 (R-100-123).
- `.claude/sessions/2026-04-25-port-scheme.md` — R-100-122 host-port scheme. `PORT_BASE=56000` paramétrable. Public 80→56000, dashboard 8080→56080, mock_llm 8001→59800, _obs 8002→59900. Slots déterministes Cn → BASE+n*100, test sidecars BASE+9000+. Spec 100-SPEC v9→v10. 693 verts.
- `.claude/sessions/2026-04-25-observability-collector-v2.md` — Collector v2 : Docker events subscription. `_attach_to(container)` idempotent (set+lock) ; `_watch_events()` filter daemon-side ; race init-scan-vs-events handled. Live `/services` passe de 7 à 16 (tous c2..c9 + init capturés). 9 unit tests. Total 693 verts.
- `.claude/sessions/2026-04-25-workflow-envelope-synthesis.md` — Phase 3 (Q-100-014 résolu) : `_observability/synthesis.py` (pure functions storage-agnostic) + endpoints `/workflows/<trace_id>` & `/workflows?recent=N`. K8s portability question : algorithme portable, ingestion à adapter (Q-100-015 Loki/ES, Q-100-016 trace dans C15 Jobs). 25 nouveaux tests (19 unit synthesis + 6 integration endpoint). Total 684 verts.
- `.claude/sessions/2026-04-25-structured-logging-and-trace.md` — Module `ay_platform_core/observability/` (production-tier) avec JSONFormatter + TraceContextMiddleware + make_traced_client + LoggingSettings + configure_logging. 8 composants wirés. R-100-104 v1→v2 (schéma JSON formalisé + `event=span_summary`). R-100-105 v1→v2 (W3C traceparent middleware + httpx hook). Q-100-014 ouverte (phase 3 workflow synthesiser). 644 unit/contract/coherence + 15 integration = 659 verts.
- `.claude/sessions/2026-04-25-credential-tests-and-overview.md` — 12 nouveaux tests integration : `ay_app` Arango (CRUD + isolation foreign DB + auth) + `ay_app` MinIO (object I/O + isolation foreign bucket + auth) + C2 local admin (bootstrap from env + idempotent + skip outside local + login flow). Nouveau `requirements/050-ARCHITECTURE-OVERVIEW.md` v1 (page d'archi 1-page pour démarrage rapide). CLAUDE.md v16 → v17 (§3 navigation map + §9.3 reading order pointent sur 050-).
- `.claude/sessions/2026-04-25-credentials-limits-observability.md` — Three credential classes (R-100-118 v2: bootstrap admin + app runtime + app admin) + resource limits/reservations (R-100-106 v2 + R-100-119) + test-tier observability collector `_observability` (R-100-120, R-100-121). 100-SPEC v5 → v7. 604/604 verts.
- `.claude/sessions/2026-04-25-dockerfile-api-and-env-consolidation.md` — B1 archi confirmée (1 image `ay-api:local`, N containers, `COMPONENT_MODULE` runtime). Dockerfile.api remplace Dockerfile.python-service. Env single-source (R-100-110 v2 + R-100-111 v2) ; DB Arango partagée `platform` (R-100-012 v3) ; users `ay_app` dédiés (R-100-118) via `arangodb_init` + `minio_init`. Stack compose validé end-to-end. CLAUDE.md v16. 560/560 unit+contract+coherence verts.
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
