// =============================================================================
// File: inline-log.tsx
// Version: 2
// Path: ay_platform_ui/components/inline-log.tsx
//
// v2 (2026-05-19): `hideOpenLink` — the Working-area surface
// suppresses the tool_call "Open in Working area" deep-link (we're
// already there ; it would self-navigate). Conversations keeps it.
// Description: THE single entry point that formats + displays every
//              inline-activity event (C3 `event: inline`, unified
//              2026-05-19). One `<InlineLog>` takes the unified
//              `InlineEvent[]` (live SSE for the in-flight turn OR
//              `Message.events` persisted/audit on reload — same
//              shape, same render) and dispatches each event to a
//              per-`kind` formatter via the FORMATTERS registry.
//
//              Architectural contract : adding a new inline event
//              kind = adding ONE formatter entry here. No plumbing
//              elsewhere (server emits on the one `event: inline`
//              channel, persists in the one `events` ledger). An
//              unknown kind never disappears — it falls back to a
//              generic row, so the inline log is GUARANTEED to be
//              populated for whatever we add later.
// =============================================================================

"use client";

import Link from "next/link";
import { type ReactNode, useState } from "react";

import type { InlineEvent } from "@/lib/types";

/** Render a millisecond duration human-readably (sub-second → 3
 *  decimals so a fast phase isn't a meaningless `0 s`). */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${(ms / 1000).toFixed(3)} s`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function StageDot({ status }: { status: "running" | "done" }) {
  return (
    <span
      className={[
        "inline-block h-1.5 w-1.5 rounded-full",
        status === "running" ? "bg-blue-500 animate-pulse" : "bg-emerald-500",
      ].join(" ")}
      aria-hidden="true"
    />
  );
}

/** kind="stage" formatter — collapsible pipeline timeline. Same UX as
 *  the former PipelineChip/StageTimelineFull : a compact "+ Xs" chip
 *  that expands to one row per phase. running/done with the same
 *  `name` collapse into a single in-place-updating row. */
function StageFormatter({ events }: { events: InlineEvent[] }): ReactNode {
  const [open, setOpen] = useState(false);
  // Merge running→done by name (done wins, keeps order of first sight).
  const byName = new Map<string, InlineEvent>();
  for (const e of events) {
    const key = e.name ?? e.label;
    const prev = byName.get(key);
    if (!prev || e.status === "done") byName.set(key, e);
  }
  const rows = [...byName.values()];
  const totalMs = rows.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0);
  const allDone = rows.every((s) => s.status === "done");

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex shrink-0 items-center gap-1 rounded-full border border-neutral-200 bg-neutral-100 px-2 py-0.5 font-mono text-[10px] text-neutral-600 hover:bg-neutral-200"
        data-testid="inline-stage-chip"
        title={`Pipeline · ${allDone ? `${formatDuration(totalMs)} total` : "in progress"}`}
      >
        <StageDot status={allDone ? "done" : "running"} />
        <span>+ {totalMs > 0 ? formatDuration(totalMs) : "…"} pipeline</span>
      </button>
    );
  }
  return (
    <div
      className="w-full rounded-md border border-neutral-200 bg-neutral-100/60 text-xs"
      data-testid="inline-stage-timeline"
    >
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-neutral-700 hover:bg-neutral-200/60"
      >
        <span className="font-mono text-[11px] uppercase tracking-wide text-neutral-500">
          − pipeline
        </span>
        <span className="truncate text-[11px] text-neutral-500">
          {allDone ? `${formatDuration(totalMs)} total` : "in progress"}
        </span>
      </button>
      <ul className="divide-y divide-neutral-200/60 px-2.5 pb-1.5 pt-0.5">
        {rows.map((s) => (
          <li
            key={s.name ?? s.label}
            className="flex items-center justify-between gap-2 py-1"
            data-testid={`inline-stage-${s.name ?? "x"}`}
          >
            <span className="flex items-center gap-2">
              <StageDot status={s.status} />
              <span className="text-neutral-800">{s.label}</span>
            </span>
            <span className="font-mono text-[10px] text-neutral-500">
              {s.duration_ms != null ? formatDuration(s.duration_ms) : "…"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** kind="tool_call" formatter — the amber "Document tools" strip.
 *  ⏳ running / ✅ ok / ❌ error, optional result summary, and an
 *  "Open in Working area →" deep-link for create/update with a path
 *  (when the rendering context supplies project + conversation). */
function ToolCallFormatter({
  events,
  projectId,
  conversationId,
  hideOpenLink,
}: {
  events: InlineEvent[];
  projectId?: string;
  conversationId?: string;
  hideOpenLink?: boolean;
}): ReactNode {
  return (
    <div
      className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs"
      data-testid="inline-toolcalls"
    >
      <div className="mb-1 font-medium uppercase tracking-wide text-amber-700">Document tools</div>
      <ul className="space-y-0.5">
        {events.map((tc, i) => {
          const canLink =
            !hideOpenLink &&
            tc.status === "done" &&
            !!tc.path &&
            !!projectId &&
            !!conversationId &&
            (tc.name === "create_document" || tc.name === "update_document");
          return (
            <li
              // Append-only across turns ; round restarts each turn so
              // the index is the correct stable key (order is stable).
              // biome-ignore lint/suspicious/noArrayIndexKey: append-only, stable order
              key={`${i}-${tc.name}-${tc.status}`}
              className="flex items-center gap-1.5 font-mono text-[11px] text-amber-900"
              data-testid={`inline-toolcall-${tc.name}-${tc.status}`}
            >
              <span aria-hidden="true">{tc.status === "running" ? "⏳" : tc.ok ? "✅" : "❌"}</span>
              <span className="font-semibold">{tc.name}</span>
              {tc.status === "done" && tc.summary ? (
                <span className="text-amber-700">— {tc.summary}</span>
              ) : null}
              {canLink ? (
                <Link
                  href={`/projects/${encodeURIComponent(
                    projectId as string,
                  )}/working-area?conv=${encodeURIComponent(
                    conversationId as string,
                  )}&path=${encodeURIComponent(tc.path as string)}`}
                  className="ml-1 rounded border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800 no-underline hover:bg-amber-200"
                  data-testid={`inline-toolcall-open-${tc.name}`}
                >
                  Open in Working area →
                </Link>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Generic fallback — guarantees an unknown future `kind` is still
 *  surfaced (never silently dropped) until a dedicated formatter is
 *  added. This is the safety net behind the "inline is guaranteed
 *  populated" contract. */
function GenericFormatter({ events }: { events: InlineEvent[] }): ReactNode {
  return (
    <div
      className="rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-700"
      data-testid="inline-generic"
    >
      <ul className="space-y-0.5">
        {events.map((e, i) => (
          <li
            // biome-ignore lint/suspicious/noArrayIndexKey: append-only, stable order
            key={`${i}-${e.kind}-${e.status}`}
            className="flex items-center gap-1.5 font-mono text-[11px]"
          >
            <StageDot status={e.status} />
            <span className="font-semibold">{e.kind}</span>
            <span>{e.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Per-kind formatter registry. THE extension point : a new inline
 *  event kind only needs an entry here. */
const FORMATTERS: Record<
  string,
  (args: {
    events: InlineEvent[];
    projectId?: string;
    conversationId?: string;
    hideOpenLink?: boolean;
  }) => ReactNode
> = {
  stage: ({ events }) => <StageFormatter events={events} />,
  tool_call: ({ events, projectId, conversationId, hideOpenLink }) => (
    <ToolCallFormatter
      events={events}
      projectId={projectId}
      conversationId={conversationId}
      hideOpenLink={hideOpenLink}
    />
  ),
};

/** Unified inline-activity renderer. Feed it the live-accumulated
 *  events for an in-flight turn OR a message's persisted
 *  `events` (audit ledger) — identical render either way. Groups by
 *  `kind` (preserving first-seen order) and dispatches each group to
 *  its formatter ; unknown kinds use the generic fallback so nothing
 *  is ever dropped. */
export function InlineLog({
  events,
  projectId,
  conversationId,
  className,
  hideOpenLink,
}: {
  events: InlineEvent[] | null | undefined;
  projectId?: string;
  conversationId?: string;
  className?: string;
  /** Suppress the tool_call "Open in Working area" deep-link. Set
   *  by the Working-area surface itself — we're already there, the
   *  link would be a no-op self-navigation. */
  hideOpenLink?: boolean;
}): ReactNode {
  if (!events || events.length === 0) return null;
  // Group by kind, preserving the order each kind first appears.
  const order: string[] = [];
  const groups = new Map<string, InlineEvent[]>();
  for (const e of events) {
    if (!groups.has(e.kind)) {
      groups.set(e.kind, []);
      order.push(e.kind);
    }
    (groups.get(e.kind) as InlineEvent[]).push(e);
  }
  return (
    <div className={["flex flex-col gap-2", className ?? ""].join(" ")} data-testid="inline-log">
      {order.map((kind) => {
        const groupEvents = groups.get(kind) as InlineEvent[];
        const fmt = FORMATTERS[kind];
        return (
          <div key={kind}>
            {fmt
              ? fmt({ events: groupEvents, projectId, conversationId, hideOpenLink })
              : GenericFormatter({ events: groupEvents })}
          </div>
        );
      })}
    </div>
  );
}
