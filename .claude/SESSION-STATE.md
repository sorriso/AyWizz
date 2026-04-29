<!-- =============================================================================
File: SESSION-STATE.md
Version: 34
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

**Last updated:** 2026-04-29 (**UX Phase 4a + URL preservation cross-reauth — VALIDATED end-to-end**. Pipeline UX 100% verte : `npm run lint` ✓, `typecheck` ✓, `test:coverage` 88/88 + **90.56% line coverage**, `test:e2e` 10/10 Playwright. Bug réel fixé : `<ProtectedLayout>` v3 gate aussi sur config (race auth-sync vs config-async crashait Navbar/Dashboard sur `useReadyConfig`). Feature URL-preservation : `?redirect=<path>` round-trip ProtectedLayout↔LoginPage avec `sanitizeRedirect()` anti open-redirect (8 tests). Watchdog 60s sur exp côté client. Tooling : Dockerfile v1.9.0 bake+symlink `/opt/ui-deps` Node deps + Playwright Chromium pré-baked `/opt/playwright-browsers` ; `.dockerignore` v1 ; devcontainer.json v8 (chown postCreate + symlink postStart) ; `.claude/settings.json` v13 npm scripts allowlist. Découverte Turbopack incompat symlink hors-projet → `next dev --webpack` workaround (Q-100-019). Backend non touché, CI Python **1208 verts** inchangé.

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
- **Tooling discipline** — `CLAUDE.md` §5 + `.claude/settings.json` v12. `sed -i` denied (Edit tool only, diffs visibles VS Code) ; wrapper-script pattern pour destructifs (`docker compose`, `kubectl apply` etc.) sous `ay_platform_core/scripts/` ou `infra/{scripts,k8s}/` ; canonical path forms (2 formes : `./scripts/X` ou `ay_platform_core/scripts/X`, hybrid form fragile) ; env files 2 tiers (versioned non-secret editable ; sensitive denied) — semantic changes Tier 1 = decision §3.
- **B1 archi + single Arango + env-var single-source + no root creds** — R-100-114 v2 + R-100-117 (image partagée `ay-api:local` ; N containers ; `COMPONENT_MODULE` runtime select), R-100-012 v3 (DB unique `platform`, isolation par collection), R-100-110 v2 + R-100-111 v2 (chaque var apparaît une fois ; shared facts unprefixés via validation_alias ; `C{N}_*` per-composant ; coherence `test_env_completeness`), R-100-118 v2 (3 credential classes : bootstrap admin / app runtime `ay_app` / `C2_LOCAL_ADMIN_*`). Détails dans 050-ARCHITECTURE-OVERVIEW.
- **Resource limits + test observability + CI/CD + workflow synthesis** — R-100-106 v2/R-100-119 (limits/reservations baseline compose v6) ; R-100-120/121 (`_observability` ring-buffered, underscore-prefix interdit prod) ; D-014/R-100-123 (GitHub Actions `ci-tests.yml`+`ci-build-images.yml` → GHCR) ; R-100-124+Q-100-015 (3 adapters `SpanSource` Buffer/Loki/ES via `OBS_SPAN_SOURCE`). Détails `2026-04-25-ci-cd-github-actions.md` + `2026-04-27-q-100-015-loki-es-adapters.md`.
- **Catalog-driven CI invariants (auth-matrix + functional coverage)** — `tests/e2e/auth_matrix/_catalog.py` SOT pour 73 endpoints (E-100-002 v2 + CLAUDE.md §13, 5 rôles). 3 coherence tests : `test_route_catalog` (catalog↔code), `test_functional_coverage` (catalog↔fonctionnel hors auth_matrix), 5 fichiers auto-paramétrés (anonymous/role/isolation/backend/auth_modes). Pitfall pytest-asyncio session fixture `loop_scope="session"` requis. Détails `2026-04-27-auth-matrix-{framework,phase2}.md` + `2026-04-28-gap-fill-functional-coverage.md`.
- **Docker testcontainers cleanup** — 2026-04-28 : Ryuk réactivé (`devcontainer.json` v6 retire `TESTCONTAINERS_RYUK_DISABLED`, `postCreateCommand` pré-pulle `testcontainers/ryuk:0.8.1` non-fatal). Cleanup au SIGKILL pytest désormais durable via Ryuk sidecar (heartbeat depuis Python, kill labelisé à expiration). `docker_test_cleanup.sh` (allowlisté, settings.json v9) reste comme filet belt-and-braces — pattern-match `arangodb/arangodb`, `minio/minio`, `grafana/loki`, `docker.elastic.co/elasticsearch`, `ollama/ollama`, `testcontainers/ryuk`. Fallback : si Ryuk instable en DooD, réajouter `RYUK_DISABLED=true` dans `containerEnv`.
- **C7 embedder + F.2 hybrid retrieval** — Phase C v1 (Ollama all-minilm dim 384 par défaut, deterministic-hash test-only) + F.2 algo A+B (`retrieve` quand kg_repo+graphe non vide : pool widening AQL 1-hop + boost cosine x `kg_expansion_boost`=1.3 sur chunks neighbour ; seeds non boostés ; no-op si graphe vide). Détails `2026-04-27-phase-c-ollama-embedder.md` + `2026-04-28-phase-f2-hybrid-retrieve.md`.
- **UX scaffold + auth shell (Phases 1+2+3+4a)** — 2026-04-29. (1) `GET /ux/config` sur C2 (Auth.OPEN, AuthGuard exempt, Traefik routing `/ux/*` compose+K8s) retourne brand + features + auth_mode, 7 fields env-tunables `C2_UX_*`. (2) `ay_platform_ui/` Next.js 16 + React 19 + Tailwind 4 + Biome 2 + Node 25. **Pattern runtime-config 2 niveaux** : Stage 1 `public/runtime-config.json` (K8s ConfigMap mountable, apiBaseUrl SANS rebuild) ; Stage 2 `/ux/config` (env vars SANS rebuild). `<ConfigProvider>` + `<AuthProvider>` Client Components. JWT decode manuel base64url + skew 30s, `useAuth()` hook 3 états (loading/auth/anon). Route group `app/(protected)/` gate via `useEffect` redirect. Login flow `apiClient.login` → `auth.setToken` → `/dashboard`. Navbar (brand+claims+logout) dans (protected) only. (3) `Dockerfile.ui` multi-stage Next standalone Node 25 alpine. K8s manifests `infra/k8s/base/ay_platform_ui/`. IngressRoute catch-all `/` priority 1. `ci-build-images.yml` v3 (job `build-ui` parallèle). Détails `2026-04-29-ux-bootstrap-and-frontend.md` + `2026-04-29-ux-phase-4a-auth-shell.md`.
- **Gap-fill UX (file download + tenant_manager + auto KG)** — 2026-04-29. (1) `GET /sources/{sid}/blob` stream MinIO. (2) `C2_LOCAL_TENANT_MANAGER_*` opt-in super-root content-blind. (3) `C7_AUTO_EXTRACT_KG_ON_UPLOAD=True` trigger `extract_kg` post-upload en `contextlib.suppress` (kg_repo+llm requis). 13 tests intégration. Détails `2026-04-29-ux-gaps-fill.md`.
- **C3→C7/C8 RemoteServices + AuthGuardMiddleware (defense-in-depth)** — 2026-04-28/29. (1) `c7_memory/remote.py` `RemoteMemoryService` (httpx, propage X-User-Id/Tenant/Roles) ; ConversationService Union-typed, `**_forward_auth_kwargs` ignorés in-process ; C3 main.py wire Remote+LLM si `C3_C7_BASE_URL`+`C8_GATEWAY_URL` set, sinon stub. mock_llm K8s `_mock_llm/` opt-in overlay system-test uniquement. (2) `observability/auth_guard.py` `AuthGuardMiddleware` : 401 sur paths non-exempt sans X-User-Id, defense-in-depth Layer 2 (Traefik=Layer 1) contre misconfig/bypass intra-cluster. Exempt lists per-composant. Autorisation fine reste per-composant via `_require_role()` (invariant catalog auth-matrix). Détails `2026-04-28-c3-remote-services-and-security-layer.md`.
- **K8s manifests + Kustomize overlays + run/stop wrappers + tier `system_k8s`** — 2026-04-28. `infra/k8s/base/<component>/` un fichier par object ; agrégation via `kustomization.yaml`. Image partagée `ghcr.io/sorriso/aywizz-api:latest` × 7 Deployments différenciés par `COMPONENT_MODULE` (R-100-114 v2). Namespace unique `aywizz`. Ingress = Traefik CRDs `IngressRoute` + `Middleware`. Overlays paramétrés via `.env` config + `.env.secret` credentials → Kustomize generators → `envFrom`. Wrappers `run.sh` / `stop.sh` encapsulent `kubectl apply/delete -k`. **4 niveaux de tests automatisés** : L1 offline `k8s_validate.sh` (kustomize+kubeval), L2+L3 `k8s_kind_smoke.sh` (kind+Traefik+curl), L4 `run_k8s_system_tests.sh` (kind + image build + overlay `system-test/` Ollama-excisé + pytest 4 tests `tests/system/k8s/test_basic_smoke.py` exerçant chaîne login→token→C7→C6). Workflow `ci-k8s-validate.yml` v2 (paths élargis `infra/docker/**` + `tests/system/k8s/**`). Compose + K8s cohérents mais évoluent en parallèle.
- **UX Phase 4a + URL preservation + Docker UI tooling** — 2026-04-29. (1) Feature `?redirect=<path>` round-trip : `<ProtectedLayout>` v3 capture `pathname+search`, redirect `/login?redirect=<encoded>` ; `<LoginPage>` v3 lit + `sanitizeRedirect()` (anti `//evil.com`/`http:`/`javascript:`/`/\evil`) ; watchdog 60s sur exp côté client `<AuthProvider>` v2 ; bug fix réel ProtectedLayout v3 gate aussi sur config (race auth-sync/config-async). Composants Navbar/Dashboard v2 défensifs (`useConfigState` au lieu de `useReadyConfig`). (2) Bake+symlink Docker pattern Node deps : Dockerfile v1.9.0 `COPY package*.json /opt/ui-deps/` + `npm install` (HORS bind-mount workspace) + Playwright Chromium pré-baked `/opt/playwright-browsers` (~250 MB) ; devcontainer.json v8 symlink postStartCommand (host wins si `node_modules` réel) + chown postCreateCommand après `updateRemoteUserUID`. `.dockerignore` v1 (denylist 115 lignes). (3) Pipeline UX validation 100% verte : 88 vitest + 10 playwright + 90.56% line coverage. Découverte Turbopack incompat symlink hors-projet → `next dev --webpack` (package.json v6) ; Q-100-019 ouverte. `.claude/settings.json` v13 (`npm run` allowlist). Détails `2026-04-29-ux-validation-and-url-preservation.md`.

---

## 4. Open questions

- **600-SPEC** still scaffold — code-domain quality engine (complexity, style, security scanners) beyond vertical coherence. Populate when quality push becomes a focus.
- **LiteLLM proxy deployment** — infra side (`infra/c8_gateway/k8s/`) + Redis + External Secrets Operator deferred until a deployment push.
- **C5 outstanding** — import endpoint still 501; ReqIF round-trip and point-in-time export deferred to v2.
- **C7 ML adapters** — v1 ships deterministic-hash-v1 (zero dep); sentence-transformers + OpenAI embedders behind optional extras, integration pending real rerank use case.
- **C6 stubs remaining (#3 interface-signature, #8 data-model-drift)** — both depend on machine-readable specs on `E-*` entities (not in corpus yet). #7 version-drift and #9 cross-layer-coherence closed in v1.5.
- **Q-100-016** — trace context propagation into Kubernetes Jobs (C15 sub-agent runtime). Open until C15 starts.
- **Q-100-017** — workflow synthesis sampling + rétention en prod (Loki/ES). R-100-124 ships l'adapter ; sampling rate per-environment et retention ≥ 30 j sont des décisions deployment, ouvertes jusqu'aux manifests K8s.
- **Q-100-018** — dashboard layer pour la synthèse workflow (Grafana panels via le Loki / standalone UI sous `ay_platform_ui/observability/`). Différé jusqu'à push observabilité prod.
- **Q-100-019 (NEW 2026-04-29)** — Turbopack incompat avec le bake+symlink (`Symlink ... points out of the filesystem root`). Court terme : `next dev --webpack` (fonctionnel, HMR plus lent). Long terme : 3 options à arbitrer — accepter webpack permanent, basculer vers `npm install` au `postCreateCommand` (perd le bake, regagne Turbopack), ou attendre patch Turbopack pour symlinks externes. À reconsidérer si HMR speed devient critique ou si une feature React 19 nécessite Turbopack.

---

## 5. Next planned action

**Plan v1 fonctionnel COMPLET ✅** (6 phases A+B+C+D+E+F.1 livrées, backbone shippable côté API). **Gap-fill couverture fonctionnelle** livré 2026-04-28 (72/72 endpoints du catalog ont ≥ 1 test hors auth_matrix, invariant pinné par coherence test).

**Suite proposée** (post-v1) :

1. **UX scaffold + auth shell (Phases 1-4a) + URL preservation** : ✅ livré + **validé pipeline 2026-04-29** (88 vitest + 10 playwright + coverage 90.56%). Phase 4b prête à démarrer.
2. **UX Phases 4b/c/d** : project management (~3-4h), file flows (upload/listing/download `/blob`, ~3-4h), chat with RAG SSE (NLUX ou custom, ~4-5h).
3. **Prod overlay K8s** : sha-* tag, storage class, External Secrets, HPA/NetworkPolicy. Spec cluster cible requise.
4. **Cross-tenant promotion** (gap UX #4) : feature majeure + spec amendment.
5. **File tree** (gap UX #6) ; **`ingest_conversation_turn` HTTP** (restaure Phase E K8s) ; **system_k8s test extension** (chat-with-RAG + UX bootstrap end-to-end).

**Différé long terme** : C15 sub-agent runtime (real K8s), C5 import endpoint (R-300-080..083), C6 stubs #3/#8 (need E-* machine-readable specs), Q-100-018 (dashboard Grafana / UI dédiée), `ay_platform_ui/` (Next.js frontend, après backend validé), Q-100-016/017, mock JWKS SSO.

---

## 6. Sessions archive

Latest entries (most recent first):
- `.claude/sessions/2026-04-29-ux-validation-and-url-preservation.md` — **UX validation pipeline + URL preservation cross-reauth**. Feature `?redirect=` round-trip ProtectedLayout↔LoginPage avec `sanitizeRedirect()`. Watchdog 60s sur exp client. Bug réel ProtectedLayout v3 gate config. Composants Navbar/Dashboard v2 défensifs. Tooling Docker : Dockerfile v1.9.0 bake `/opt/ui-deps` + Playwright Chromium pré-baked, `.dockerignore` v1, devcontainer.json v8 (chown+symlink), settings.json v13 (npm scripts). Pipeline UX : 88 vitest + 10 playwright + **90.56% line coverage**. Découverte Turbopack incompat symlink → webpack workaround (Q-100-019). Backend non touché.
- `.claude/sessions/2026-04-29-ux-phase-4a-auth-shell.md` — **UX Phase 4a auth-aware shell**. JWT decode client manuel + skew 30s. `<AuthProvider>` (3 états, useAuth), `app/(protected)/` route group avec auth gate, navbar avec brand+claims+logout, dashboard placeholder. Login flow `apiClient.login` → `auth.setToken` → redirect `/dashboard`. Backend pas touché ; CI Python 1208 verts inchangé.
- `.claude/sessions/2026-04-29-ux-bootstrap-and-frontend.md` — **UX bootstrap end-to-end (Phases 1+2+3)**. `GET /ux/config` sur C2 (Auth.OPEN, 7 fields `C2_UX_*`). `ay_platform_ui/` Next.js 15.1→^16 + React/TS/Tailwind/Biome/Node 25 latest. Pattern runtime-config 2 niveaux (`/runtime-config.json` static + `/ux/config` dynamic). `<ConfigProvider>` + login page. `Dockerfile.ui` + K8s manifests + IngressRoute catch-all + `ci-build-images.yml` v3 (job build-ui). CI Python **1208 verts**.
- `.claude/sessions/2026-04-29-ux-gaps-fill.md` — **Gap-fill UX**. File download `/blob` (4 tests), bootstrap tenant_manager (`_ensure_local_tenant_manager`, 6 tests), auto KG extraction on upload (`C7_AUTO_EXTRACT_KG_ON_UPLOAD` flag + suppress, 3 tests). CI 1184→**1196 verts**. 060-IMPLEMENTATION-STATUS régénéré. Server mature pour UX.
- `.claude/sessions/2026-04-28-c3-remote-services-and-security-layer.md` — **C3 RemoteServices + AuthGuardMiddleware**. Round 1 : `RemoteMemoryService` httpx (forward-auth propagation) + 11 tests. Round 2 : C3 main.py v3 wire Remote+LLM conditionally + mock_llm K8s + 3 env vars (`C3_C7_BASE_URL`, `C3_C8_BEARER_TOKEN`). Round 3 : `AuthGuardMiddleware` defense-in-depth wiré dans 7 composants + 7 tests. CI 1172→**1179 verts**. 060-IMPLEMENTATION-STATUS régénéré.
- `.claude/sessions/2026-04-28-k8s-system-tests.md` — **Tests système K8s pytest**. Tier `system_k8s` opt-in. 4 tests dans `tests/system/k8s/` exerçant chaîne login→token→C7→C6. Overlay `system-test/` (Ollama excisé). Wrapper `run_k8s_system_tests.sh`. Workflow v2 (job L4 + paths élargis). 060-IMPLEMENTATION-STATUS régénéré. Settings v12.
- `.claude/sessions/2026-04-28-infra-k8s-bootstrap.md` — **Infra refactor — OCI labels + K8s bootstrap**. `Dockerfile.api` v2 + `ci-build-images.yml` v2 (OCI labels). `infra/k8s/base/` 36 manifests + 14 kustomizations. Overlay `overlays/dev/` avec `.env` + `.env.secret`. Wrappers `run.sh`/`stop.sh`. Scripts L1/L2/L3 + workflow. Settings v11.
- `.claude/sessions/2026-04-28-devcontainer-ryuk.md` — **Devcontainer Ryuk réactivé**. `devcontainer.json` v5→v6 retire `TESTCONTAINERS_RYUK_DISABLED` et ajoute pré-pull `testcontainers/ryuk:0.8.1` non-fatal au `postCreateCommand`. Cleanup au SIGKILL pytest désormais durable. Rebuild devcontainer requis. Fallback documenté si Ryuk instable en DooD.
- `.claude/sessions/2026-04-28-phase-f2-hybrid-retrieve.md` — **Plan v1.5 Phase F.2 — KG hybrid retrieval**. Algo A+B combiné (pool widening + boost). `find_neighbor_source_ids` (AQL 1-hop ANY) + `fetch_chunks_for_source_ids` + `_apply_kg_expansion`. 3 paramètres config (depth/boost/neighbour_cap). 3 tests (graphe vide, boost surface beta, scan_cap cap force fetch). CI 1159 verts.
- `.claude/sessions/2026-04-28-gap-fill-functional-coverage.md` — **Gap-fill couverture fonctionnelle**. Audit script reproductible (`scripts/checks/audit_functional_coverage.py`). 5 gaps identifiés : DELETE project cascade + 2 health + 2 stubs 501. 5 tests ajoutés (1 e2e dans `test_tenant_project_lifecycle.py` + 4 smoke dans `tests/integration/_smoke/test_v1_contract_pin.py`). Coherence test `tests/coherence/test_functional_coverage.py` pin l'invariant. Couverture 67/72 → 72/72. CI 1153 verts.
- `.claude/sessions/2026-04-28-phase-f1-kg-extraction.md` — **Plan v1 Phase F.1 — DERNIÈRE phase**. Module `c7_memory/kg/` (extractor LLM + repository Arango vertex/edge). Endpoint `POST .../sources/{sid}/extract-kg` ; 503 si LLM non-wiré, 502 si malformé, idempotent. 5 tests dirigés + 4 auto-paramétrés. CI 1147 verts. **Plan v1 COMPLET** — toutes les 6 phases livrées (A+B+C+D+E+F.1).
- `.claude/sessions/2026-04-28-phase-e-conversation-memory-loop.md` — **Plan v1 Phase E**. Nouvel `IndexKind.CONVERSATIONS` (3e index). `MemoryService.ingest_conversation_turn` ingest paire user/assistant sous CONVERSATIONS (one row per turn, `conv:{cid}:{turn_id}`). C3 `_rag_stream` retrieve `[EXTERNAL_SOURCES, CONVERSATIONS]` + ingest turn après assistant persist (best-effort `contextlib.suppress`). +2 tests dirigés (direct AQL scan + multi-turn follow-up retrieves prior). **Journey v1 fonctionnel end-to-end** : tenant→projet→upload→chat-with-RAG→follow-up. CI 1138 verts.
- `.claude/sessions/2026-04-28-phase-d-chat-with-rag.md` — **Plan v1 Phase D**. ConversationService accepte `MemoryService` + `LLMGatewayClient` en injection optionnelle. `send_message_stream` route en RAG si (project_id + memory + llm + tenant) sinon stub. Pipeline : retrieve C7 top-K → augment prompt → C8 streaming → SSE re-émis → persist assistant. 3 tests dirigés round-trip. Auth-matrix _stack.py réorganisé. CI 1136 verts.
- `.claude/sessions/2026-04-27-phase-b-upload-parsers.md` — **Plan v1 Phase B**. Endpoint multipart `POST /api/v1/memory/projects/{p}/sources/upload`. 5 parsers actifs (txt, MD, HTML via BS4, PDF via pypdf, DOCX via python-docx). Blob MinIO `sources/{tenant}/{project}/{source_id}{.ext}`. Refactor service : `_index_parsed_source` shared entre flow JSON et flow multipart. 7 tests dirigés + auto-paramétrés sur catalog. Image MIMEs retirés (réservés v1.5+ OCR). Deps : pypdf, beautifulsoup4, python-docx. CI 1133 verts.
- `.claude/sessions/2026-04-27-phase-c-ollama-embedder.md` — **Plan v1 Phase C**. Switch `.env.example` C7_EMBEDDING_* vers `ollama`/`all-minilm`/`384` (production default). `.env.test` était déjà aligné. Tests slow `test_real_embedder.py` 3 verts (top-1 = src-cat). Décision tracée §3 (CLAUDE.md §4.6).
- `.claude/sessions/2026-04-27-phase-a-tenant-project-lifecycle.md` — **Plan v1 Phase A**. 8 nouveaux endpoints C2 (admin_router pour tenant_manager, projects_router pour admin/owner). Nouvelle collection `c2_projects`. 11 méthodes repo + 8 service + 6 tests dirigés round-trip. Catalog auth-matrix 62→70. CI 1121 verts.
- `.claude/sessions/2026-04-27-auth-matrix-phase2.md` — Phase 2 auth-matrix : 99 nouveaux tests (role_matrix 63 + isolation 27 + backend_state 4 + auth_modes 5). **Hang root cause** : pytest-asyncio session fixture sans `loop_scope="session"`. Fix appliqué. Wrapper `docker_test_cleanup.sh` allowlisté (settings.json v8→v9). CI 1084 verts.
- `.claude/sessions/2026-04-27-auth-matrix-framework.md` — Phase 1 auth-matrix. E-100-002 v1→v2 (5-rôles : `tenant_manager` super-root content-blind + `admin`/`tenant_admin` + 3 project roles). Catalog-driven framework `tests/e2e/auth_matrix/`. CLAUDE.md v19→v20 §13. 100-SPEC v12→v13.
- `.claude/sessions/2026-04-27-q-100-015-loki-es-adapters.md` — Q-100-015 résolu. R-100-124 (Production Workflow Synthesis Service) : `SpanSource` Protocol + Buffer/Loki/ES adapters + `make_workflow_router` montable. 33 unit + 6 integration tests. 100-SPEC v11→v12.
- `.claude/sessions/2026-04-27-claude-md-v19-and-test-only-cleanup.md` — CLAUDE.md v18→v19 §12 (`run_tests.sh ci` discipline). 2 markers (R-100-080/081). 8 test-only documentés comme légitimes.
- _Earlier 2026-04-26 entries_ : ci-lint-typecheck-cleanup (26 ruff + 39 mypy errors → 0/0, surfaced sans `run_tests.sh ci`), implementation-status-audit (`audit_implementation_status.py` + `060-IMPLEMENTATION-STATUS.md`, 258 R-* indexés, CLAUDE.md v17→v18).
- _Earlier 2026-04-22..25 entries_ : C1 gateway Traefik, C2 auth (3 modes), C3 conversation, C5 requirements v1+v1.5, C6 validation, C7 memory, C8 LLM, C9 MCP, C12 n8n. Test debt resolution + auth context propagation (sessions 2026-04-25-test-debt-resolution + credential-tests-and-overview). CI/CD GitHub Actions + GHCR (2026-04-25-ci-cd-github-actions). R-100-122 PORT_BASE port scheme. Observability complète : structured-logging (R-100-104 v2 + traceparent R-100-105 v2), workflow synthesiser Q-100-014 + collector v2. R-100-118 v2 three credential classes + R-100-119 resource limits + R-100-120/121 test-tier `_observability`. B1 archi (Dockerfile.api + COMPONENT_MODULE) + env single-source (R-100-110 v2 / R-100-111 v2 / R-100-012 v3). Governance: matcher-friendly shell §5.7, test debug §10, coverage §11, sed ban §5.2/§4.6, e2e wrapper §5.3, env discipline §4.6, script path forms. See `sessions/2026-04-22-*.md` to `sessions/2026-04-25-*.md`.

---

## 7. Maintenance rules

- This file SHALL remain ≤ 150 lines.
- Claude SHALL propose an update at end of any session introducing a decision, completing a stage, or changing §5.
- User validates before each write (no silent edits) except for trivial deltas allowed by `CLAUDE.md` v15 §9.1.
