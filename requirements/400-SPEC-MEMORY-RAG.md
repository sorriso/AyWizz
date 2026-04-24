---
document: 400-SPEC-MEMORY-RAG
version: 2
path: requirements/400-SPEC-MEMORY-RAG.md
language: en
status: draft
derives-from: [D-002, D-010, D-013]
---

# Memory & RAG Specification

> **STATUS: draft v2 — first populated pass.** Derives from D-002 (stack reuse: ArangoDB for both vector and graph), D-010 (graph-backed embeddings, text-only, no node2vec in v1), D-013 (external-source ingestion via C12 + C7). AyExtractor informs the structural patterns (dual-store mental model, chunking, decontextualization) but v1 is deliberately simpler: a single ArangoDB instance, text embeddings only, linear chunking, federated read across two logical indexes.
>
> Open questions in §7 gate any production deployment. Alignment with the `references/data-Extractor-specifications.md` sections §26 (RAG), §29 (embedding), §30.6/§30.7 (store interfaces) is the explicit source for future enrichments.

---

## 1. Purpose & Scope

This document specifies the **Memory Service (C7)** and the ingestion pipeline that feeds it:

- Embedding computation model, storage schema, refresh cadence.
- Federated retrieval across two logical indexes: `requirements` (owned by C5) and `external_sources` (owned by C7) — per D-013.
- External source ingestion: parsing, chunking, embedding, indexing, orchestrated by C12 (n8n) and computed by C7 — per D-013.
- Short-term vs long-term memory boundaries within a conversational run.
- Public REST + MCP surfaces consumed by C3 (conversation), C4 (orchestrator agents), C9 (MCP tool server).

**Out of scope.**
- Write path for the requirements corpus (→ `300-SPEC-REQUIREMENTS-MGMT.md`, already v1-delivered).
- RAG query classification logic internals (implementation detail).
- Node-level graph embeddings (D-010 defers to v2+).
- Online fine-tuning and feedback-loop re-ranking (D-010 out of scope).
- Image OCR pipeline details (referenced by D-013, baseline library choice deferred to Q-400).

---

## 2. Glossary

| Term | Definition |
|---|---|
| **Embedding** | A fixed-length vector representation of a text fragment, produced by a sentence-transformers model. |
| **Chunk** | A bounded text fragment (typically a section / paragraph / fixed-window slice) that is embedded and stored as a unit. |
| **Source** | An external document (PDF, Markdown, TXT, image) uploaded by a user into a project's RAG corpus. |
| **Index** | A logical partition of embeddings. v1 has two: `requirements` (C5-owned) and `external_sources` (C7-owned). |
| **Federated retrieval** | A single retrieval call fans out to one or both indexes with explicit weighting, merges, returns the top-k. |
| **Embedding provider** | An adapter behind `EmbeddingProvider` protocol — local sentence-transformers model, or HTTP API. |
| **Refresh** | The operation that recomputes embeddings for content whose source has changed or whose model was upgraded. |

---

## 3. Relationship to Synthesis Decisions

| Decision | How this document operationalises it |
|---|---|
| D-002 (stack reuse) | ArangoDB hosts both the embeddings (vector) and the entity/source graph (unified). No ChromaDB / Qdrant / Neo4j in v1. |
| D-010 (graph-backed embeddings, approach A + α) | Text embeddings only; no graph neural embeddings. Refresh strategy α: periodic (cron-triggered or commit-triggered); no online fine-tuning. |
| D-013 (external source ingestion) | v1 formats = PDF, Markdown, TXT, images (with optional OCR). C12 receives uploads, dispatches parsing jobs; C7 computes embeddings and indexes. Federated retrieval with separated indexes preserves provenance. |

---

## 4. Functional Requirements

### 4.1 Embedding model & lifecycle

#### R-400-001

```yaml
id: R-400-001
version: 1
status: draft
category: functional
```

The Memory Service SHALL compute text embeddings via an abstract `EmbeddingProvider` interface (E-400-001). Concrete adapters SHALL be swappable via configuration without code changes. The v1 baseline adapter is a local sentence-transformers model (configurable via env var).

**Rationale.** Per D-010: embedding model choice is an operational decision, not architectural. Abstracting the provider lets teams swap between local models (CPU/GPU) and hosted APIs (OpenAI, Voyage, Cohere) based on latency/cost/privacy trade-offs.

#### R-400-002

```yaml
id: R-400-002
version: 1
status: draft
category: functional
```

Every embedding record SHALL carry the `model_id` that produced it (e.g. `sentence-transformers/all-mpnet-base-v2`). Records produced by different models SHALL NOT be mixed in a single retrieval — the retriever SHALL reject or re-rank when the query model differs from stored records' model.

**Rationale.** Cosine similarity is only meaningful within the same embedding space. Silent cross-model retrieval yields garbage results.

#### R-400-003

```yaml
id: R-400-003
version: 1
status: draft
category: functional
```

Embedding dimensions SHALL be declared in the model metadata and validated at write time. Any mismatch between the embedding vector length and the declared dimension SHALL cause a 422 rejection.

**Rationale.** Prevents silent drift on model upgrades.

#### R-400-004

```yaml
id: R-400-004
version: 1
status: draft
category: functional
```

On model upgrade (change of `model_id`), the service SHALL schedule a **re-embedding pass** for every affected index. During the pass, old records remain queryable; new records co-exist tagged with the new `model_id`. Once the pass completes, old records MAY be deleted per tenant retention policy.

**Rationale.** Per D-010 refresh strategy α. Upgrades are rare but disruptive; graceful coexistence avoids downtime.

---

### 4.2 Storage schema (ArangoDB)

#### R-400-010

```yaml
id: R-400-010
version: 1
status: draft
category: functional
```

The Memory Service SHALL own exactly two document collections and one edge collection (per R-100-012):

- `memory_chunks` — one record per embedded chunk (external source chunk OR requirements entity embedding).
- `memory_sources` — one record per uploaded external document (parent of its chunks).
- `memory_links` (edge) — edges from `memory_chunks` to canonical entities in `req_entities` (C5-owned) when a chunk cites or references a requirements entity.

The detailed schema is in Appendix 8.1.

**Rationale.** Minimal schema aligned with D-002 (ArangoDB unifies vector + graph). The edge collection enables "which chunks support this requirement?" queries without joining at retrieval time.

#### R-400-011

```yaml
id: R-400-011
version: 1
status: draft
category: functional
```

Embeddings SHALL be stored as fixed-length `float32[]` arrays in the `vector` field of `memory_chunks`. v1 SHALL NOT use ArangoDB's native vector index (experimental as of the baseline deployment); it SHALL implement cosine similarity via a server-side AQL function with a cap of 50 000 chunks per query scope. Beyond that cap, the query SHALL be progressively narrowed by metadata filters (project, source type, date).

**Rationale.** Native vector indexes in ArangoDB 3.12 are experimental. AQL-based cosine works up to tens of thousands of chunks with acceptable latency. The cap forces filter-first retrieval discipline, avoiding degenerate full-corpus scans.

#### R-400-012

```yaml
id: R-400-012
version: 1
status: draft
category: functional
```

Every `memory_chunks` record SHALL carry provenance metadata: `project_id`, `source_id` (for external) OR `entity_id` + `entity_version` (for requirements), `chunk_index`, `content_hash`, `model_id`, `model_dim`. Fields not matching the schema SHALL be rejected at write time.

**Rationale.** Provenance is the basis for retrieval ranking, citation, and invalidation. No chunk without provenance.

#### R-400-013

```yaml
id: R-400-013
version: 1
status: draft
category: functional
```

The `memory_sources` record SHALL reference the MinIO path of the original uploaded file so that re-parsing is always possible from the source of truth. The record SHALL also carry: `tenant_id`, `project_id`, `uploaded_by`, `upload_timestamp`, `content_mime_type`, `size_bytes`, `parse_status` (one of `pending`, `parsed`, `failed`), `chunk_count`.

**Rationale.** Parse is idempotent from the MinIO source; re-parse on schema upgrade or parser upgrade becomes a single job per source, not a re-upload.

---

### 4.3 External source ingestion (D-013)

#### R-400-020

```yaml
id: R-400-020
version: 1
status: draft
category: functional
```

External source ingestion SHALL be a three-step pipeline:

1. **Upload** — a user POSTs the file to C12 (n8n `/uploads/*` endpoint). C12 stores the raw bytes in MinIO under `sources/<project_id>/<source_id>/raw.<ext>` and emits a NATS event `ingestion.source.uploaded`.
2. **Parse** — C7 consumes the NATS event, reads MinIO, invokes the parser matching the file's MIME type, writes the parsed text output to MinIO under `sources/<project_id>/<source_id>/parsed.txt` and the chunked JSON under `sources/<project_id>/<source_id>/chunks.json`.
3. **Index** — C7 computes embeddings on each chunk and writes the records to `memory_chunks` + `memory_sources`. On completion, emits `ingestion.source.indexed`.

Each step SHALL be idempotent and individually re-runnable from the MinIO artifacts.

**Rationale.** Per D-013: C12 owns orchestration, C7 owns parsing+embedding. The three-step split lets each stage fail and retry without reprocessing the whole pipeline.

#### R-400-021

```yaml
id: R-400-021
version: 1
status: draft
category: functional
```

v1 parsers SHALL support:

- `text/plain` — pass-through.
- `text/markdown` — frontmatter stripped, headings preserved as chunk boundaries.
- `application/pdf` — text extraction via the configured PDF library (Q-400-001).
- `image/png`, `image/jpeg` — optional OCR via the configured OCR library (Q-400-002). If OCR is disabled for the project, image ingestion SHALL fail with a clear error.

Other formats SHALL return HTTP 415 at the C12 upload surface (enforced before C7 is invoked).

**Rationale.** Minimum viable format set per D-013 option (i). DOCX/PPTX/XLSX deferred to v2; HTML/CSV/JSON/URL crawling to v3; Git clone to v4.

#### R-400-022

```yaml
id: R-400-022
version: 1
status: draft
category: functional
```

Chunking SHALL use a **fixed-window strategy** in v1: chunks of `CHUNK_TOKEN_SIZE` tokens (default 512), with `CHUNK_OVERLAP` tokens of overlap (default 64), computed with the tokenizer of the configured embedding model. Paragraph/heading-aware chunking is deferred to v2 when domain-specific parsers land.

**Rationale.** Fixed-window is robust and model-aware; AyExtractor's structure-aware chunking is valuable but requires per-format adapters that exceed the v1 baseline.

#### R-400-023

```yaml
id: R-400-023
version: 1
status: draft
category: functional
```

Ingestion SHALL be **scoped to one project**: an upload declares its `project_id` and the resulting embeddings are only ever retrieved for queries targeting that project. Cross-project retrieval is explicitly prohibited in v1.

**Rationale.** Per D-013 and R-100-083. Cross-project contamination is a larger security/privacy concern than the convenience of "find this everywhere".

#### R-400-024

```yaml
id: R-400-024
version: 1
status: draft
category: functional
```

Per-project storage quota SHALL be enforced at upload time. Default: 1 GB per project, configurable per tenant. Exceeding the quota SHALL return HTTP 413 at C12. The current usage SHALL be queryable via `GET /api/v1/memory/projects/{project_id}/quota`.

**Rationale.** Prevents runaway embedding costs and storage bills. Per-tenant override supports regulated contexts with larger retention needs.

---

### 4.4 Requirements-corpus embedding (write side)

#### R-400-030

```yaml
id: R-400-030
version: 1
status: draft
category: functional
```

Every time an entity is created or materially updated in C5, C7 SHALL receive a NATS event (`requirements.*.entity.created|updated`) and re-embed the entity's body. The resulting `memory_chunks` record SHALL carry `entity_id`, `entity_version`, `content_hash`, and SHALL be scoped to the `requirements` index.

**Rationale.** Per D-010: embeddings are kept fresh by event-driven re-compute on write-through. No polling.

#### R-400-031

```yaml
id: R-400-031
version: 1
status: draft
category: functional
```

Entity versions SHALL co-exist in the `requirements` index: embedding records for `v1` SHALL NOT be deleted when `v2` arrives. Retrieval SHALL by default return only the latest version of each entity; a flag `include_history=true` SHALL expose prior versions.

**Rationale.** Historical traceability per R-M100-091; fresh default prevents the retriever from surfacing stale text.

#### R-400-032

```yaml
id: R-400-032
version: 1
status: draft
category: functional
```

Requirements entities with `status = deprecated` SHALL be retained in the index with a flag; retrieval SHALL NOT return them unless `include_deprecated=true`.

**Rationale.** Per R-M100-091 deprecated entities remain discoverable by auditors but are out of the default retrieval set for agents.

---

### 4.5 Federated retrieval (D-013)

#### R-400-040

```yaml
id: R-400-040
version: 1
status: draft
category: functional
```

The retrieval API SHALL expose `POST /api/v1/memory/retrieve` accepting:

- `project_id` (required).
- `query` (required, text).
- `indexes` (required): non-empty subset of `{"requirements", "external_sources"}`.
- `top_k` (optional, default 10, max 50).
- `weights` (optional): per-index multiplier applied to the similarity score; defaults to `{requirements: 1.0, external_sources: 1.0}`.
- `filters` (optional): `{status, category, domain, source_id, ...}` — the accepted keys depend on the index.
- `include_history` (optional, default False).
- `include_deprecated` (optional, default False).

Response: `RetrievalResponse` with a merged, weighted, re-ranked list of up to `top_k` records, each carrying full provenance (entity_id/source_id, chunk_index, score, index, snippet).

**Rationale.** Federated retrieval per D-013 with explicit per-index weighting avoids the contamination issue (an external PDF snippet being treated as a requirement) while still giving callers one call site.

#### R-400-041

```yaml
id: R-400-041
version: 1
status: draft
category: nfr
```

Retrieval latency SHALL be under 200 ms p95 for `top_k ≤ 10` on corpora up to 10 000 chunks per index. Beyond that scale, the caller SHALL narrow the query via filters before hitting the retriever, or accept degraded latency until v2 introduces indexed search.

**Rationale.** Agents (C4) depend on retrieval on the hot path of every LLM call. Sub-200 ms keeps the LLM-driven latency dominant.

#### R-400-042

```yaml
id: R-400-042
version: 1
status: draft
category: functional
```

The retriever SHALL reject requests where the query model and the stored `model_id` differ, returning HTTP 409 with guidance to re-embed or query with the matching model. No automatic cross-model re-ranking in v1.

**Rationale.** Per R-400-002. Prevents silent quality degradation.

#### R-400-043

```yaml
id: R-400-043
version: 1
status: draft
category: functional
```

The retrieval response SHALL include a `retrieval_id` (UUID) and the full set of input parameters (for debugging and reproducibility), and SHALL emit a NATS event `memory.retrieval.completed` carrying the same id, the `top_k` snippets' chunk_ids, and the resulting scores.

**Rationale.** Observability for evaluating retrieval quality (input → output pair) and for future eval harness correlation.

---

### 4.6 Short-term vs long-term memory

#### R-400-050

```yaml
id: R-400-050
version: 1
status: draft
category: functional
```

**Short-term memory** is the conversational context held by C3 (message history) — NOT part of C7. C7 memory is exclusively long-term: persisted embeddings of external sources and requirements.

**Rationale.** Avoid feature creep. Conversational short-term context is already a first-class concern of C3 and does not share semantics with RAG.

#### R-400-051

```yaml
id: R-400-051
version: 1
status: draft
category: functional
```

When a pipeline run (C4) needs conversational context beyond what C3 holds, it SHALL NOT push conversation turns into C7's indexes automatically. An explicit user-initiated action ("remember this conversation") is required to promote a conversation summary to C7 storage — this action is deferred to v2.

**Rationale.** Auto-indexing conversations creates strong privacy and retention obligations that exceed the v1 scope.

---

### 4.7 Refresh & invalidation (D-010 strategy α)

#### R-400-060

```yaml
id: R-400-060
version: 1
status: draft
category: functional
```

C7 SHALL expose an admin endpoint `POST /api/v1/memory/projects/{project_id}/refresh` that triggers re-embedding of everything in `external_sources` for the project. Requirements entities are covered by event-driven refresh (R-400-030) and do not need an explicit trigger.

**Rationale.** Per D-010 strategy α: periodic recomputation, not online learning. An admin-initiated refresh handles model upgrades and corpus migrations.

#### R-400-061

```yaml
id: R-400-061
version: 1
status: draft
category: functional
```

Refresh SHALL be an asynchronous job (same pattern as C5 reindex) with `GET /api/v1/memory/refresh/{job_id}` for status polling. In v1 it is admin-only; per-tenant scheduling (cron) is deferred to v2.

**Rationale.** Mirrors C5's reindex job model (R-300-070) for operator familiarity.

---

### 4.8 RBAC & quotas

#### R-400-070

```yaml
id: R-400-070
version: 1
status: draft
category: security
```

Every request to C7 SHALL carry identity via the Traefik forward-auth headers (`X-User-Id`, `X-User-Roles`, `X-Tenant-Id`). Per-project roles from E-100-002 apply:

- `project_viewer` / `project_editor` / `project_owner` can retrieve from the project's indexes.
- `project_editor` / `project_owner` / `admin` can upload new sources (via C12).
- `project_owner` / `admin` can trigger refresh or delete sources.

**Rationale.** Consistent with the rest of the platform's RBAC model.

#### R-400-071

```yaml
id: R-400-071
version: 1
status: draft
category: security
```

Cross-tenant retrieval is PROHIBITED. A query scoped to a project SHALL only consider embeddings whose `tenant_id` matches the caller's tenant; mismatch SHALL return HTTP 404 (not 403) to avoid leaking tenant existence.

**Rationale.** Privacy-first default for multi-tenant deployments.

---

## 5. Non-Functional Requirements

### 5.1 Performance

#### R-400-100

```yaml
id: R-400-100
version: 1
status: draft
category: nfr
```

Embedding a single 512-token chunk with the baseline sentence-transformers model SHALL take under 100 ms p95 on a CPU-only baseline deployment footprint (R-100-106). GPU acceleration is optional and not assumed.

**Rationale.** Baseline model choice balances quality and CPU inference speed. GPU is a deploy-time optimisation, not a v1 assumption.

#### R-400-101

```yaml
id: R-400-101
version: 1
status: draft
category: nfr
```

Ingestion throughput SHALL be at least 100 chunks per minute sustained on the baseline footprint (measured end-to-end from `ingestion.source.uploaded` to `ingestion.source.indexed`).

**Rationale.** Caps the upload-to-available window at reasonable minutes for typical-size documents. Lower throughput is a capacity-tuning concern, not a v1 correctness concern.

### 5.2 Consistency

#### R-400-110

```yaml
id: R-400-110
version: 1
status: draft
category: nfr
```

Requirements-entity embeddings SHALL be consistent with the entity state within 30 seconds of a C5 write (event-driven refresh). External-source embeddings SHALL be consistent with the source within the end-to-end ingestion window (R-400-101).

**Rationale.** Bounds on "how stale can a retrieved snippet be" — critical for agents that decide based on the result.

### 5.3 Observability

#### R-400-120

```yaml
id: R-400-120
version: 1
status: draft
category: nfr
```

C7 SHALL emit Prometheus metrics covering at minimum: embedding latency per model, ingestion queue depth, retrieval latency percentiles per index, per-project chunk count, refresh job duration, parse failure rate per MIME type.

**Rationale.** Surfaces the operational fault lines most likely to degrade retrieval quality.

---

## 6. Interfaces & Contracts

### 6.1 REST API

Public surface (rooted under `/api/v1/memory/` behind C1 forward-auth):

```
POST   /api/v1/memory/retrieve            — federated retrieval
GET    /api/v1/memory/projects/{pid}/sources           — list uploaded sources
GET    /api/v1/memory/projects/{pid}/sources/{sid}     — single source metadata
DELETE /api/v1/memory/projects/{pid}/sources/{sid}     — remove a source + its chunks
GET    /api/v1/memory/projects/{pid}/quota             — storage quota
POST   /api/v1/memory/projects/{pid}/refresh           — trigger refresh (admin)
GET    /api/v1/memory/refresh/{job_id}                 — job status
GET    /api/v1/memory/health                           — liveness + model availability
```

The source-upload endpoint itself lives on C12 (`POST /uploads/...`) and forwards to C7 via NATS; C7 does not expose an HTTP upload surface directly in v1.

Full OpenAPI schema in E-400-005.

### 6.2 NATS subjects

```
ingestion.source.uploaded         (published by C12, consumed by C7)
ingestion.source.parsed           (published by C7)
ingestion.source.indexed          (published by C7)
ingestion.source.failed           (published by C7 on parse/embed failure)
requirements.<pid>.entity.created (consumed by C7 — triggers re-embed)
requirements.<pid>.entity.updated (consumed by C7)
requirements.<pid>.entity.deprecated (consumed by C7 — flags as deprecated)
memory.retrieval.completed        (published by C7 after every retrieve)
memory.refresh.started|completed|failed
```

Event envelope follows E-300-003 (reused); per-event payload in E-400-004.

### 6.3 Contract-critical entities

#### E-400-001: `EmbeddingProvider` protocol

```yaml
id: E-400-001
version: 1
status: draft
category: architecture
```

Python `Protocol` every embedding adapter satisfies. Two methods:

```python
async def embed_one(self, text: str) -> list[float]: ...
async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

Plus metadata:

```python
model_id: str         # e.g. "sentence-transformers/all-mpnet-base-v2"
dimension: int        # vector length this adapter produces
max_input_tokens: int # largest single input the adapter accepts
```

Concrete adapters shipped in v1: `DeterministicHashEmbedder` (test baseline, zero deps, reproducible) and `SentenceTransformersEmbedder` (production baseline, requires `sentence-transformers` at deploy time — optional extra in `pyproject.toml`).

#### E-400-002: `memory_chunks` collection schema

```yaml
id: E-400-002
version: 1
status: draft
category: architecture
```

```json
{
  "_key": "<tenant_id>:<project_id>:<chunk_id>",
  "tenant_id": "<tenant-id>",
  "project_id": "<project-id>",
  "index": "requirements | external_sources",
  "source_id": "<source-id-or-null>",
  "entity_id": "<entity-id-or-null>",
  "entity_version": 3,
  "chunk_index": 0,
  "content": "<verbatim text>",
  "content_hash": "sha256:...",
  "vector": [0.01, 0.42, ...],
  "model_id": "sentence-transformers/all-mpnet-base-v2",
  "model_dim": 768,
  "created_at": "2026-04-23T12:00:00Z",
  "status": "active | deprecated | superseded",
  "metadata": { "category": "functional", "domain": "code", ... }
}
```

Indexes:
- Persistent on `(tenant_id, project_id, index)` for retrieval scoping.
- Persistent on `entity_id` to support version co-existence lookup.
- Persistent on `source_id` for source deletion cascades.

#### E-400-003: `memory_sources` collection schema

```yaml
id: E-400-003
version: 1
status: draft
category: architecture
```

```json
{
  "_key": "<tenant_id>:<project_id>:<source_id>",
  "tenant_id": "<tenant-id>",
  "project_id": "<project-id>",
  "source_id": "<source-id>",
  "minio_raw_path": "sources/<pid>/<sid>/raw.pdf",
  "minio_parsed_path": "sources/<pid>/<sid>/parsed.txt",
  "minio_chunks_path": "sources/<pid>/<sid>/chunks.json",
  "mime_type": "application/pdf",
  "size_bytes": 423412,
  "uploaded_by": "<user-id>",
  "uploaded_at": "2026-04-23T12:00:00Z",
  "parse_status": "pending | parsed | failed",
  "parse_error": null,
  "chunk_count": 42,
  "model_id": "sentence-transformers/all-mpnet-base-v2"
}
```

#### E-400-004: NATS event payloads

```yaml
id: E-400-004
version: 1
status: draft
category: architecture
```

Envelope per E-300-003. Payload examples:

- `ingestion.source.uploaded`: `{"source_id": "...", "project_id": "...", "mime_type": "application/pdf", "size_bytes": 423412}`
- `ingestion.source.indexed`: `{"source_id": "...", "chunk_count": 42, "model_id": "..."}`
- `memory.retrieval.completed`: `{"retrieval_id": "...", "top_k": 10, "indexes": ["requirements"], "chunk_ids": ["..."], "latency_ms": 87}`

#### E-400-005: REST API OpenAPI reference

```yaml
id: E-400-005
version: 1
status: draft
category: architecture
```

Canonical path: `api/openapi/memory-service-v1.yaml`. Every endpoint in §6.1 SHALL be declared with request/response schemas, auth requirements (bearer JWT), and error examples.

---

## 7. Open Questions

| ID | Question | Owning decision | Target resolution |
|---|---|---|---|
| Q-400-001 | PDF parser library: `pypdf`, `pdfplumber`, `docling`, PyMuPDF? | D-013 | v1 (baseline: `pypdf` for text-only PDFs; upgrade to `docling` when tables/images are needed) |
| Q-400-002 | OCR library: Tesseract, PaddleOCR, cloud API? | D-013 | v1 (baseline: Tesseract via `pytesseract`, CPU-only; feature flag `OCR_ENABLED`) |
| Q-400-003 | Baseline sentence-transformers model choice — `all-mpnet-base-v2` (768d, general-purpose) vs `bge-small-en-v1.5` (384d, faster) vs `bge-large-en-v1.5` (1024d, higher quality)? | D-010 | v1 (baseline: `all-mpnet-base-v2`, revisit after first real-world corpus measurements) |
| Q-400-004 | ArangoDB native vector index: when it becomes non-experimental, drop the AQL-based cosine path? | D-002, D-010 | v2 (triggered by ArangoDB 3.13+ stability announcement) |
| Q-400-005 | Chunk overlap strategy — fixed token count vs sentence-aware? | D-010 | v2 (structure-aware chunking per format when AyExtractor patterns land) |
| Q-400-006 | Graph-propagation re-ranking (D-010's "approach (α)"): which signals propagate through `memory_links` / `req_relations`? | D-010 | v2 (requires link construction at ingest — deferred) |
| Q-400-007 | Auto-indexing of conversation summaries into C7 — which privacy controls? Opt-in per project? Retention per tenant? | — | v2 (R-400-051 defers the feature; privacy review gates the implementation) |
| Q-400-008 | Refresh cadence — fully admin-triggered vs per-tenant cron? | D-010 | v2 (admin-only in v1; cron arrives with Redis-backed scheduler) |
| Q-400-009 | Source deletion semantics — hard delete vs soft delete with 30-day grace? | — | v1 (baseline: hard delete on user action; chunks and source are removed from indexes immediately, MinIO `_deleted/` holds raw for 30 days) |
| Q-400-010 | Multi-language embedding — per-project model selection? | D-009 | v2 (corpus is English-by-default; multi-language RAG deferred) |
| Q-400-011 | Eval harness for retrieval quality — golden query set per project? | D-010 | v2 (evaluation infrastructure lives with the v2 eval harness of 800-SPEC) |

---

## 8. Appendices

### 8.1 ArangoDB collections (indicative summary)

| Collection | Owner | Kind | Purpose |
|---|---|---|---|
| `memory_chunks` | C7 | document | Embedded text with provenance (external sources AND requirements entities). |
| `memory_sources` | C7 | document | Metadata about uploaded external documents. |
| `memory_links` | C7 | edge (`memory_chunks` → `req_entities`) | "This chunk cites this requirement" links, built opportunistically during ingestion or by a later backfill pass. |

Indexes:
- `memory_chunks`: persistent on `(tenant_id, project_id, index)`, on `entity_id`, on `source_id`.
- `memory_sources`: persistent on `(tenant_id, project_id)`.
- `memory_links`: edge indexes on `_from` and `_to`.

### 8.2 Cosine similarity AQL (indicative)

Cosine of two float arrays of equal length:

```aql
FUNCTION UTILS::COSINE(a, b) = (
  SUM(FOR i IN 0..LENGTH(a)-1 RETURN a[i] * b[i])
  / (SQRT(SUM(FOR x IN a RETURN x*x)) * SQRT(SUM(FOR y IN b RETURN y*y)))
)
```

Registered once at ensure-collections time; invoked by the retrieval query:

```aql
FOR c IN memory_chunks
  FILTER c.tenant_id == @tenant AND c.project_id == @project
     AND c.index IN @indexes AND c.model_id == @model_id
     AND (c.status == 'active' OR @include_deprecated)
  LET score = UTILS::COSINE(c.vector, @query_vector) * @weights[c.index]
  SORT score DESC
  LIMIT @top_k
  RETURN { chunk_id: c._key, score, content: c.content, metadata: c.metadata }
```

Beyond 50 000 chunks per scope, this query degrades; filters (source_id, category, etc.) are expected to narrow the scan before the SORT.

---

**End of 400-SPEC-MEMORY-RAG.md v2 (first populated draft).**
