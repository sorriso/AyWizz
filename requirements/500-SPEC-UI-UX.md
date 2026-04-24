---
document: 500-SPEC-UI-UX
version: 1
path: requirements/500-SPEC-UI-UX.md
language: en
status: draft
derives-from: [D-008]
---

# UI & UX Specification — SCAFFOLD

> **STATUS: SCAFFOLD.** Referenced by `100-SPEC-ARCHITECTURE.md` (C3
> Conversation Service) and `999-SYNTHESIS.md` D-008 (hybrid agent
> exposure with expert mode). Content to be written when the UI layer
> is actively designed. The Next.js reference implementation
> (`simplechat-specification_frontend.md` in `references/`) is the
> starting point for evaluation.

---

## 1. Purpose & Scope

This document will specify:

- The **Conversation Service (C3)** user-facing contracts — REST
  endpoints, SSE streaming, session semantics.
- **Expert mode** panel: consumption of pipeline events from NATS,
  visibility into phase transitions, sub-agent dispatches, and hard
  gate evaluations per `D-008`.
- **External source upload** UX — accepted formats, size limits,
  progress, ingestion job status feedback.
- **Authentication & authorization** UI flows aligned with the three
  auth modes (`none`, `local`, `sso`) exposed by C2 Auth Service.
- **Accessibility** baseline (target: WCAG 2.2 AA, to be confirmed).
- Alignment with prior internal work:
  `references/simplechat-specification_frontend.md` (Next.js 16 + NLUX
  + Tailwind v4) — reuse what applies per `999-SYNTHESIS.md` §3.3.

**Out of scope.**
- Backend conversation management internals (-> `100-SPEC-ARCHITECTURE.md` C3).
- Styling details and design system (operational).

---

## 2. Entities

*To be written.*

No `R-500-*` or `E-500-*` entities are defined yet.

---

*Scaffold end. Content to be authored when UI/UX is tackled.*
