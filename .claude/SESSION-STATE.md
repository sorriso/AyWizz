<!-- =============================================================================
File: SESSION-STATE.md
Version: 26
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

**Last updated:** 2026-04-28 (**Phase F.2 KG hybrid retrieval** livrée. `MemoryService.retrieve` consomme désormais le graphe peuplé par F.1. Algorithme A+B combiné : (A) pool widening — les chunks de sources graph-related cut off par `scan_cap` sont fetched directement via `fetch_chunks_for_source_ids` ; (B) boost ranking — les chunks dont `source_id ∈ neighbours` voient leur score cosine multiplié par `kg_expansion_boost` (default 1.3). Toujours actif quand `kg_repo` wiré + graphe non vide ; aucun coût quand vide. 3 nouveaux Field `MemoryConfig` v3 : `kg_expansion_depth=1`, `kg_expansion_boost=1.3`, `kg_expansion_neighbour_cap=20` + 3 vars `.env.example`/`.env.test`. `retrieval_scan_cap` floor abaissé `100→2` pour tester le path proposition A en isolation. AQL traversal 1-hop ANY direction (`memory_kg_relations`) avec exclusion des seed vertices. 3 tests dirigés (vide/boost/scan_cap-bypass). CI **1159 verts**.

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
- **Production workflow synthesis service** — R-100-124 + Q-100-015 résolu (2026-04-27). 3 adapters concrets implémentent un `SpanSource` Protocol storage-agnostic : `BufferSpanSource` (test-tier, wrap LogRingBuffer), `LokiSpanSource` (LogQL pipeline `| json | event="span_summary"` — whitespace-tolerant), `ElasticsearchSpanSource` (`bool/filter` + `trace_id.keyword` term + Basic Auth optionnelle). Mountable router `make_workflow_router(source)` partagé entre `_observability` (test) et future K8s deployment (prod). Sélection via `OBS_SPAN_SOURCE` ∈ {buffer, loki, elasticsearch} ; per-backend URL/credentials/window/timeout via `OBS_*`. Test-tier `_observability/main.py` v2 délègue ses `/workflows*` au même router avec `BufferSpanSource(buffer)` — un seul code path de synthèse, trois back-ends. Sous-questions deployment (sampling/rétention, dashboard) split en Q-100-017 / Q-100-018. K8s manifests pour la prod-tier service restent dans R-100-060.
- **Auth × role × scope test matrix — Phases 1+2 livrées** — E-100-002 v2 (2026-04-27). Hiérarchie 5 rôles : `tenant_manager` super-root content-blind (tenant lifecycle ONLY), `admin` = `tenant_admin` tenant-scoped, `project_owner`/`project_editor`/`project_viewer`. Framework catalog-driven sous `ay_platform_core/tests/e2e/auth_matrix/` : `_catalog.py` (62 endpoints), `_stack.py` (7 composants 1 Arango + 1 MinIO), `_clients.py` (Bearer JWT pour C2 admin + forward-auth headers ailleurs ; `make_asgi_client` avec `raise_app_exceptions=False`), `_backend.py` (helpers Arango/MinIO). 5 fichiers de tests auto-paramétrés sur le catalog (anonymous 62 + role_matrix 63 + isolation 27 + backend_state 4 + auth_modes 5 = **161 tests dédiés**). Coherence test `tests/coherence/test_route_catalog.py` pin catalog ↔ code ; toute nouvelle route SHALL ajouter une `EndpointSpec` (CLAUDE.md §13). Doc auto-générée `requirements/065-TEST-MATRIX.md` via `scripts/checks/generate_test_matrix_doc.py`. **pytest-asyncio session fixture loop_scope** = `loop_scope="session"` obligatoire sur fixture ET sur `pytest.mark.asyncio(...)` des tests consommateurs (sinon hang silencieux après ~20 tests cumulatifs). SSO mode test reste un stub 501 jusqu'à ce que `oauth2-proxy` (variant A) soit déployé — basculera vers full-flow JWKS-mocked à ce moment.
- **Docker testcontainers cleanup** — Ryuk sidecar absent du devcontainer, donc cleanup repose uniquement sur le `with X as container:` du fixture qui ne s'exécute pas si pytest est SIGKILL. Mitigation : `ay_platform_core/scripts/docker_test_cleanup.sh` (allowlisté, settings.json v9) — pattern-match `arangodb/arangodb`, `minio/minio`, `grafana/loki`, `docker.elastic.co/elasticsearch`, `ollama/ollama`, `testcontainers/ryuk` ; modes `--dry-run` et execution. Pull de `testcontainers/ryuk` au build du devcontainer = solution durable différée.
- **C7 embedder par défaut = Ollama all-minilm** — semantic env switch (CLAUDE.md §4.6) appliqué au `.env.example` 2026-04-27 (Phase C plan v1). Production config : `C7_EMBEDDING_ADAPTER=ollama` + `C7_EMBEDDING_MODEL_ID=all-minilm` + `C7_EMBEDDING_DIMENSION=384`. Rationale : RAG production exige des vecteurs sémantiques ; `deterministic-hash` est test-only (bag-of-words, pas de retrieval sémantique). Ollama all-minilm est dans la stack compose, ~46 MB local, déterministe. Tests `test_real_embedder.py` valident top-1 sémantique sur corpus cat-vs-rocket. Hash-deterministic reste accessible via override env pour unit tests rapides.
- **F.2 hybrid retrieval algorithme A+B** — 2026-04-28. Quand `MemoryService` est instancié avec un `kg_repo` ET le graphe est non vide pour le projet, `retrieve` applique 2 effets combinés sur le scoring cosine : **(A) pool widening** — `find_neighbor_source_ids` AQL-traverse 1-hop sur `memory_kg_relations` à partir des entités mentionnant les seed source_ids ; les neighbour source_ids absents du `scored` initial (cut off par `scan_cap`) sont fetched directement via `MemoryRepository.fetch_chunks_for_source_ids` et ajoutés au pool ; **(B) boost ranking** — chaque chunk dont `source_id ∈ neighbour_source_ids` (capped à `kg_expansion_neighbour_cap`=20) voit son score cosine x `kg_expansion_boost` (default 1.3, configurable). Les seeds eux-mêmes ne sont PAS boostés (déjà au top par vector, rebooster mascarade le signal). Sans `kg_repo` wiré OU graphe vide : no-op, retrieve identique v1. Justification A+B vs A seul ou B seul : sans A, B inactif quand scan_cap mord ; sans B, A invisible en petit corpus where tout est dans le scan. AQL traversal `ANY` direction parce que la pertinence sémantique d'une relation graphe est direction-agnostic.
- **Functional coverage invariant** — gap-fill 2026-04-28. Définition opérationnelle : un endpoint du catalog `tests/e2e/auth_matrix/_catalog.py` est "functional-tested" ssi au moins UN fichier sous `tests/integration/`, `tests/e2e/` (hors `auth_matrix/`) ou `tests/system/` contient un littéral URL qui matche son path segment-par-segment (`{placeholder}` accepté de chaque côté) ET contient la méthode HTTP correspondante (`.{method}(` ou `.request(`). Audit reproductible via `scripts/checks/audit_functional_coverage.py` (`--summary-only` / `--auth-only`). Coherence test `tests/coherence/test_functional_coverage.py` fait de cette définition un invariant CI : ajouter un `EndpointSpec` sans test fonctionnel hors auth_matrix échoue le build. Mirror de `test_route_catalog` (catalog↔code) pour la dimension comportement métier.

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

---

## 5. Next planned action

**Plan v1 fonctionnel** validé (6 phases, ~8-10 sessions) : Phase A livrée (2026-04-27). Backbone tenant+project+grants opérationnel ; les phases suivantes ajoutent successivement les fonctions du journey utilisateur (upload→RAG→chat→mémoire).

**Plan v1 fonctionnel COMPLET ✅** — toutes les phases (A+B+C+D+E+F.1) livrées et testées. Le backbone est shippable côté API. **Gap-fill couverture fonctionnelle** livré (2026-04-28) : 72/72 endpoints du catalog ont au moins un test fonctionnel hors auth_matrix ; invariant pinné par coherence test.

**Suite proposée** (post-v1) :

1. **F.2 — Hybrid retrieval (v1.5)** : ✅ livrée 2026-04-28 (algo A+B, 3 tests, CI 1159).
2. **Devcontainer rebuild** pour `testcontainers/ryuk:0.5.x` — durable au leak Docker.
3. **C3 → C7/C8 wiring K8s production** : `RemoteMemoryService` / `RemoteLLMClient` httpx (pattern à la C9). Les interfaces sont déjà compatibles, juste à factoriser en module remote. **Demander spécifications K8s à l'utilisateur avant de commencer**.
4. **R-100-060 — production K8s manifests** : Helm/raw YAML par composant + Loki/Promtail (R-100-124 stack). Idem K8s : spec utilisateur requise.
5. **Q-100-016** trace propagation dans C15 Jobs (avec C15 sub-agent runtime).
6. **`ay_platform_ui/`** Next.js frontend — séparé, fait à part.

**Différé long terme** : C15 sub-agent runtime (real K8s), C5 import endpoint (R-300-080..083), C6 stubs #3/#8 (need E-* machine-readable specs), Q-100-018 (dashboard Grafana / UI dédiée), `ay_platform_ui/` (Next.js frontend, après backend validé), Q-100-016/017, mock JWKS SSO.

---

## 6. Sessions archive

Latest entries (most recent first):
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
- `.claude/sessions/2026-04-26-ci-lint-typecheck-cleanup.md` — 26 ruff + 39 mypy errors → 0/0. Erreurs non-vérifiées sans `run_tests.sh ci`.
- `.claude/sessions/2026-04-26-implementation-status-audit.md` — Script `audit_implementation_status.py` + doc `060-IMPLEMENTATION-STATUS.md` (258 R-* indexés). 0 divergent. CLAUDE.md v17→v18.
- _Earlier 2026-04-22..25 entries_ : C1 gateway Traefik, C2 auth (3 modes), C3 conversation, C5 requirements v1+v1.5, C6 validation, C7 memory, C8 LLM, C9 MCP, C12 n8n. Test debt resolution + auth context propagation (sessions 2026-04-25-test-debt-resolution + credential-tests-and-overview). CI/CD GitHub Actions + GHCR (2026-04-25-ci-cd-github-actions). R-100-122 PORT_BASE port scheme. Observability complète : structured-logging (R-100-104 v2 + traceparent R-100-105 v2), workflow synthesiser Q-100-014 + collector v2. R-100-118 v2 three credential classes + R-100-119 resource limits + R-100-120/121 test-tier `_observability`. B1 archi (Dockerfile.api + COMPONENT_MODULE) + env single-source (R-100-110 v2 / R-100-111 v2 / R-100-012 v3). Governance: matcher-friendly shell §5.7, test debug §10, coverage §11, sed ban §5.2/§4.6, e2e wrapper §5.3, env discipline §4.6, script path forms. See `sessions/2026-04-22-*.md` to `sessions/2026-04-25-*.md`.

---

## 7. Maintenance rules

- This file SHALL remain ≤ 150 lines.
- Claude SHALL propose an update at end of any session introducing a decision, completing a stage, or changing §5.
- User validates before each write (no silent edits) except for trivial deltas allowed by `CLAUDE.md` v15 §9.1.
