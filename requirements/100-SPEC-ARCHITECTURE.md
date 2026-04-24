---
document: 100-SPEC-ARCHITECTURE
version: 3
path: requirements/100-SPEC-ARCHITECTURE.md
language: en
status: draft
derives-from: [D-002, D-003, D-007, D-008, D-010, D-011, D-012, D-013]
---

# Architecture Specification — Platform Components & Contracts

> **Purpose of this document.** Define the macro-level component decomposition of the platform, where each type of requirement lives, the contracts between components, the scaling model, and the deployment targets. This spec defines the **what** and the **why** of each component — concrete technology choices and implementation details belong to component-specific engineering work.

> **Version 3 changes.** New §10 *Configuration & Deployment* codifying the configuration architecture that emerged during the v1 implementation of C1–C9: a single `.env`-style file as source of truth for every runtime-overridable parameter, per-component `env_prefix` convention, a platform-wide `PLATFORM_ENVIRONMENT` variable, a completeness coherence test pinning the env-file shape to the Pydantic Settings fields, and the deployable local-stack topology (shared `Dockerfile.python-service`, compose with `env_file:`, Traefik as the ONLY public port, mock LLM for CI). Adds `R-100-110..R-100-116`. No existing requirement is modified.

> **Version 2 changes.** Alignment with `D-012` (production domain extensibility) and `D-013` (external source ingestion). Component C6 is renamed from "Analysis Engine" to "Validation Pipeline Registry" to reflect its domain-pluggable nature. Hard gates referenced here (via derives-from D-007) are now formulated in domain-agnostic terms. New requirements R-100-080 to R-100-088 cover the external source ingestion capability through C12 + C7 collaboration. Existing auth, scaling, deployment, and failure-domain requirements are unchanged.

---

## 1. Purpose & Scope

This document specifies the platform's component-level architecture at a deliberately macro granularity. It establishes:

- The set of components that compose the platform and their single responsibility.
- Where platform-managed requirements (as data, as rules, as conversation constraints) are hosted.
- Where external sources ingested by users are hosted and processed.
- The contracts between components and the communication styles.
- The scaling model (horizontal/vertical, automatic, per-component).
- The deployment targets (Docker Desktop local, AKS production).
- Failure domains and graceful degradation principles.

**Out of scope.** Language choice per component (Python/Rust split — tracked as Q-100-001), exact library selections, API schemas beyond contract-critical entities, runtime configuration details, tenant isolation beyond namespace strategy, detailed ingestion parsing specifics (deferred to `400-SPEC-MEMORY-RAG.md` pending simplechat/AyExtractor alignment).

---

## 2. Relationship to Synthesis Decisions

| Decision | How this document operationalises it |
|---|---|
| D-002 (stack reuse) | MinIO, ArangoDB, n8n are declared as components C10, C11, C12. Kubernetes is the runtime platform. |
| D-003 (core library + 3 surfaces) | MCP Server is a first-class component (C9); CLI is not a deployed component but a distribution artifact. |
| D-007 (staff-engineer pattern) | The Orchestrator (C4) implements the 5-phase pipeline; sub-agents are ephemeral pods dispatched by C4. Hard gates are domain-agnostic (artifact / validation artifact vocabulary). |
| D-008 (hybrid agent exposure) | The Event Bus (NATS) carries pipeline events consumed by the Conversation Service (C3) for expert mode. |
| D-010 (graph-backed embeddings) | ArangoDB (C11) hosts both the graph and the vector collections; the Memory Service (C7) performs reads. Both the requirements corpus and external sources are embedded. |
| D-011 (LiteLLM abstraction) | The LLM Gateway (C8) is a dedicated component wrapping LiteLLM. No other component calls LLM providers directly. |
| D-012 (domain extensibility) | C6 is a registry of validation plugins. No backbone component hard-codes domain-specific vocabulary in public contracts. |
| D-013 (external source ingestion) | C12 (n8n) handles upload reception, parsing, and ingestion job orchestration. C7 handles embedding computation and indexing. No new component is introduced. Federated retrieval across separated indexes. |

---

## 3. Glossary

| Term | Definition |
|---|---|
| **Component** | A deployable unit with a single responsibility, a stable contract, and independent scaling characteristics. |
| **Contract** | The interface a component exposes (REST endpoints, event topics, RPC methods) with its schema. |
| **Ephemeral pod** | A short-lived Kubernetes pod created per sub-agent task, destroyed on completion. |
| **Failure domain** | The blast radius of a component's failure — what else becomes unavailable. |
| **Identity propagation** | Passing the authenticated user's identity downstream via a signed JWT, so no component re-authenticates. |
| **JWT** | JSON Web Token signed by the Auth Service; uniform across the three auth modes (`none`, `local`, `sso`). |
| **PDP (coarse)** | Policy Decision Point at the Gateway level, enforcing route-level and tenant-level authorization. |
| **PDP (fine)** | Per-component authorization logic for resource-specific actions. |
| **Production domain** | A registered class of artifact (`code`, `documentation`, `presentation`, ...) with its own generation and validation pipelines. |
| **External source** | A user-uploaded document (PDF, text, image, etc.) ingested for RAG. Distinct from produced artifacts. |
| **Federated retrieval** | RAG query mechanism that queries multiple separated indexes (requirements, external sources) with explicit scoping. |

---

## 4. Functional Requirements

### 4.1 Architectural Principles

#### R-100-001

```yaml
id: R-100-001
version: 1
status: draft
category: architecture
```

The platform SHALL decompose its functionality into components such that each component has exactly one responsibility. Overlap of responsibilities between components is a defect.

**Rationale.** Single Responsibility at the component level enables independent evolution, independent scaling, and clear ownership. Overlap creates synchronisation debt.

#### R-100-002

```yaml
id: R-100-002
version: 1
status: draft
category: architecture
```

The platform SHALL be deployable on a minimum footprint suitable for a single-machine local development environment (Docker Desktop + Kubernetes, ≤ 16 GB RAM, ≤ 8 vCPU allocated to the cluster).

**Rationale.** Small-start is a principle of the synthesis (Principle 6). Local parity with production is mandatory for developer productivity and for reproducibility of support cases.

#### R-100-003

```yaml
id: R-100-003
version: 1
status: draft
category: architecture
```

Every functional component of the platform SHALL be stateless. All state SHALL be externalised to declared storage components (C11 ArangoDB, C10 MinIO, or the NATS stream for in-flight events).

**Rationale.** Statelessness is a prerequisite for automatic horizontal scaling, for pod disposability, and for graceful failure recovery. The exceptions (C10, C11) are explicit and contained.

#### R-100-004

```yaml
id: R-100-004
version: 1
status: draft
category: architecture
```

Every functional component SHALL expose Kubernetes liveness and readiness probes. The readiness probe SHALL correctly reflect the component's ability to serve traffic (e.g. downstream dependency connectivity), not merely its process liveness.

**Rationale.** Kubernetes orchestration, auto-scaling, and rolling updates depend on accurate probe semantics. A readiness probe that returns OK while a dependency is unreachable causes cascading failures.

#### R-100-005

```yaml
id: R-100-005
version: 1
status: draft
category: architecture
```

Every functional component SHALL handle SIGTERM gracefully: stop accepting new requests, drain in-flight work within the configured grace period (default 30 s), and exit cleanly. A Kubernetes `preStop` hook SHALL be configured to coordinate graceful shutdown with traffic draining.

**Rationale.** Scaling down and rolling updates must not interrupt in-flight user work. Pods that exit abruptly leak sub-agent jobs and orphan events on the bus.

#### R-100-006

```yaml
id: R-100-006
version: 1
status: draft
category: architecture
```

The platform SHALL NOT rely on session affinity (sticky sessions) at any layer. Any request from an authenticated user SHALL be servable by any replica of the target component.

**Rationale.** Session affinity defeats horizontal scaling, complicates rolling updates, and creates hot replicas. State that would otherwise require affinity lives in C11 (ArangoDB) or NATS.

#### R-100-007

```yaml
id: R-100-007
version: 1
status: draft
category: architecture
```

Every outbound call to an external dependency (LLM providers, external IdPs, user git remotes, user upload sources) SHALL be wrapped by a circuit breaker with fail-fast behaviour. Default thresholds: open after 5 consecutive failures within 30 s, half-open probe after 60 s.

**Rationale.** External dependencies are the primary cause of cascading latency in the platform. Fail-fast preserves user experience and prevents resource exhaustion.

#### R-100-008

```yaml
id: R-100-008
version: 2
status: draft
category: architecture
```

Backbone components (C1 Gateway, C2 Auth, C3 Conversation, C4 Orchestrator, C5 Requirements, C7 Memory, C8 LLM Gateway, C9 MCP Server) SHALL NOT hard-code vocabulary specific to a single production domain (e.g. "code", "test", "function") in their public contracts. Internal domain-specific modules are permitted but SHALL be encapsulated behind domain-agnostic interfaces.

**Rationale.** Per D-012, the backbone is domain-pluggable. Contract-level leakage of domain vocabulary would create breaking-change dependencies when new domains are added.

---

### 4.2 Component Decomposition

The platform v1 comprises **10 internal components** (C1–C9, C15) and **3 external/dependency components** (C10–C12). External IdPs and LLM providers are out-of-cluster dependencies, not components.

#### Component inventory

| ID | Name | Type | Responsibility (one sentence) |
|---|---|---|---|
| C1 | Gateway & Identity | internal | Single entry point: TLS termination, routing, rate limiting, coarse authorization, identity propagation via JWT. |
| C2 | Auth Service | internal | Issue JWTs under one of three pluggable modes (`none`, `local`, `sso`). |
| C3 | Conversation Service | internal | Manage user-facing conversation sessions and the UI-facing event stream (including expert mode). |
| C4 | Orchestrator | internal | Drive the five-phase pipeline, dispatch and supervise sub-agent ephemeral pods, enforce hard gates. |
| C5 | Requirements Service | internal | CRUD and versioning of the StrictDoc corpus; owns the requirements data model. |
| C6 | Validation Pipeline Registry | internal | Host domain-specific validation plugins; run vertical coherence and artifact quality checks. |
| C7 | Memory Service | internal | Embeddings computation, retrieval (federated across indexes), graph traversals over ArangoDB, external source indexing. |
| C8 | LLM Gateway | internal | Single egress to LLM providers via LiteLLM; routing, budgets, per-feature compatibility. |
| C9 | MCP Server | internal | Expose Validation Pipeline Registry and Requirements Service capabilities as MCP tools to external LLM agents. |
| C15 | Sub-agent Runner | internal | Ephemeral pod template dispatched by C4, not a persistent deployment. |
| C10 | Artifact Store | dependency | Object storage for requirements files, generated artifacts, ingested external sources, reports (MinIO). |
| C11 | Graph Store | dependency | Unified vector + graph store for requirements, embeddings, sessions, RBAC, external source metadata (ArangoDB). |
| C12 | Workflow Engine | dependency | External ingestion, post-release sync, automation (n8n). |

The Event Bus (NATS) is infrastructure, not a component. It is addressed in §6.

#### R-100-010

```yaml
id: R-100-010
version: 1
status: draft
category: architecture
```

The platform SHALL implement the component inventory defined above in v1. Introducing a new component SHALL require an amendment to this document and approval per the methodology's review process.

#### R-100-011

```yaml
id: R-100-011
version: 1
status: draft
category: architecture
```

No component SHALL call an LLM provider directly. All LLM calls SHALL route through C8 (LLM Gateway). This rule is enforced by network policies in production.

**Rationale.** D-011 demands a single egress for observability, cost tracking, and provider-swap without code changes.

#### R-100-012

```yaml
id: R-100-012
version: 2
status: draft
category: architecture
```

No component SHALL access ArangoDB (C11) directly for operations that fall within another component's responsibility. Specifically: Requirements Service (C5) owns the requirements collections; Memory Service (C7) owns the embeddings, graph traversal logic, and external source indexing collections; Auth Service (C2) owns the identity and RBAC collections.

**Rationale.** Shared database access across multiple owners creates implicit coupling and schema drift. This rule enforces component ownership of data.

#### R-100-013

```yaml
id: R-100-013
version: 2
status: draft
category: architecture
```

C4 (Orchestrator) SHALL NOT perform validation or static analysis itself. These operations SHALL be delegated to C6 (Validation Pipeline Registry) via its defined contract.

**Rationale.** Keeps orchestration logic separate from validation logic; allows independent scaling; respects the domain-plug-in boundary per D-012.

#### R-100-014

```yaml
id: R-100-014
version: 1
status: draft
category: architecture
```

C15 (Sub-agent Runner) SHALL NOT be a persistent deployment. Each instance is a Kubernetes Job created on-demand by C4, running a bounded task, and terminating on completion or timeout (default 10 minutes).

**Rationale.** Ephemeral execution aligns with the staff-engineer pattern (D-007): fresh context per sub-agent, no cross-task contamination, natural resource reclamation.

#### R-100-015

```yaml
id: R-100-015
version: 2
status: draft
category: architecture
```

C9 (MCP Server) SHALL be a thin wrapper over C5 and C6 APIs. It SHALL NOT implement business logic of its own. Disabling or removing C9 SHALL NOT affect the functionality of any other component.

**Rationale.** D-003 places the core logic in C5/C6; C9 exists only to expose an MCP-compatible surface for external LLM tooling.

#### R-100-016

```yaml
id: R-100-016
version: 1
status: draft
category: architecture
```

C6 (Validation Pipeline Registry) SHALL accept domain validation plugins at build time (v1) and at runtime (v2+). Each plugin declares: the production domain it targets, the list of checks it implements, the artifact formats it parses, and its dependencies on other components.

**Rationale.** Per D-012, the architecture supports progressive addition of domains. v1 ships the `code` plugin; v2 adds `documentation`; v3 adds `presentation`. The plugin contract itself is specified in `700-SPEC-VERTICAL-COHERENCE.md`.

---

### 4.3 Requirements Placement

Platform-managed requirements (user project requirements, platform's own requirements, and decisions) are hosted across three planes:

#### Plane 1 — Requirements as data

Source of truth, physical storage, versioned history.

| Artifact | Component | Storage detail |
|---|---|---|
| `.sdoc` / `.md` files (text source of truth) | C10 Artifact Store | MinIO bucket per project, S3 versioning enabled |
| Parsed entity metadata (id, version, status, category, relations) | C11 Graph Store | ArangoDB document collections |
| Entity-to-entity relations (derives-from, impacts, tailoring-of, supersedes) | C11 Graph Store | ArangoDB edge collections |
| Embeddings | C11 Graph Store | ArangoDB vector collection (index `requirements`) |
| Git history (if project opts into Git sync) | C12 Workflow Engine → user's remote | n8n workflows |

#### Plane 2 — Requirements as rules applied to produced artifacts

| Operation | Component |
|---|---|
| Load requirement corpus for validation | C5 → C11 (read) |
| Parse produced artifacts for `@relation` markers (see methodology §8) | C6 via domain-specific parser |
| Execute MUST/SHOULD/COULD coherence checks | C6 (per active domain plugin) |
| Produce coherence reports (blocking + advisory findings) | C6 → C10 (report artifact) |

#### Plane 3 — Requirements as constraints on conversation

| Operation | Component |
|---|---|
| Load contextual requirements for a pipeline phase | C4 → C5 |
| Retrieve semantically relevant requirements (RAG) | C4 → C7 |
| Expose requirement surface to user UI | C3 reads from C5 and C7 |
| Expose pipeline events (phase, agent, artifacts) for expert mode | C3 subscribes to NATS events from C4 |

#### R-100-020

```yaml
id: R-100-020
version: 1
status: draft
category: architecture
```

The source of truth for a requirement's textual content SHALL be the `.md` file in C10 (Artifact Store). Metadata in C11 (Graph Store) SHALL be a derived index, rebuildable from the source files.

**Rationale.** Textual corpus is the git-versionable, human-auditable artifact. Index rebuild capability allows C11 to be treated as a cache for indexing purposes.

#### R-100-021

```yaml
id: R-100-021
version: 1
status: draft
category: architecture
```

Writes to the requirement corpus SHALL always go through C5 (Requirements Service). Direct writes to C10 or C11 by other components are prohibited. C12 may read from C5 but SHALL NOT write directly.

**Rationale.** C5 owns the consistency invariants between the `.md` file, the indexed metadata, and the relation graph. Bypassing C5 creates desync.

#### R-100-022

```yaml
id: R-100-022
version: 1
status: draft
category: architecture
```

C5 SHALL provide an idempotent "reindex" operation that rebuilds C11 metadata from C10 source files. This operation SHALL be safe to run while the platform is serving traffic (no downtime).

**Rationale.** Recovery from index corruption, schema migration, embedding model upgrade — all require rebuild capability.

---

### 4.4 Authentication & Authorization

#### Authentication: three pluggable modes

The platform SHALL support three mutually exclusive authentication modes, selected at deployment time via configuration.

#### R-100-030

```yaml
id: R-100-030
version: 1
status: draft
category: security
```

C2 (Auth Service) SHALL support three pluggable authentication modes: `none`, `local`, `sso`. The active mode SHALL be set by configuration at deployment time and SHALL NOT change at runtime.

**Rationale.** Mode switches at runtime introduce complex state-migration issues for in-flight sessions. Restart-to-switch is an acceptable operational constraint.

#### R-100-031

```yaml
id: R-100-031
version: 1
status: draft
category: security
```

In `none` mode, C2 SHALL issue a JWT for a single system-wide user `john.doe` for any incoming authentication request, without credential verification. All sessions in `none` mode SHALL share the same user identity and the same project memory.

**Rationale.** `none` mode targets single-user demos, tutorials, and local development. It is deliberately not safe for multi-user concurrent usage.

#### R-100-032

```yaml
id: R-100-032
version: 1
status: draft
category: security
```

The platform SHALL refuse to start in `none` mode if the environment variable `PLATFORM_ENVIRONMENT` is set to `production` or `staging`. The startup check SHALL fail with a non-zero exit code and a loud log message. Deployment manifests for production SHALL set this variable explicitly.

**Rationale.** `none` mode in production is a security catastrophe. This guard is non-bypassable at the code level, not just documented as a convention.

#### R-100-033

```yaml
id: R-100-033
version: 1
status: draft
category: security
```

When running in `none` mode, the UI SHALL display a persistent, visible banner stating "INSECURE DEV MODE — NO AUTHENTICATION". The banner SHALL NOT be dismissible and SHALL be rendered by the Gateway (C1) to prevent its removal by compromised downstream components.

**Rationale.** Visual hazard signal is the last line of defence when a dev instance is inadvertently exposed.

#### R-100-034

```yaml
id: R-100-034
version: 1
status: draft
category: security
```

In `local` mode, C2 SHALL store user credentials as `(username, argon2id_hash, salt, metadata)` tuples in a dedicated ArangoDB collection. Other hashing algorithms (bcrypt, scrypt, sha256, pbkdf2, plaintext) SHALL NOT be permitted.

**Rationale.** argon2id is the current state-of-the-art password hashing function (winner of the Password Hashing Competition, recommended by OWASP). No legitimate reason to use anything weaker in a new system.

#### R-100-035

```yaml
id: R-100-035
version: 1
status: draft
category: security
```

In `local` mode, password self-service recovery (reset-by-email) SHALL NOT be implemented in v1. Password resets SHALL require administrator action via an admin CLI or admin UI.

**Rationale.** Self-service reset requires an email transport stack (SMTP, deliverability, templating) that expands attack surface and operational burden without clear v1 value. Deferred to v2 alongside the MFA work.

#### R-100-036

```yaml
id: R-100-036
version: 1
status: draft
category: security
```

Multi-factor authentication (MFA) SHALL be out of scope for v1 across all three modes. In `sso` mode, MFA enforcement is delegated to the external IdP and is not the platform's concern.

**Rationale.** MFA in `local` mode would require TOTP/WebAuthn support. Deferred as a v2 roadmap item. `sso` mode inherits whatever the external IdP enforces.

#### R-100-037

```yaml
id: R-100-037
version: 1
status: draft
category: security
```

In `sso` mode, C2 SHALL integrate with external OIDC-compliant identity providers via oauth2-proxy (variant A). The platform SHALL NOT self-host an IdP in v1; Keycloak deployment is not in scope.

**Rationale.** Delegating to managed IdPs (Auth0, Microsoft Entra, Google Workspace, or a tenant's Keycloak) reduces operational burden and attack surface.

#### R-100-038

```yaml
id: R-100-038
version: 1
status: draft
category: security
```

All three authentication modes SHALL emit JWTs with an identical claim structure (see E-100-001). Downstream components SHALL NOT need to know which authentication mode was used to serve a request. The `auth_mode` claim is informative only, used for audit purposes.

**Rationale.** Uniformity downstream is the whole point of centralising auth behind C2. Divergent JWT structures per mode would defeat that goal.

#### R-100-039

```yaml
id: R-100-039
version: 1
status: draft
category: security
```

C1 (Gateway) SHALL enforce rate limiting on authentication endpoints (`/auth/login`, `/auth/token`). Default limits: 10 requests per minute per source IP, 5 consecutive failed logins per account trigger a 15-minute account lock in `local` mode.

**Rationale.** Password brute-force and credential stuffing are the most common attacks on auth endpoints. Rate limits at the gateway prevent C2 overload and slow attackers.

#### Authorization: always managed internally

#### R-100-040

```yaml
id: R-100-040
version: 1
status: draft
category: security
```

Authorization decisions (what a user can do) SHALL be managed internally by the platform, regardless of the active authentication mode. External IdPs, when used for authentication, SHALL NOT be queried for authorization decisions.

**Rationale.** Externalising authorization to an IdP would create tight coupling, high latency, and limited expressiveness for platform-specific permissions (per-project roles, per-requirement ownership).

#### R-100-041

```yaml
id: R-100-041
version: 1
status: draft
category: security
```

The v1 authorization model SHALL be role-based (RBAC) with three global roles (`admin`, `tenant_admin`, `user`) and three per-project scoped roles (`project_owner`, `project_editor`, `project_viewer`). The full role-permission matrix SHALL be defined in E-100-002.

**Rationale.** RBAC covers the expected v1 use cases. ABAC is a v2 consideration if concrete unmet requirements emerge.

#### R-100-042

```yaml
id: R-100-042
version: 1
status: draft
category: security
```

Coarse-grained authorization decisions (route-level access, tenant isolation, global quotas) SHALL be enforced by C1 (Gateway) using the JWT claims. Fine-grained authorization decisions (resource-specific actions within a project) SHALL be enforced by the component that owns the resource.

**Rationale.** Coarse at the edge stops unauthorised traffic early. Fine-grained at the component respects component ownership and keeps business logic co-located with enforcement.

---

### 4.5 Scaling Model

#### R-100-050

```yaml
id: R-100-050
version: 1
status: draft
category: architecture
```

Every stateless component (C1–C9, excluding ephemeral C15) SHALL be horizontally scalable via Kubernetes Horizontal Pod Autoscaler (HPA) with the following default metrics: CPU utilisation (target 70%), memory utilisation (target 75%), and custom application metrics where justified.

**Rationale.** CPU and memory are the baseline. Custom metrics (e.g. queue depth for C4, embedding request rate for C7) provide better signal for uneven workloads and SHOULD be added per-component as data becomes available.

#### R-100-051

```yaml
id: R-100-051
version: 1
status: draft
category: architecture
```

Every horizontally scalable component SHALL have `minReplicas=1` and `maxReplicas` configured per-component based on observed capacity. The platform SHALL operate correctly at `minReplicas=1` for all components on a single-machine deployment.

**Rationale.** Minimum one replica enables local development. Maximum replicas prevents runaway scaling from exhausting cluster resources.

#### R-100-052

```yaml
id: R-100-052
version: 1
status: draft
category: architecture
```

Scale-down behaviour SHALL include a stabilisation window (default 5 minutes) to prevent thrashing under bursty loads. Scale-up behaviour SHALL be fast (stabilisation ≤ 60 seconds) to preserve user-perceived latency.

**Rationale.** Asymmetric stabilisation: react fast to load, slow to relief. Standard HPA practice.

#### R-100-053

```yaml
id: R-100-053
version: 1
status: draft
category: architecture
```

C11 (ArangoDB) SHALL scale vertically for the primary node in v1. Read replicas MAY be added horizontally when read-heavy workloads (retrieval, coherence checks, source ingestion queries) demonstrably exceed the primary's capacity. Horizontal write scaling is out of scope for v1.

**Rationale.** ArangoDB's SmartGraph sharding is powerful but adds complexity not justified at v1 scale. Vertical scaling + read replicas cover a wide range of load.

#### R-100-054

```yaml
id: R-100-054
version: 1
status: draft
category: architecture
```

C10 (MinIO) SHALL be deployed in distributed mode in production (4 or more nodes) for data durability. In local development, single-node mode is acceptable.

**Rationale.** MinIO's distributed mode provides erasure coding and node failure tolerance; single-node is adequate for development but loses durability guarantees.

#### R-100-055

```yaml
id: R-100-055
version: 1
status: draft
category: architecture
```

C15 (Sub-agent Runner) SHALL scale by instantiation: each dispatched sub-agent is one Kubernetes Job. The Orchestrator (C4) SHALL enforce a per-project concurrency limit (default 5 concurrent sub-agents per project, configurable per tenant) to prevent resource exhaustion.

**Rationale.** Sub-agent pods are the most resource-intensive units of work (memory-heavy LLM context, tool exec). Unbounded concurrency from a single project could starve others.

#### R-100-056

```yaml
id: R-100-056
version: 1
status: draft
category: architecture
```

The platform SHALL NOT require any component to be manually scaled. All scaling decisions SHALL be taken by the cluster's autoscaling machinery based on declared policies.

**Rationale.** "Scaling by design, automatically" as per user requirement. Manual scaling is an operational anti-pattern that doesn't survive growth.

---

### 4.6 Deployment Targets

#### R-100-060

```yaml
id: R-100-060
version: 1
status: draft
category: infrastructure
```

The platform SHALL deploy identically on two target environments: Docker Desktop with built-in Kubernetes (local, macOS and Linux) and Azure Kubernetes Service (AKS, production). The same Helm charts (or equivalent manifests) SHALL be used for both; differences are expressed through values files.

**Rationale.** Environment parity is a prerequisite for reproducible issues, trustworthy pre-prod testing, and fast iteration.

#### R-100-061

```yaml
id: R-100-061
version: 1
status: draft
category: infrastructure
```

The platform SHALL be deployable to the local target in under 10 minutes from a clean cluster, including initialisation of C10 (MinIO buckets) and C11 (ArangoDB collections and indexes).

**Rationale.** Fast local deploy is a developer productivity metric. Slow deploys discourage local iteration.

#### R-100-062

```yaml
id: R-100-062
version: 1
status: draft
category: infrastructure
```

All platform components SHALL be deployed in a single Kubernetes namespace per installation. Multi-tenant isolation SHALL be achieved by logical isolation (tenant-scoped data, JWT claims, RBAC) rather than by namespace-per-tenant.

**Rationale.** Namespace-per-tenant was considered and rejected for v1 due to operational overhead (per-tenant TLS certs, network policies, resource quotas). Logical isolation is sufficient when authorization is enforced consistently. Migration path to namespace-per-tenant is preserved by not relying on cross-tenant network reachability.

#### R-100-063

```yaml
id: R-100-063
version: 1
status: draft
category: infrastructure
```

The platform SHALL NOT depend on cloud-provider-specific services that are not available as equivalent in the local target. For example, managed Postgres services (Azure Database for PostgreSQL) SHALL NOT be assumed; ArangoDB runs in-cluster in both targets.

**Rationale.** Cloud-specific dependencies break parity and create vendor lock-in. The stack (D-002) was chosen in part for its portability.

---

### 4.7 Failure Domains & Graceful Degradation

#### R-100-070

```yaml
id: R-100-070
version: 1
status: draft
category: architecture
```

The platform SHALL define explicit failure domains for each dependency and document degraded-mode behaviour. Minimum declared failure domains: LLM provider unreachable, C11 (ArangoDB) unreachable, C10 (MinIO) unreachable, external IdP unreachable, NATS unreachable, C12 (n8n) unreachable.

#### R-100-071

```yaml
id: R-100-071
version: 1
status: draft
category: architecture
```

When an LLM provider is unreachable, the platform SHALL: return a clear error to the user (not a timeout), log a structured event, and, if fallback providers are configured (see D-011 level 2+, v2 scope), retry with the fallback. In v1, a single provider failure is a user-facing error.

#### R-100-072

```yaml
id: R-100-072
version: 1
status: draft
category: architecture
```

When C11 (ArangoDB) is unreachable, the platform SHALL return 503 Service Unavailable from all endpoints that require read or write access to the corpus. The platform SHALL NOT serve stale cached data as fresh in this state.

**Rationale.** The corpus is the source of truth; serving stale data risks silent divergence between what the user sees and what is actually stored. Honest unavailability is preferable.

#### R-100-073

```yaml
id: R-100-073
version: 1
status: draft
category: architecture
```

When the external IdP is unreachable in `sso` mode, existing valid JWTs SHALL continue to be accepted until their expiration. New login attempts SHALL fail with a clear message. Session refresh SHALL fail gracefully when the refresh requires IdP contact.

**Rationale.** Short-term IdP outages should not invalidate existing user sessions. Defense in depth: the JWT carries enough state for downstream authorization without IdP contact.

#### R-100-074

```yaml
id: R-100-074
version: 1
status: draft
category: architecture
```

When NATS is unreachable, the platform's conversational path (user → C3) SHALL continue to function, but expert mode features (phase transitions, agent dispatch events, live pipeline visualisation) SHALL be unavailable and SHALL display a "pipeline telemetry unavailable" indicator.

**Rationale.** Telemetry is not on the critical path of user value. Losing it should degrade the expert-mode UX, not break core functionality.

#### R-100-075

```yaml
id: R-100-075
version: 2
status: draft
category: architecture
```

When C12 (n8n) is unreachable, the platform's conversational and generation paths SHALL continue to function. External source ingestion (upload, parsing) SHALL queue uploads for later processing and inform the user that sources will be indexed when service is restored. Already-indexed sources remain fully available for retrieval.

**Rationale.** Ingestion is asynchronous by nature and should not block interactive workflows. Queueing uploads aligns with user expectations for upload progress and eventual consistency.

---

### 4.8 External Source Ingestion

This subsection operationalises D-013 at the architecture level. Detailed parsing, chunking, and retrieval specifics are deferred to `400-SPEC-MEMORY-RAG.md`, pending alignment with simplechat/AyExtractor prior work.

#### R-100-080

```yaml
id: R-100-080
version: 1
status: draft
category: functional
```

The platform SHALL accept external source uploads from authenticated users for indexing into their project's RAG context. The supported formats in v1 SHALL be limited to: PDF (`.pdf`), Markdown (`.md`), plain text (`.txt`), and images (`.png`, `.jpg`, `.jpeg`). Other formats SHALL be rejected with a clear error message.

**Rationale.** Minimum v1 format set per D-013. Progressive format expansion in later versions.

#### R-100-081

```yaml
id: R-100-081
version: 1
status: draft
category: architecture
```

The ingestion pipeline SHALL be implemented through the collaboration of C12 (Workflow Engine, n8n) and C7 (Memory Service). C12 SHALL own: upload reception, per-format parsing and text extraction, chunking, and job orchestration (retry, status tracking). C7 SHALL own: embedding computation and indexing into C11 (ArangoDB) within the `external_sources` index.

**Rationale.** Per D-013 decision. Reuse of existing components over introduction of a new component. n8n's workflow capabilities and available parsing nodes are leveraged; C7 remains the sole owner of embeddings and indexing.

#### R-100-082

```yaml
id: R-100-082
version: 1
status: draft
category: architecture
```

The raw uploaded source files SHALL be persisted in C10 (Artifact Store, MinIO) within a bucket scoped to the owning project. File deletion by the user SHALL cascade to removal from C10 and to index removal in C11.

**Rationale.** Source files are project assets and must survive ingestion for re-indexing (model upgrade, chunking strategy change). Cascade deletion prevents orphan storage.

#### R-100-083

```yaml
id: R-100-083
version: 1
status: draft
category: security
```

External sources SHALL be scoped to a single project. Cross-project source sharing SHALL NOT be supported in v1. A user's access to a source SHALL follow the project-level RBAC rules (see E-100-002).

**Rationale.** Per-project scoping is the simplest safe default. Cross-project sharing introduces complex permission-propagation scenarios deferred to later versions.

#### R-100-084

```yaml
id: R-100-084
version: 1
status: draft
category: functional
```

Retrieval across the RAG corpus SHALL be **federated** across two separated indexes in C11: the `requirements` index (owned by C5) and the `external_sources` index (owned by C7). Retrieval API consumers SHALL specify whether a query targets `requirements`, `external_sources`, or both with explicit weighting.

**Rationale.** Per D-013. Preventing index mixing avoids contamination: a snippet from a user-uploaded PDF must not be returned as if it were a requirement.

#### R-100-085

```yaml
id: R-100-085
version: 1
status: draft
category: functional
```

The ingestion pipeline SHALL implement deduplication at the file level: uploading the same file (identified by content hash) to the same project SHALL result in a single persisted source and a single set of embeddings. Subsequent uploads update the file's metadata (upload timestamps, uploader) without re-running parsing or embedding.

**Rationale.** Prevents storage bloat and unnecessary embedding cost. Content-hash-based deduplication is the standard approach.

#### R-100-086

```yaml
id: R-100-086
version: 1
status: draft
category: functional
```

External sources SHALL be versioned: replacing a previously uploaded source file SHALL preserve the prior version as historical. The retrieval index SHALL return results from the current version only; older versions are accessible via explicit history queries.

**Rationale.** Users legitimately update specifications, drawings, or documentation. Losing history would break traceability; serving stale versions in retrieval would confuse the RAG.

#### R-100-087

```yaml
id: R-100-087
version: 1
status: draft
category: nfr
```

The ingestion pipeline SHALL be asynchronous from the user's point of view. Upload requests SHALL return immediately with a job identifier; the UI SHALL poll or subscribe (via NATS) to report progress, completion, or failure. Ingestion SHALL NOT block the conversational workflow.

**Rationale.** Parsing and embedding can take tens of seconds to minutes for large documents. Synchronous ingestion would kill the UX.

#### R-100-088

```yaml
id: R-100-088
version: 1
status: draft
category: functional
```

The platform SHALL enforce per-project storage quotas for external sources, configurable per tenant. Default quota: 1 GB per project. Exceeding the quota SHALL cause upload rejection with a clear error. Quota monitoring SHALL be accessible via the project admin UI.

**Rationale.** External sources can grow unbounded if unchecked. Quotas prevent cost runaway and abusive usage. Defaults are conservative; operators tune per tenant.

---

## 5. Non-Functional Requirements

### R-100-100

```yaml
id: R-100-100
version: 1
status: draft
category: nfr
```

C1 (Gateway) SHALL add no more than 20 ms of p95 latency to a downstream request in normal operation (excluding authentication logic that itself may require a JWT verification or IdP token exchange).

**Rationale.** The gateway is on every request path; latency budget must be tight.

### R-100-101

```yaml
id: R-100-101
version: 1
status: draft
category: nfr
```

C2 (Auth Service) SHALL issue a JWT in under 100 ms p95 in `local` and `none` modes. `sso` mode latency is bounded by the IdP and is documented but not controlled.

**Rationale.** Auth is on the login path; a slow login ruins first impression. IdP latency is explicitly outside platform control.

### R-100-102

```yaml
id: R-100-102
version: 1
status: draft
category: nfr
```

Cold-start scaling of any stateless component from 1 to 2 replicas SHALL complete in under 30 seconds (image pull cache hit). Cold-start from 0 to 1 replica SHALL complete in under 60 seconds.

**Rationale.** Scale-up latency directly impacts user-perceived responsiveness under load bursts.

### R-100-103

```yaml
id: R-100-103
version: 1
status: draft
category: nfr
```

The platform SHALL expose Prometheus-compatible metrics endpoints on every internal component. Metrics SHALL include at minimum: request rate, error rate, latency percentiles (p50, p95, p99), resource utilisation.

**Rationale.** Observability baseline. Custom metrics come on top; these four are mandatory.

### R-100-104

```yaml
id: R-100-104
version: 1
status: draft
category: nfr
```

The platform SHALL emit structured logs (JSON) including at minimum: timestamp, component, severity, trace_id, span_id, tenant_id (when applicable), message. Free-form string logs SHALL NOT be emitted in production.

**Rationale.** Structured logs are a prerequisite for effective log aggregation and incident response.

### R-100-105

```yaml
id: R-100-105
version: 1
status: draft
category: nfr
```

The platform SHALL implement distributed tracing with W3C Trace Context propagation across all inter-component calls. Traces SHALL be sampled at a configurable rate (default 10% in production, 100% in local).

**Rationale.** Multi-component workflows (conversation → orchestrator → multiple sub-agents → validation → LLM) are impossible to debug without distributed tracing.

### R-100-106

```yaml
id: R-100-106
version: 1
status: draft
category: nfr
```

The resource footprint of the platform at minimum deployment (all components at `minReplicas=1`, no active user load) SHALL not exceed 4 vCPU and 8 GB RAM across all internal components (C1–C9), excluding dependency stores (C10–C12).

**Rationale.** Small-start principle. Aggregate resource consumption at idle sets the lower bound of the feasible deployment envelope.

### R-100-107

```yaml
id: R-100-107
version: 1
status: draft
category: nfr
```

The platform SHALL persist end-to-end cost tracking per user, per project, and per sub-agent dispatch in C11. Cost data SHALL be queryable and retained for at least 90 days.

**Rationale.** LLM costs are material and tenant-attributable; cost tracking is a business requirement and an operational safeguard (runaway detection).

### R-100-108

```yaml
id: R-100-108
version: 1
status: draft
category: nfr
```

External source ingestion throughput SHALL be sufficient to process a typical 50-page PDF (parsing, chunking, embedding) within 2 minutes p95 on standard deployment resources. Larger documents MAY take proportionally longer.

**Rationale.** Establishes a user-observable performance expectation for the ingestion UX. Longer waits degrade the "upload and go back to work" experience.

---

## 6. Interfaces & Contracts

### 6.1 Communication styles

| Communication type | Style | Rationale |
|---|---|---|
| External client → C1 (Gateway) | HTTPS + REST/JSON (+ WebSocket for conversation streams) | Standard web client. |
| C1 → downstream internal components | HTTP + REST/JSON, JWT in `Authorization: Bearer` header | Uniform internal traffic. Internal TLS enforced via mTLS (v2) or service mesh. |
| C4 (Orchestrator) → C15 (Sub-agent Runner) | Kubernetes Jobs API; result via MinIO path + NATS event | Native K8s; natural isolation. |
| C8 (LLM Gateway) → LLM providers | OpenAI-compatible REST over HTTPS | Imposed by D-011. |
| Any component → C11 (ArangoDB) | ArangoDB native protocol (HTTP or TCP) | Owner-component-only per R-100-012. |
| Any component → C10 (MinIO) | S3-compatible API over HTTPS | Standard. |
| Any component → NATS | NATS protocol (TCP) | Event bus. |
| C9 (MCP Server) ↔ external LLM agents | MCP protocol over stdio or SSE | Imposed by MCP. |
| User session → IdP (in `sso` mode) | OIDC flow (authorization code + PKCE) | Standard. |
| User upload → C1 → C12 ingestion workflow | HTTPS multipart upload; async job id; NATS progress events | Async upload pattern. |

### 6.2 Contracts to be formalised

The following contracts are declared here and fully specified in the owning component's detailed spec or in the entities below.

| Contract | Consumer → Producer | Detailed in |
|---|---|---|
| JWT claim schema | all internal → C2 | E-100-001 (this doc) |
| RBAC model | C1, C3, C4, C5, C6, C7 → C2 | E-100-002 (this doc) |
| NATS event taxonomy (pipeline events, ingestion progress events) | C3 ← C4, C3 ← C12 | 200-SPEC-PIPELINE-AGENT, 400-SPEC-MEMORY-RAG |
| Requirements CRUD API | C3, C4, C6, C9 → C5 | 300-SPEC-REQUIREMENTS-MGMT |
| Validation pipeline API | C4, C9 → C6 | 700-SPEC-VERTICAL-COHERENCE |
| Retrieval API (federated: requirements + external sources) | C4 → C7 | 400-SPEC-MEMORY-RAG |
| Ingestion job API | C12 → C7 (embedding + indexing) | 400-SPEC-MEMORY-RAG |
| LLM completion API | C3, C4 → C8 | 800-SPEC-LLM-ABSTRACTION |
| Sub-agent job manifest | C4 → C15 | 200-SPEC-PIPELINE-AGENT |
| MCP tool schema | external → C9 | 300-SPEC-REQUIREMENTS-MGMT + 700-SPEC-VERTICAL-COHERENCE |
| Domain validation plugin contract | C6 ← domain plugins | 700-SPEC-VERTICAL-COHERENCE |

### 6.3 Contract-critical entities

#### E-100-001: Platform-internal JWT claim schema

```yaml
id: E-100-001
version: 1
status: draft
category: architecture
```

The JWT issued by C2 SHALL contain the following claims, in JSON structure. Fields marked `optional` MAY be absent.

```json
{
  "iss": "platform-auth",
  "sub": "<user-id>",
  "aud": "platform",
  "iat": 1700000000,
  "exp": 1700003600,
  "jti": "<unique-token-id>",

  "auth_mode": "none" | "local" | "sso",
  "tenant_id": "<tenant-id>",

  "roles": ["user" | "admin" | "tenant_admin"],
  "project_scopes": {
    "<project-id>": ["owner" | "editor" | "viewer"]
  },

  "name": "<display name, optional>",
  "email": "<optional, may be absent in none mode>"
}
```

**Signing.** HS256 in development, RS256 or EdDSA in production. The signing key is rotated per Q-100-005.

**Expiration.** Default 1 hour. Refresh tokens out of scope for v1; users re-authenticate on expiry.

#### E-100-002: RBAC model

```yaml
id: E-100-002
version: 1
status: draft
category: security
```

The platform's RBAC model comprises:

**Global roles** (stored in JWT `roles` claim):

| Role | Permissions |
|---|---|
| `admin` | All actions across all tenants. Reserved for platform operators. |
| `tenant_admin` | All actions within their `tenant_id`. Can create projects, manage users within tenant. |
| `user` | Baseline. Can hold project scopes; cannot administer tenant. |

**Project scoped roles** (stored in JWT `project_scopes` claim, per project):

| Role | Permissions (including external source operations) |
|---|---|
| `project_owner` | All actions on the project, including deletion, ACL management, source uploads, and source deletion. |
| `project_editor` | Create/edit requirements, run pipeline, upload sources, view reports. Cannot delete project, change ACL, or delete sources uploaded by others. |
| `project_viewer` | Read-only access to requirements, reports, sources, conversation history. Cannot trigger pipeline or upload sources. |

**Permission resolution.** A user's effective permission on a resource is the union of their global roles and their project-scoped roles for that resource's project. The most permissive applicable rule wins (principle of most-privilege-needed, within what the roles allow).

**Persistence.** The authoritative RBAC data (users, tenants, project memberships, role assignments) lives in dedicated ArangoDB collections owned by C2.

#### E-100-003: Component dependency graph

```yaml
id: E-100-003
version: 2
status: draft
category: architecture
```

```mermaid
flowchart LR
    EXT([External client])
    IdP([External IdP])
    LLMProv([LLM Providers])

    EXT --> C1
    C1 <-->|auth| C2
    C2 -.sso only.-> IdP

    C1 --> C3
    C1 --> C4
    C1 --> C5
    C1 --> C6
    C1 -->|uploads| C12

    C3 --> C4
    C3 --> C5
    C3 --> C7

    C4 -.dispatches.-> C15
    C4 --> C5
    C4 --> C6
    C4 --> C7
    C4 --> C8

    C6 --> C5
    C6 --> C7
    C7 --> C8

    C9 --> C5
    C9 --> C6

    C15 --> C8
    C15 --> C5

    C8 --> LLMProv

    C5 --> C11
    C7 --> C11
    C2 --> C11
    C5 --> C10
    C6 --> C10
    C7 --> C10

    C12 -->|parsed content| C7
    C12 -.ingestion / git sync.-> C5
    C12 --> C10

    C3 <-.events.-> NATS[(NATS)]
    C4 <-.events.-> NATS
    C12 <-.progress events.-> NATS
```

Arrows indicate synchronous calls. Dotted lines indicate event-driven or infrequent interactions. Storage dependencies (C10, C11) are owner-restricted per R-100-012.

---

## 7. Open Questions

| ID | Question | Owning decision | Target resolution |
|---|---|---|---|
| Q-100-001 | Which components, if any, require Rust (vs Python) for performance, memory, or safety reasons? | D-002, D-003 | v1 (per-component as implementation starts) |
| Q-100-002 | Exact LiteLLM deployment shape: sidecar per component, shared service, or both? | D-011 | v1 (likely shared service per R-100-011, to confirm in `800`) |
| Q-100-003 | Sub-agent pod lifecycle details: init container, MinIO sync strategy (pull on start, push on exit), timeout per phase type. | D-007 | v1 (detailed in `200-SPEC-PIPELINE-AGENT`) |
| Q-100-004 | Exact NATS deployment (JetStream enabled, stream persistence, retention policy). | — | v1 (can be decided at deploy time; baseline: JetStream enabled, 7-day retention) |
| Q-100-005 | JWT signing key rotation strategy (how often, how propagated to verifiers, grace period). | D-011 | v1 (security-critical; likely 90-day rotation with dual-key verification during grace) |
| Q-100-006 | Choice of reverse proxy in C1: Traefik (baseline per variant A discussion) vs alternative. | — | v1 (baseline Traefik unless concrete objection) |
| Q-100-007 | Exact tenant-to-project assignment model (many-to-many? project-can-span-tenants?). | — | v1 (detailed in `500-SPEC-UI-UX` alongside project creation flow) |
| Q-100-008 | Cost tracking granularity: per-request, per-session, per-phase, per-sub-agent? Storage schema? | D-011 | v1 (detailed in `800-SPEC-LLM-ABSTRACTION`) |
| Q-100-009 | Secret management (LiteLLM API keys, JWT signing keys, ArangoDB passwords): K8s Secrets, external vault (Azure Key Vault), or both? | — | v1 (baseline: K8s Secrets locally, Azure Key Vault in AKS) |
| Q-100-010 | Resource quotas per tenant (CPU, memory, sub-agent concurrency, cost budget): enforcement layer? | — | v2 (billing/metering likely a v2 concern) |
| Q-100-011 | Ingestion parsing library alignment with simplechat/AyExtractor (docling candidate vs actual prior choice). | D-013 | v1 (pending upload of simplechat/AyExtractor specs) |
| Q-100-012 | Ingestion chunking strategy (fixed size, structure-aware, semantic): align with prior work. | D-013 | v1 (pending upload) |
| Q-100-013 | Storage quota per project default (1 GB baseline in R-100-088) and tenant-level override mechanism. | D-013 | v1 (detailed in `400` and `500`) |

---

## 8. Appendices

### 8.1 Component × responsibility matrix

The matrix below summarises, for each component, which architectural concerns it owns and which it does not.

| Concern | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 | C15 | C12 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| External traffic entry | ✅ | | | | | | | | | | |
| TLS termination | ✅ | | | | | | | | | | |
| Coarse authz (route/tenant) | ✅ | | | | | | | | | | |
| JWT issuance | | ✅ | | | | | | | | | |
| User conversation state | | | ✅ | | | | | | | | |
| Expert mode event surface | | | ✅ | | | | | | | | |
| Pipeline orchestration | | | | ✅ | | | | | | | |
| Sub-agent dispatch | | | | ✅ | | | | | | | |
| Hard gate enforcement | | | | ✅ | | | | | | | |
| Requirements CRUD | | | | | ✅ | | | | | | |
| Requirements index (re)build | | | | | ✅ | | | | | | |
| Validation pipeline hosting (domain plugins) | | | | | | ✅ | | | | | |
| Artifact quality checks | | | | | | ✅ | | | | | |
| Vertical coherence checks (per domain) | | | | | | ✅ | | | | | |
| Fine authz (resource-level) | | | | | (✅) | (✅) | (✅) | | (✅) | | |
| Embeddings computation | | | | | | | ✅ | | | | |
| Graph traversal | | | | | | | ✅ | | | | |
| External source indexing | | | | | | | ✅ | | | | |
| Federated retrieval (requirements + sources) | | | | | | | ✅ | | | | |
| LLM provider call | | | | | | | | ✅ | | | |
| LLM cost tracking | | | | | | | | ✅ | | | |
| MCP tool surface | | | | | | | | | ✅ | | |
| Ephemeral task execution | | | | | | | | | | ✅ | |
| Upload reception | | | | | | | | | | | ✅ |
| Per-format parsing | | | | | | | | | | | ✅ |
| Ingestion job orchestration | | | | | | | | | | | ✅ |
| Post-release / git sync | | | | | | | | | | | ✅ |

`(✅)` = fine authz is enforced by the component that owns the resource, for actions within its scope.

### 8.2 Mapping of auth modes to deployment environments (reference)

| Environment | Typical auth mode | Notes |
|---|---|---|
| Local developer laptop (Docker Desktop) | `none` | Fast iteration, no credentials to manage. |
| Local integration testing | `local` | Verifies the auth path, no external IdP needed. |
| CI pipelines (ephemeral clusters) | `local` or `none` | Depends on test scope. |
| Staging (AKS) | `local` or `sso` | Full production fidelity if `sso`. |
| Production (AKS) | `sso` | Mandatory; `none` and `local` may be enabled per R-100-030 but strongly discouraged. |

This mapping is indicative and enforceable only via R-100-032 (production guard against `none` mode).

---

## 10. Configuration & Deployment

Every internal component (C1–C9 plus the mock-LLM used in tests) is
paramétrable through environment variables read at startup by a
Pydantic-settings class. This section codifies the architectural
constraints that emerged during the v1 implementation so future
components inherit the same contract.

### 10.1 Env file as source of truth

#### R-100-110

```yaml
id: R-100-110
version: 1
status: approved
category: architecture
```

Every runtime-overridable parameter of the platform SHALL be reachable
through a **single env-style file** (key=value, one entry per line,
`#` comments). Per-deployment variants (`.env.test`, `.env.dev`,
`.env.prod`) SHALL share the same key set; only the values differ.
A canonical file `.env.example` at the monorepo root SHALL carry the
code-side defaults and document every variable for operators.

**Rationale.** Centralising config in one file eliminates drift
between the compose file, the deployment manifests, and the code
defaults; it also enforces a single surface for audits of
"what can this deployment be tuned to do?".

#### R-100-111

```yaml
id: R-100-111
version: 1
status: approved
category: architecture
```

Each component's `BaseSettings` class SHALL declare
`env_prefix="c<n>_"` (lower-case component id + underscore). Env
variables on disk appear as `C<N>_<FIELD>` (upper-cased; pydantic-
settings is case-insensitive). The only exception is the platform-
wide variable below (R-100-112).

**Rationale.** Namespacing per component prevents collision between
variables that have identical names but different semantics across
components (`ARANGO_DB`, `MINIO_BUCKET`, etc.). Operators can scope
a config change to a single component without risk of leaking into
neighbours.

#### R-100-112

```yaml
id: R-100-112
version: 1
status: approved
category: architecture
```

`PLATFORM_ENVIRONMENT` SHALL be a cross-cutting variable read without
prefix (via Pydantic-settings `validation_alias="PLATFORM_ENVIRONMENT"`)
by every component whose behaviour depends on it. Accepted values:
`development`, `testing`, `staging`, `production`. Components SHALL
NOT define per-component variants (`C5_PLATFORM_ENVIRONMENT` etc.)
— a single operator-level line SHALL propagate identically to the
whole stack.

**Rationale.** `PLATFORM_ENVIRONMENT` drives security-sensitive
guards (e.g. R-100-032 — no `auth_mode=none` in production). Keeping
it cross-cutting eliminates the drift risk where one component reads
"testing" while another reads "production".

### 10.2 Completeness coherence tests

#### R-100-113

```yaml
id: R-100-113
version: 1
status: approved
category: methodology
```

A coherence test SHALL enforce bijection between the Pydantic
Settings fields discovered in `src/` and the keys of every
`.env*` file under the test tree:

- every field of every `BaseSettings` subclass has a line in each
  env file (completeness);
- every line in an env file corresponds to a live field (no orphans);
- `.env.example` and `.env.test*` share the same key set.

A companion contract test SHALL verify, per `(class, field)` pair,
that setting the env var to a non-default value does propagate to
the instantiated Settings object (override effectiveness).

**Rationale.** These tests make configuration drift impossible to
ship silently — adding a field to a Settings class without updating
the env files breaks CI, and vice versa. Override effectiveness
catches regressions where a field is renamed but its alias isn't.

### 10.3 Deployable local stack

#### R-100-114

```yaml
id: R-100-114
version: 1
status: approved
category: tooling
```

Every Python component SHALL be buildable as a container image from
a single shared Dockerfile
(`infra/docker/Dockerfile.python-service`) parameterised by a
build-arg `COMPONENT_MODULE`. The Dockerfile SHALL install all runtime
dependencies from `ay_platform_core/pyproject.toml` — no
hard-coded `pip install` calls of individual libraries. The `src/`
tree SHALL be mountable as a bind volume so developers can iterate
live without rebuilding the image.

**Rationale.** A single Dockerfile guarantees all Python components
share the exact same runtime stack; pyproject-driven installs keep
`pyproject.toml` the single source of truth for dependencies; the
bind-mount closes the edit-rebuild-test loop for day-to-day work.

#### R-100-115

```yaml
id: R-100-115
version: 1
status: approved
category: security
derives-from: [R-100-039]
```

The platform docker-compose topology SHALL expose **exactly one
public host port** — the one bound to C1 Traefik. All internal
services are unreachable from the host network; operators access
them only through the gateway. The single exception is test-only
infrastructure (e.g. the mock-LLM admin port) which MAY publish
additional ports explicitly marked as non-production.

**Rationale.** A single ingress enforces the forward-auth chain
(C2) and applies Traefik's cross-cutting middlewares (rate limit,
secure headers, CORS) to every inter-component call originating
from outside the cluster. Multiple public ports would create auth
side-channels.

#### R-100-116

```yaml
id: R-100-116
version: 1
status: approved
category: tooling
```

The local stack SHALL ship a mock-LLM service (FastAPI app at
`ay_platform_core/src/ay_platform_core/_mock_llm/`) that speaks the
OpenAI-compatible subset C4 requires, with an admin endpoint
(`POST /admin/enqueue`, `GET /admin/calls`, `POST /admin/reset`)
for tests to script per-run LLM responses. CI runs against the
mock by default; a `real-llm` compose profile SHALL be available
to swap in a real LiteLLM proxy when API keys are provided.

**Rationale.** Scripting LLM responses removes non-determinism
from orchestration tests, eliminates provider cost and rate limits
in CI, and lets deterministic assertions ("the pipeline took
exactly N LLM calls") replace soft ones ("the LLM probably
answered").

---

**End of 100-SPEC-ARCHITECTURE.md v3.**
