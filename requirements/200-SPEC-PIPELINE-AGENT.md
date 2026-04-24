---
document: 200-SPEC-PIPELINE-AGENT
version: 2
path: requirements/200-SPEC-PIPELINE-AGENT.md
language: en
status: draft
derives-from: [D-007, D-008, D-011, D-012]
---

# Pipeline & Agent Specification

> **STATUS: draft v2 — first populated pass.** Derives from D-007 (staff-engineer pattern), D-008 (hybrid agent exposure), D-011 (multi-LLM via LiteLLM), D-012 (domain extensibility). Open questions are explicitly enumerated in §7 and MUST be resolved before C4 is considered production-ready.

---

## 1. Purpose & Scope

This document specifies the **Orchestrator (C4)** and the contract between the orchestrator and the agents it coordinates:

- The five-phase pipeline (`brainstorm → spec → plan → generate → dual review`) per D-007.
- The three hard gates enforcing discipline between phases.
- Sub-agent dispatch as ephemeral Kubernetes pods with isolated context.
- Agent-to-LLM contracts: which agents run in which phase, what LLM features they require (cross-referenced to 800-SPEC §4.6).
- The hybrid agent exposure model: invisible by default, expert mode togglable, events published on NATS for C3/UI consumption.
- The domain plug-in contract so that v2+ `documentation` and `presentation` domains register without touching the orchestrator core.
- Escalation model: four statuses, three-fix rule, architectural-review request on halt.

**Out of scope.**
- Per-agent prompt engineering (operational).
- LLM gateway routing details (→ `800-SPEC-LLM-ABSTRACTION.md`).
- Memory/RAG read path (→ `400-SPEC-MEMORY-RAG.md`).
- Per-domain validation check specifics (→ `600-SPEC-CODE-QUALITY.md` for `code` domain).
- UI rendering of expert mode (→ `500-SPEC-UI-UX.md`, which consumes the NATS events specified here).

---

## 2. Glossary

| Term | Definition |
|---|---|
| **Pipeline run** | A single end-to-end execution of the five phases, scoped to one project + one conversation session. Addressable by `run_id`. |
| **Phase** | One of: `brainstorm`, `spec`, `plan`, `generate`, `review`. Phase `review` is the dual review (spec compliance + artifact quality). |
| **Agent** | A named role executing one or more phases (`architect`, `planner`, `implementer`, `spec-reviewer`, `quality-reviewer`, `sub-agent`). |
| **Sub-agent** | An ephemeral agent spawned by the orchestrator for a bounded task, running in an isolated pod with a restricted context. |
| **Hard gate** | A pre-condition enforced before advancing to the next phase. Failure blocks progression and surfaces an actionable error. |
| **Domain** | A production domain (`code`, `documentation`, `presentation`, …) providing its own generation and validation plugins. |
| **Escalation status** | One of `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED`. Returned by every agent completion. |
| **Three-fix rule** | After three consecutive failed fix attempts on the same artifact, halt the pipeline and request architectural review. |

---

## 3. Relationship to Synthesis Decisions

| Decision | How this document operationalises it |
|---|---|
| D-007 (staff-engineer pattern) | Defines the five-phase lifecycle, the three hard gates, the four escalation statuses, the three-fix rule, and the sub-agent dispatch model. |
| D-008 (hybrid exposure) | Defines the NATS event subjects the orchestrator publishes for C3/UI consumption. |
| D-011 (LiteLLM abstraction) | Declares the per-agent feature requirements referenced by 800-SPEC §4.6 and constrains the orchestrator to invoke C8 exclusively (no direct provider calls). |
| D-012 (domain extensibility) | Formulates every gate and agent contract in domain-agnostic terms; defines the plug-in registration mechanism. |

---

## 4. Functional Requirements

### 4.1 Pipeline lifecycle

#### R-200-001

```yaml
id: R-200-001
version: 1
status: draft
category: pipeline-design
```

The orchestrator SHALL execute pipeline runs across exactly five ordered phases: `brainstorm`, `spec`, `plan`, `generate`, `review`. Phases are traversed sequentially; skipping a phase is prohibited. A run MAY terminate before reaching `review` if a hard gate (§4.2) blocks progression or if an agent returns `BLOCKED`.

**Rationale.** The phase sequence encodes the discipline of D-007: no generation without design, no completion without verification. Skipping would dilute the gates.

#### R-200-002

```yaml
id: R-200-002
version: 1
status: draft
category: pipeline-design
```

Each pipeline run SHALL be identified by a unique `run_id` (UUID v4). The run is scoped to a single `(project_id, session_id)` pair. The orchestrator SHALL persist run state in ArangoDB (collection `c4_runs`, owned by C4 per R-100-012) to survive pod restarts. Concurrent runs within the same session SHALL be rejected with HTTP 409.

**Rationale.** One active run per session keeps the conversational UX coherent (user shouldn't see two parallel pipelines in a single chat). Persistence supports HPA and rolling updates per R-100-003.

#### R-200-003

```yaml
id: R-200-003
version: 1
status: draft
category: pipeline-design
```

The orchestrator SHALL advance phases only upon agent completion with a terminal status (`DONE` or `DONE_WITH_CONCERNS`). `NEEDS_CONTEXT` SHALL trigger a context-enrichment round (bounded by R-200-040). `BLOCKED` SHALL halt the run and surface an architectural-review request.

**Rationale.** The four escalation statuses form the only permitted transition signals out of a phase. Other outcomes (exceptions, timeouts) are mapped onto `BLOCKED` by the dispatcher.

### 4.2 Hard gates

#### R-200-010

```yaml
id: R-200-010
version: 1
status: draft
category: pipeline-design
```

**Gate A — Design before artifact.** The orchestrator SHALL NOT allow the `generate` phase to run unless the `plan` phase completed with status `DONE` or `DONE_WITH_CONCERNS` AND the produced plan was explicitly approved by the human user (invisible-mode: implicit approval via continuation; expert-mode: explicit toggle).

**Rationale.** Enforces D-007's first hard gate in domain-agnostic terms: "no artifact before design approval."

#### R-200-011

```yaml
id: R-200-011
version: 1
status: draft
category: pipeline-design
```

**Gate B — Validation artifact before production artifact.** The orchestrator SHALL NOT allow the `generate` phase to emit a production artifact before the associated validation artifact (the domain-specific form: failing test for `code`, unmet acceptance checklist for `documentation`, etc.) has been written AND demonstrated to fail as expected. Domain plug-ins (§4.7) define the concrete form of "validation artifact" and "fails as expected".

**Rationale.** D-007's second hard gate, generalised per D-012. For `code`, this is the TDD red phase.

#### R-200-012

```yaml
id: R-200-012
version: 1
status: draft
category: pipeline-design
```

**Gate C — Fresh verification before completion.** The orchestrator SHALL NOT mark a run as completed until the `review` phase has produced evidence of verification dated AFTER the last artifact modification. Cached or stale verification results are rejected.

**Rationale.** D-007's third hard gate: "no completion claim without fresh verification evidence." Prevents the "green-when-last-measured" anti-pattern.

#### R-200-013

```yaml
id: R-200-013
version: 1
status: draft
category: pipeline-design
```

Hard-gate formulations SHALL be domain-agnostic. Code-specific vocabulary (`test`, `function`, `class`, etc.) SHALL NOT appear in gate definitions. Domain plug-ins translate the abstract gates into concrete checks for their artifact class.

**Rationale.** D-012: backbone contracts are domain-agnostic.

### 4.3 Agents and responsibilities

#### R-200-020

```yaml
id: R-200-020
version: 1
status: draft
category: pipeline-design
```

The orchestrator SHALL recognise the following agent roles in v1:

| Agent | Active in phase(s) | Responsibility |
|---|---|---|
| `architect` | brainstorm, spec | Elicit intent, propose architecture, author requirements |
| `planner` | plan | Decompose into ordered, testable steps; declare gate-B validation artifacts |
| `implementer` | generate | Produce artifacts (code, docs, …) against the plan; dispatches sub-agents for bounded tasks |
| `spec-reviewer` | review | Verify artifact conforms to the approved spec |
| `quality-reviewer` | review | Verify artifact passes the domain's quality checks per 600-SPEC |
| `sub-agent` | any | Ephemeral ad-hoc helper with isolated context |

Each agent role maps to an entry in the `AGENT_CATALOG` (C8 `catalog.py`) that declares its required LLM features.

**Rationale.** Minimal-viable agent set per D-007. The dual-review split (spec compliance vs artifact quality) is preserved.

#### R-200-021

```yaml
id: R-200-021
version: 1
status: draft
category: pipeline-design
```

Agents SHALL invoke LLMs exclusively via the C8 LiteLLM gateway (R-800-011). Direct provider SDK imports (e.g. `anthropic`, `openai`) in agent code are prohibited by architectural policy. Every LLM call SHALL carry the mandatory headers declared in R-800-013 (`X-Agent-Name`, `X-Session-Id`), plus the orchestration-specific `X-Phase` header.

**Rationale.** Single egress point per D-011 for cost tracking, routing, and audit.

#### R-200-022

```yaml
id: R-200-022
version: 1
status: draft
category: pipeline-design
```

Every agent completion SHALL return one of the four escalation statuses. The status SHALL be accompanied by a structured payload matching E-200-002:

- `DONE` — terminal success, output is usable as-is.
- `DONE_WITH_CONCERNS` — terminal success with non-blocking caveats; the orchestrator records them and surfaces them to the user in the run summary.
- `NEEDS_CONTEXT` — agent lacked necessary information; specifies what is missing. Triggers a context enrichment round (R-200-040) without advancing the phase.
- `BLOCKED` — agent cannot proceed; specifies the blocker. Halts the run, requests architectural review.

**Rationale.** Four statuses per D-007 capture every outcome without unbounded error taxonomy.

### 4.4 Sub-agent dispatch

#### R-200-030

```yaml
id: R-200-030
version: 1
status: draft
category: pipeline-design
```

The orchestrator SHALL dispatch sub-agents as **ephemeral Kubernetes pods** (per R-100-040). Each sub-agent pod SHALL be scheduled fresh (no pod reuse), receive the minimum context necessary for its task via a MinIO-sourced context bundle, and terminate after returning its result.

**Rationale.** D-007 (staff-engineer pattern) isolates sub-agent work to prevent context pollution across tasks. Ephemeral pods enforce this boundary at the infrastructure level.

#### R-200-031

```yaml
id: R-200-031
version: 1
status: draft
category: pipeline-design
```

Sub-agent pods SHALL run as non-root, with read-only root filesystem, a scratch `emptyDir` for work files, and egress network policy permitting only C8 (LLM gateway) and C10 (MinIO). No direct provider access, no internet egress.

**Rationale.** Sandboxing per R-100-041. The C8-only egress preserves the single-egress invariant (D-011).

#### R-200-032

```yaml
id: R-200-032
version: 1
status: draft
category: pipeline-design
```

Sub-agent pod lifecycle SHALL be bounded by a hard timeout (default 15 minutes, configurable per agent role). Pods exceeding the timeout SHALL be terminated via Kubernetes `activeDeadlineSeconds`; the orchestrator SHALL treat the timeout as a `BLOCKED` completion for three-fix-rule accounting (R-200-051).

**Rationale.** Prevents runaway sub-agent costs; consistent with rate-limiting/cost-cap defenses at C8.

#### R-200-033

```yaml
id: R-200-033
version: 1
status: draft
category: pipeline-design
```

Sub-agent context bundles SHALL be assembled by the orchestrator in MinIO at path `c4-dispatch/<run_id>/<sub_agent_id>/` and mounted read-only in the pod. Bundles SHALL contain: the relevant requirements excerpt, the plan step scoped to the sub-agent, any prior artifacts the sub-agent may read, and a manifest file (`manifest.json`) describing the task envelope.

**Rationale.** Explicit context manifest is auditable (required by D-007) and enables deterministic replay for debugging.

### 4.5 Context enrichment & retries

#### R-200-040

```yaml
id: R-200-040
version: 1
status: draft
category: pipeline-design
```

On `NEEDS_CONTEXT` completion, the orchestrator SHALL perform a **context enrichment round**: consult the Memory Service (C7, retrieval API defined in 400-SPEC), append the retrieved context to the agent's bundle, and retry the same phase. At most **three** enrichment rounds SHALL be performed per phase; exceeding this count SHALL promote the completion to `BLOCKED`.

**Rationale.** Bounded retries prevent thrash while still handling legitimate context gaps.

#### R-200-041

```yaml
id: R-200-041
version: 1
status: draft
category: pipeline-design
```

On `DONE_WITH_CONCERNS` completion, the orchestrator SHALL record the concerns on the run record (`c4_runs.concerns[]`) and advance. Concerns SHALL be surfaced in the run summary returned to the conversational UI, distinguished from `DONE` by a structured badge.

**Rationale.** Non-blocking concerns must remain visible without blocking the pipeline.

### 4.6 Escalation & three-fix rule

#### R-200-050

```yaml
id: R-200-050
version: 1
status: draft
category: pipeline-design
```

The orchestrator SHALL track the number of consecutive fix attempts on a given artifact (or sub-task) within a single phase. A "fix attempt" is any retry triggered by a gate failure or a reviewer escalation.

**Rationale.** Prerequisite for the three-fix rule (R-200-051).

#### R-200-051

```yaml
id: R-200-051
version: 1
status: draft
category: pipeline-design
```

**Three-fix rule.** After **three** consecutive failed fix attempts on the same artifact within the same phase, the orchestrator SHALL halt the run with status `BLOCKED`, record the fix history on `c4_runs`, and emit a NATS event `orchestrator.{run_id}.review.requested` for the human operator to intervene.

**Rationale.** Per D-007. Beyond three attempts, continued retries rarely resolve the underlying issue and cost more than the architectural review itself.

#### R-200-052

```yaml
id: R-200-052
version: 1
status: draft
category: pipeline-design
```

On `BLOCKED` halt, the orchestrator SHALL preserve all intermediate artifacts (in MinIO under `c4-runs/<run_id>/`) and the full fix history. The human operator MAY resume the run via a dedicated admin endpoint after editing the failing step or rejecting the run.

**Rationale.** Debuggability and auditability. Resumption avoids losing work already done on earlier phases.

### 4.7 Domain plug-in contract

#### R-200-060

```yaml
id: R-200-060
version: 1
status: draft
category: architecture
```

Production domains SHALL register with the orchestrator via a **domain descriptor** (E-200-003) declared in a YAML file mounted at C4 startup. The descriptor enumerates: the domain's artifact MIME types, its validation artifact type, the concrete check bundle to invoke for each hard gate, and the agent roles specific to the domain (if any beyond the v1 roster of R-200-020).

**Rationale.** Per D-012, backbone is domain-agnostic; domain behavior lives in pluggable descriptors.

#### R-200-061

```yaml
id: R-200-061
version: 1
status: draft
category: architecture
```

The v1 implementation SHALL ship with exactly one registered domain: `code`. Its descriptor maps:
- `artifact_mime_types`: `text/x-python`, `text/x-typescript`, and the other languages declared in R-100-XXX.
- `validation_artifact_type`: `pytest_test` for Python, `vitest_test` for TypeScript, etc.
- `gate_b_check`: "validation artifact exists and runs red against the current tree".
- `gate_c_check`: "validation artifact runs green against the current tree with a timestamp newer than the last production-artifact write".

**Rationale.** Concrete domain used by v1. Future domains (v2 `documentation`, v3 `presentation`) register independently.

#### R-200-062

```yaml
id: R-200-062
version: 1
status: draft
category: architecture
```

Domain plug-in registration SHALL be **build-time only** in v1. Runtime registration (hot-plug of a new domain on a running C4) is deferred to v2 when a second domain lands.

**Rationale.** Simpler invariants; forces a conscious deployment cycle on domain changes.

### 4.8 NATS events (hybrid exposure)

#### R-200-070

```yaml
id: R-200-070
version: 1
status: draft
category: pipeline-design
```

The orchestrator SHALL publish events on NATS at the following subjects (hierarchical):

- `orchestrator.{run_id}.phase.started`
- `orchestrator.{run_id}.phase.completed`
- `orchestrator.{run_id}.agent.invoked`
- `orchestrator.{run_id}.agent.completed`
- `orchestrator.{run_id}.sub_agent.dispatched`
- `orchestrator.{run_id}.sub_agent.completed`
- `orchestrator.{run_id}.gate.passed`
- `orchestrator.{run_id}.gate.blocked`
- `orchestrator.{run_id}.review.requested`
- `orchestrator.{run_id}.run.completed`
- `orchestrator.{run_id}.run.blocked`

Payloads SHALL share the envelope defined in E-300-003 (reused). Event-specific payloads are defined in E-200-004.

**Rationale.** Per D-008: invisible-by-default UI can ignore these; expert-mode UI subscribes and renders them. C3 (conversation service) relays relevant events into the conversation thread. Delivery guarantee: at-least-once via NATS JetStream; consumers SHALL be idempotent on `event_id`.

#### R-200-071

```yaml
id: R-200-071
version: 1
status: draft
category: pipeline-design
```

Invisible mode SHALL NOT alter event publication — the events are published unconditionally, and UI-side filtering selects which to render. Changing modes at runtime SHALL NOT require orchestrator restart or re-subscription.

**Rationale.** Decouples agent logic from presentation (D-008 consequence).

### 4.9 Persistence & observability

#### R-200-080

```yaml
id: R-200-080
version: 1
status: draft
category: pipeline-design
```

Run state SHALL be persisted in the `c4_runs` ArangoDB collection (schema in E-200-001) on every phase transition, agent completion, and gate evaluation. On pod restart, in-flight runs SHALL be resumable from the last persisted checkpoint.

**Rationale.** Statelessness (R-100-003) and rolling updates.

#### R-200-081

```yaml
id: R-200-081
version: 1
status: draft
category: nfr
```

The orchestrator SHALL emit Prometheus metrics covering at minimum: runs started/completed/blocked per phase, phase duration percentiles, agent completion status distribution, sub-agent dispatch count and pod lifetime, three-fix-rule triggers, gate failure rate per gate.

**Rationale.** Visibility on operational pipeline health.

---

## 5. Non-Functional Requirements

### 5.1 Performance

#### R-200-100

```yaml
id: R-200-100
version: 1
status: draft
category: nfr
```

Phase-transition overhead (orchestrator bookkeeping, persistence, event emission) SHALL add no more than 200 ms p95 per transition. LLM and sub-agent latency are counted separately against their respective budgets.

**Rationale.** The orchestrator is on the critical path of every phase; its own overhead must be small relative to the LLM calls it coordinates.

### 5.2 Concurrency

#### R-200-110

```yaml
id: R-200-110
version: 1
status: draft
category: nfr
```

A single orchestrator replica SHALL handle at least 50 concurrent pipeline runs on the baseline deployment footprint (R-100-106). Exceeding this count SHALL trigger HPA scale-up per R-100-050.

**Rationale.** Capacity baseline. A conversation turn may trigger a run, so per-replica throughput must match expected conversational load.

### 5.3 Auditability

#### R-200-120

```yaml
id: R-200-120
version: 1
status: draft
category: nfr
```

Every phase transition, agent completion, gate evaluation, and sub-agent dispatch SHALL be recorded in a structured audit log (stdout JSON) with: `run_id`, `project_id`, `tenant_id`, `user_id`, `phase`, `agent`, `status`, `event_type`, `timestamp`. Retention policy follows R-800-072 (≥ 90 days, tenant-configurable).

**Rationale.** Regulated contexts require the ability to reconstruct the exact sequence of agent decisions leading to an artifact.

---

## 6. Interfaces & Contracts

### 6.1 REST API (overview)

The orchestrator SHALL expose a minimal REST surface for conversational clients (C3) and admin tooling:

```
POST   /api/v1/orchestrator/runs
  body: { project_id, session_id, initial_prompt }
  creates a run, returns run_id, status=brainstorm

GET    /api/v1/orchestrator/runs/{run_id}
  returns the run record (RunPublic)

POST   /api/v1/orchestrator/runs/{run_id}/feedback
  body: { phase, user_feedback }
  advances interactive phases (brainstorm/spec/plan) that await user input

POST   /api/v1/orchestrator/runs/{run_id}/resume   (admin-only)
  body: { strategy: "retry" | "skip-phase" | "abort" }
  used to unblock a halted run after architectural review

GET    /api/v1/orchestrator/runs/{run_id}/events?since=<ts>
  SSE-style stream of NATS events for the run (admin / expert-mode UI)
```

Full OpenAPI schema lives in E-200-005.

### 6.2 NATS events

See R-200-070. Payload schema in E-200-004.

### 6.3 Contract-critical entities

#### E-200-001: `c4_runs` ArangoDB collection schema

```yaml
id: E-200-001
version: 1
status: draft
category: architecture
```

```json
{
  "_key": "<run_id>",
  "run_id": "<uuid>",
  "project_id": "<project-id>",
  "session_id": "<session-id>",
  "tenant_id": "<tenant-id>",
  "user_id": "<user-id>",
  "domain": "code",
  "current_phase": "generate",
  "status": "running | completed | blocked",
  "started_at": "2026-04-23T12:00:00Z",
  "completed_at": null,
  "concerns": [ { "phase": "plan", "message": "..." } ],
  "fix_attempts": { "<artifact_id>": 2 },
  "enrichment_rounds": { "plan": 1 },
  "events_emitted": 42,
  "minio_root": "c4-runs/<run_id>/"
}
```

Indexes: `(project_id, session_id)`, `(status, started_at)`.

#### E-200-002: agent completion envelope

```yaml
id: E-200-002
version: 1
status: draft
category: architecture
```

Every agent completion returns:

```json
{
  "agent": "planner",
  "run_id": "<uuid>",
  "phase": "plan",
  "status": "DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED",
  "output": { /* phase-specific */ },
  "concerns": [ { "severity": "low|medium|high", "message": "..." } ],
  "needs_context": { "queries": ["..."] },
  "blocker": { "reason": "...", "suggested_action": "..." },
  "duration_ms": 12345,
  "llm_calls": [ /* references to C8 call_ids */ ]
}
```

Only one of `concerns`, `needs_context`, `blocker` is populated, matching the status.

#### E-200-003: domain descriptor

```yaml
id: E-200-003
version: 1
status: draft
category: architecture
```

Domain plug-ins register via a YAML descriptor:

```yaml
# domains/code/descriptor.yaml
domain: code
artifact_mime_types:
  - text/x-python
  - text/x-typescript
validation_artifact_type: pytest_test
gate_b:
  check: "validation_runs_red"
  implementation: "ay_platform_core.domains.code.checks:run_validation_red"
gate_c:
  check: "validation_runs_green_fresh"
  implementation: "ay_platform_core.domains.code.checks:run_validation_green_fresh"
agents:
  implementer:
    llm_features_additional: [tool_calling]
```

Loaded at C4 startup per R-200-062.

#### E-200-004: NATS event payloads

```yaml
id: E-200-004
version: 1
status: draft
category: architecture
```

Every event shares the envelope defined in E-300-003 (reused). `payload` varies per event:

- `phase.started` / `phase.completed`: `{ "phase": "plan", "agent": "planner", "status": "DONE" }`
- `agent.invoked` / `agent.completed`: the full agent envelope (E-200-002) minus LLM-call references.
- `sub_agent.dispatched`: `{ "sub_agent_id": "...", "task": "...", "pod_name": "..." }`
- `gate.passed` / `gate.blocked`: `{ "gate": "B", "artifact_id": "...", "reason": "..." }`
- `review.requested`: `{ "fix_attempts": 3, "artifact_id": "...", "history": [...] }`

#### E-200-005: orchestrator OpenAPI reference

```yaml
id: E-200-005
version: 1
status: draft
category: architecture
```

Canonical path: `api/openapi/orchestrator-v1.yaml`. Every endpoint in §6.1 SHALL be declared with request/response schemas, auth requirements (bearer JWT per E-100-001), and error examples.

---

## 7. Open Questions

| ID | Question | Owning decision | Target resolution |
|---|---|---|---|
| Q-200-001 | Sub-agent pod image: single baseline image with language-specific containers layered, or one image per domain? | D-007, D-012 | v1 (baseline: single image with domain plug-ins bundled; per-domain images if size exceeds 1 GB) |
| Q-200-002 | Where do sub-agents run: same K8s namespace as C4, or an isolated "workers" namespace? | D-007 | v1 (isolated namespace `c4-workers` for network-policy scoping) |
| Q-200-003 | Conversational feedback during interactive phases (brainstorm/spec/plan): inline SSE vs async NATS event? | D-008 | v1 (NATS event + C3 SSE relay — consistent with other runtime events) |
| Q-200-004 | "Plan approval" in invisible mode: how does the UI surface implicit approval? Via a confirm-to-continue prompt? | D-008 | v1 (UI concern; spec in 500-SPEC; C4 treats any `POST /feedback` with `approved=true` as approval) |
| Q-200-005 | Retention of MinIO run artifacts (`c4-runs/<run_id>/`): 30 days? tenant-configurable? | — | v1 (baseline: 30 days, tenant override for regulatory retention) |
| Q-200-006 | Sub-agent isolation: strict `emptyDir` + no shared cache, or shared read-only cache mount for common libraries? | D-007 | v1 (strict isolation; shared cache deferred until cold-start latency proves prohibitive) |
| Q-200-007 | Three-fix rule scope: per artifact or per phase? The spec reads "per artifact"; must clarify artifact granularity for multi-file generations. | D-007 | v1 (per "logical artifact" = unit of change addressable by the domain plug-in; concrete definition lives in the domain descriptor) |
| Q-200-008 | Dual review ordering (spec compliance first vs quality first)? Does one block the other? | D-007 | v1 (baseline: parallel both reviewers; merge concerns; either `BLOCKED` halts the run) |
| Q-200-009 | Resumption strategy `"skip-phase"` in admin endpoint: allowed only on non-gate phases? Allowed on `review`? | D-007 | v2 (admin override semantics need governance; defer until first production run) |
| Q-200-010 | Architectural-review request: human response channel? Email? Slack? In-platform comment? | D-007, D-008 | v2 (baseline: in-platform comment; external channels via webhook per tenant config) |
| Q-200-011 | Agent LLM call caching: does the orchestrator pre-populate `X-Cache-Hint: static` for architect/planner prompts? | D-011 | v1 (yes — architect/planner carry large stable system prompts that benefit from caching) |
| Q-200-012 | Cross-domain sub-agents: can a run mix `code` and `documentation` domain tasks within one pipeline? | D-012 | v2 (a single run binds to one domain in v1; cross-domain is a v2 concern when the second domain lands) |

---

## 8. Appendices

### 8.1 Phase transition state machine (informative)

```
                    ┌────────────┐
                    │ brainstorm │
                    └──────┬─────┘
                           │ DONE
                           ▼
                    ┌────────────┐
                    │    spec    │
                    └──────┬─────┘
                           │ DONE
                           ▼
                    ┌────────────┐       ┌───────────────────┐
                    │    plan    │──────►│ Gate A: approved? │
                    └──────┬─────┘       └──┬────────────────┘
                           │ approved       │ not approved → loop back to plan
                           ▼
                    ┌────────────┐       ┌─────────────────────────────┐
                    │  generate  │──────►│ Gate B: validation red OK?  │
                    └──────┬─────┘       └──┬──────────────────────────┘
                           │                │ not OK → BLOCKED
                           │ pass
                           ▼
                    ┌────────────┐       ┌─────────────────────────────┐
                    │   review   │──────►│ Gate C: validation fresh OK?│
                    └──────┬─────┘       └──┬──────────────────────────┘
                           │                │ not OK → BLOCKED
                           │ DONE
                           ▼
                      ┌────────┐
                      │ COMPLETED
                      └────────┘
```

### 8.2 Agent → LLM feature mapping (reference only — normative in 800-SPEC §4.6)

See `800-SPEC-LLM-ABSTRACTION.md` §4.6 for the authoritative agent → required features table. This section is informational and must not drift from that source of truth.

---

**End of 200-SPEC-PIPELINE-AGENT.md v2 (first populated draft).**
