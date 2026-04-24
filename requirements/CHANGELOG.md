# Changelog — Requirements Corpus

All notable changes to the requirements corpus in this directory are
documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Changes here track the **corpus evolution** (specs added, versions bumped,
entities introduced / superseded), per `meta/100-SPEC-METHODOLOGY.md` §10.

Per-release headings replace the `[Unreleased]` section at release time.

---

## [Unreleased]

### 2026-04-24 — Test & config foundation (P1–P6)

**Added**
- `100-SPEC-ARCHITECTURE.md` **§10 Configuration & Deployment** — 7 new
  `R-100-1NN` entities covering: single `.env` file as source of truth,
  `env_prefix="c<n>_"` naming convention, `PLATFORM_ENVIRONMENT`
  cross-cutting variable, completeness + override coherence tests,
  shared `Dockerfile.python-service`, docker-compose layout with the
  single public port on Traefik, mock LLM for CI.
- `meta/100-SPEC-METHODOLOGY.md` **§11 Test tier topology** — six-tier
  taxonomy formalised (unit, contract, integration, e2e, system,
  coherence) plus filename conventions (`test_*_real_chain.py`,
  `test_*_real_llm.py`, `test_*_storage_verified.py`) and fixture
  discipline (session-scoped testcontainers + orphan wipe +
  cleanup-with-verify helpers).

**Changed**
- `700-SPEC-VERTICAL-COHERENCE.md` bumped to v3 — `version-drift`
  (R-700-026) and `cross-layer-coherence` (R-700-028) promoted from
  STUB to real implementations (severity `blocking`). Only #3
  interface-signature-drift and #8 data-model-drift remain stubs, both
  deferred pending machine-readable `E-*` entity signature specs.
- `999-SYNTHESIS.md` §6 Document Mapping statuses refreshed — 200/400/
  700 now listed as **delivered**; 500/600 remain planned.

### 2026-04-23/24 — Implementation of C1–C9 backbone

**Added**
- `200-SPEC-PIPELINE-AGENT.md` v2 — 24 `R-200-*` entities, 12 `Q-200-*`
  resolved, five-phase pipeline fully specified (brainstorm → spec →
  plan → generate → review, three hard gates, sub-agent escalation).
- `400-SPEC-MEMORY-RAG.md` v2 — 28 `R-400-*` / `E-400-*` entities, 11
  `Q-400-*`; embedding lifecycle, dual-index schema
  (`requirements` / `external_sources`), federated retrieval, quota.
- `700-SPEC-VERTICAL-COHERENCE.md` v2 — Validation Pipeline Registry
  (C6) plugin contract, Finding model, run lifecycle, 9 MUST checks
  under `R-700-020..028` (see v3 above for stubs closure).

**Notes**
- Scaffolds `500-SPEC-UI-UX.md` and `600-SPEC-CODE-QUALITY.md` are
  unchanged in this cycle — UI and code-domain quality engine are
  scheduled beyond the backbone.

### 2026-04-22 — Initial corpus scaffold

**Added**
- `meta/100-SPEC-METHODOLOGY.md` v2 — authoring conventions, ID scheme,
  frontmatter schemas, tailoring syntax, `@relation` markers.
- `999-SYNTHESIS.md` v4 — cross-cutting decisions `D-001` through
  `D-013`, guiding principles, roadmap (v1..v4+).
- `100-SPEC-ARCHITECTURE.md` v2 — platform component decomposition
  (C1..C15), contracts, scaling model, failure domains.
- `300-SPEC-REQUIREMENTS-MGMT.md` v1 — Requirements Service (C5)
  storage, CRUD, versioning, tailoring.
- `800-SPEC-LLM-ABSTRACTION.md` v1 — LLM Gateway (C8) LiteLLM proxy,
  routing, cost tracking, eval hooks.
- `200-SPEC-PIPELINE-AGENT.md` v1 — scaffold.
- `400-SPEC-MEMORY-RAG.md` v1 — scaffold.
- `500-SPEC-UI-UX.md` v1 — scaffold.
- `600-SPEC-CODE-QUALITY.md` v1 — scaffold.
- `700-SPEC-VERTICAL-COHERENCE.md` v1 — scaffold.
- `references/simplechat-specification_backtend.md` — prior internal
  work (FastAPI chat backend reference implementation).
- `references/simplechat-specification_frontend.md` — prior internal
  work (Next.js chat frontend reference implementation).
- `references/data-Extractor-specifications.md` — prior internal work
  (multi-agent document analyzer, chunking + graph + RAG).
