// =============================================================================
// File: page.tsx
// Version: 7
// Path: ay_platform_ui/app/(protected)/projects/[pid]/conversations/[cid]/page.tsx
// Description: Chat view — message history + SSE-streamed assistant
//              replies. The composer at the bottom POSTs to C3's
//              `/messages` endpoint ; chunks land via the streaming
//              ApiClient method and are appended to a transient
//              "live" message. When the stream terminates ([DONE]),
//              the message is persisted and the conversation refetched
//              so the server-side id/timestamp take over.
//
//              v7 : the pipeline timeline now persists server-side
//              and is read back from `Message.stages` on navigation /
//              reload. Earlier the chip + panel only existed for the
//              freshly-streamed turn (live SSE state) and vanished
//              when the operator clicked another conversation and
//              came back.
//
//              v6 : two layout fixes on top of the v5 chip refactor.
//              (1) The trigram, pipeline chip and bubble are now on
//              the SAME LINE in the collapsed state (was two-stacked
//              before — pipeline above bubble — wasting vertical
//              space). Expanding the chip switches the row to the
//              previous stacked layout so the full timeline gets the
//              full row width.  (2) The streaming "thinking" dots are
//              folded directly into the live-row bubble instead of
//              being a separate `ThinkingBubble` element that
//              duplicated the live row for the first second of every
//              turn.
//
//              v5 : kills the 1-frame duplicate flash where both the
//              live row and the freshly-fetched server assistant row
//              briefly co-existed — a snapshot of the pre-send
//              message count gates the live row out as soon as the
//              server pair has landed. The pipeline timeline also
//              collapses to a tiny "+ 12.4s" chip when idle (full
//              panel still pops via click) instead of the previous
//              full-width header row.
//
//              v4 : the chat page is now responsible for naming a
//              freshly-created conversation. The conversations list
//              page creates it with a placeholder title ; on the
//              FIRST user message the chat PATCHes the conversation
//              with a derived title (first 60 chars of the message,
//              trimmed at a word boundary). Avoids the earlier UX
//              trap where the operator typed their question into
//              the "title" prompt and landed on an empty composer.
//              Also formats pipeline durations in seconds (e.g.
//              `1.4 s`) rather than raw milliseconds so the operator
//              gets an immediately interpretable timing.
//
//              v3 : user bubbles are right-aligned (avatar on the
//              right, tinted with the per-user `user_color` from C2
//              prefs), assistant bubbles stay left-aligned with the
//              neutral brand palette. The live `event: stage` SSE
//              stream renders next to the assistant avatar — visible
//              while running, collapsed behind a `+` toggle after
//              `[DONE]` so it does not consume vertical real estate
//              once the reply is on screen.
//
//              v2 : fetches user preferences (effective user_prompt)
//              and the active project (effective project system_prompt)
//              at mount, forwards both on every chat message so C3 can
//              prepend them ahead of the RAG context.
// =============================================================================

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Avatar, ThinkingDots } from "@/components/avatar";
import { ApiClient, ApiError } from "@/lib/apiClient";
import { fullNameForTooltip, getEffectiveTrigram } from "@/lib/preferences";
import type { Conversation, Message, MessageRole, StageEvent } from "@/lib/types";

import { useAuth } from "../../../../../auth-provider";
import { useConfigState } from "../../../../../providers";

/** Placeholder title set by the conversations list page when the
 *  operator clicks "+ New conversation". The chat page replaces it on
 *  the first user message — see `deriveTitleFromMessage` below. Must
 *  stay in sync with the constant of the same name in the list page. */
const DEFAULT_NEW_CONVERSATION_TITLE = "New conversation";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; conversation: Conversation; messages: Message[] }
  | { status: "not-found" }
  | { status: "error"; message: string };

/** Local rendering model — server messages + an optional live (in-flight) one. */
interface DisplayMessage {
  role: MessageRole;
  content: string;
  /** Stable key for React. Server messages use their id ; the live
   *  streamed one uses "live". */
  key: string;
  /** Stage timeline attached to a live assistant message. Reset on
   *  each new send ; server-restored messages don't carry stages. */
  stages?: StageEvent[];
  /** True while the SSE is open ; used to keep the timeline pinned
   *  on the message and not collapsed prematurely. */
  inFlight?: boolean;
}

export default function ChatPage() {
  const params = useParams<{ pid: string; cid: string }>();
  const projectId = decodeURIComponent(params.pid);
  const conversationId = decodeURIComponent(params.cid);
  const configState = useConfigState();
  const { state: authState } = useAuth();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [composer, setComposer] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [liveAssistant, setLiveAssistant] = useState<string | null>(null);
  const [liveStages, setLiveStages] = useState<StageEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Behavioural prompts resolved by C2 — fetched once on mount and
  // forwarded on every chat message. `null` means "not yet loaded" ;
  // empty string means "loaded but no effective text" (skip).
  const [userPrompt, setUserPrompt] = useState<string | null>(null);
  const [projectPrompt, setProjectPrompt] = useState<string | null>(null);
  const [userColor, setUserColor] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  // Snapshot of `state.messages.length` taken just BEFORE the
  // optimistic user row is pushed. We use it to suppress the live
  // assistant row in the brief window between `loadAll()` returning
  // (state has the server-persisted user + assistant ; messages.length
  // == base + 2) and `setLiveAssistant(null)` clearing the transient
  // row — without this guard, the assistant reply rendered twice for
  // a frame, visually flashing.
  const messageCountAtSendRef = useRef(0);

  // User identity → trigram + tooltip name. Memoised so toggling
  // chat state doesn't reread localStorage on every render.
  const userIdentity = useMemo(() => {
    if (authState.status !== "authenticated") {
      return { trigram: "USR", fullName: "Anonymous" };
    }
    return {
      trigram: getEffectiveTrigram(authState.claims),
      fullName: fullNameForTooltip(authState.claims),
    };
  }, [authState]);

  // Brand name for the assistant trigram + tooltip — pulled from
  // /ux/config so a deployment re-branding flows through to chat.
  const assistantIdentity = useMemo(() => {
    if (configState.status !== "ready") {
      return { trigram: "AYW", fullName: "AyWizz assistant" };
    }
    const short = configState.config.ux.brand.short_name;
    const tri =
      short
        .replace(/[^A-Za-z0-9]/g, "")
        .slice(0, 3)
        .toUpperCase() || "AYW";
    return {
      trigram: tri,
      fullName: `${configState.config.ux.brand.name} assistant`,
    };
  }, [configState]);

  const apiClient = useMemo(() => {
    if (configState.status !== "ready") return null;
    return new ApiClient(configState.config);
  }, [configState]);

  const loadAll = useCallback(async (): Promise<void> => {
    if (!apiClient) return;
    try {
      const conv = await apiClient.getConversation(conversationId);
      const msgs = await apiClient.listMessages(conversationId);
      setState({
        status: "ready",
        conversation: conv,
        messages: msgs.messages,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setState({ status: "not-found" });
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      setState({ status: "error", message });
    }
  }, [apiClient, conversationId]);

  useEffect(() => {
    let cancelled = false;
    if (apiClient && !cancelled) loadAll();
    return () => {
      cancelled = true;
    };
  }, [apiClient, loadAll]);

  // Resolve the effective behavioural prompts + user colour once.
  // Either call may fail (auth-mode='none' deployments don't expose
  // user prefs) — we swallow errors and fall back to defaults rather
  // than blocking chat.
  useEffect(() => {
    if (!apiClient) return;
    let cancelled = false;
    apiClient
      .getUserPreferences()
      .then((p) => {
        if (cancelled) return;
        setUserPrompt(p.user_prompt);
        setUserColor(p.user_color);
      })
      .catch(() => {
        if (!cancelled) {
          setUserPrompt("");
          setUserColor(null);
        }
      });
    apiClient
      .getProject(projectId)
      .then((p) => {
        if (!cancelled) setProjectPrompt(p.system_prompt);
      })
      .catch(() => {
        if (!cancelled) setProjectPrompt("");
      });
    return () => {
      cancelled = true;
    };
  }, [apiClient, projectId]);

  // Auto-scroll to bottom whenever the message list grows OR the
  // live-streamed chunk advances. Biome can't see the deps are read
  // (we rely on them only as triggers) ; the suppression is on
  // purpose.
  // biome-ignore lint/correctness/useExhaustiveDependencies: state + liveAssistant + liveStages are scroll triggers
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [state, liveAssistant, liveStages]);

  async function onSend(e: FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    if (!apiClient || !composer.trim() || streaming) return;
    if (state.status !== "ready") return;

    const userText = composer.trim();
    setComposer("");
    setError(null);
    // Snapshot the message count BEFORE the optimistic add — used by
    // the render path to know when the server-persisted (user +
    // assistant) pair has arrived and the live row should be hidden.
    messageCountAtSendRef.current = state.messages.length;

    // First-message auto-rename : if the conversation is still on its
    // placeholder title (set by the conversations list page when the
    // user clicked "+ New conversation"), derive a meaningful title
    // from the first user message and persist it. Fires AFTER the
    // optimistic update but BEFORE the SSE stream — the rename is
    // best-effort and never blocks the chat (errors swallowed).
    const isPlaceholderTitle = state.conversation.title === DEFAULT_NEW_CONVERSATION_TITLE;
    if (isPlaceholderTitle) {
      const derived = deriveTitleFromMessage(userText);
      void apiClient
        .updateConversation(conversationId, { title: derived })
        .then((updated) => {
          setState((prev) => {
            if (prev.status !== "ready") return prev;
            return { ...prev, conversation: updated };
          });
        })
        .catch(() => {
          // Rename failure is benign — the conversation keeps its
          // placeholder title and the chat continues. No UX surface.
        });
    }

    // Optimistically append the user message to the visible list so
    // it shows up immediately. The server response will replace it
    // when we re-fetch after the stream ends.
    const optimisticUser: Message = {
      id: `optimistic-${Date.now()}`,
      conversation_id: conversationId,
      role: "user",
      content: userText,
      timestamp: new Date().toISOString(),
    };
    setState({
      ...state,
      messages: [...state.messages, optimisticUser],
    });

    setStreaming(true);
    setLiveAssistant("");
    setLiveStages([]);
    try {
      await apiClient.sendMessageStream(
        conversationId,
        userText,
        (chunk) => {
          setLiveAssistant((prev) => (prev ?? "") + chunk);
        },
        {
          userPrompt,
          projectPrompt,
          onStage: (stage) => {
            // Merge same-name running/done events into a single row :
            // when a `done` event arrives for a phase already shown
            // as `running`, replace that entry rather than appending.
            // Net visual effect : one row per phase that updates in
            // place with the final duration + stats.
            setLiveStages((prev) => {
              const idx = prev.findIndex((s) => s.name === stage.name && s.status === "running");
              if (idx === -1) return [...prev, stage];
              const next = prev.slice();
              next[idx] = stage;
              return next;
            });
          },
        },
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`Send failed: ${message}`);
    } finally {
      setStreaming(false);
      // Keep liveAssistant + liveStages visible briefly so the
      // collapsible timeline survives the re-fetch ; loadAll will
      // overwrite the optimistic messages, then we clear the live
      // state.
      await loadAll();
      setLiveAssistant(null);
      // Stages stay on screen but the `inFlight=false` flag flips
      // so the bubble renders with the `+` collapser instead of the
      // live timeline. We DO NOT clear `liveStages` here so the
      // user can inspect what happened ; navigating away resets
      // the component and clears them naturally.
    }
  }

  if (state.status === "loading") {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <p className="text-neutral-500">Loading conversation…</p>
      </main>
    );
  }

  if (state.status === "not-found") {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h2 className="text-2xl font-semibold">Conversation not found</h2>
        <Link
          href={`/projects/${encodeURIComponent(projectId)}/conversations`}
          className="mt-6 inline-block rounded-md border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
        >
          ← Back to conversations
        </Link>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <p className="text-red-700" role="alert">
          Failed to load: {state.message}
        </p>
      </main>
    );
  }

  // Build the visible row list. The most recent assistant row that
  // *exists in state.messages* receives the captured stage timeline
  // (if we have one). The live in-flight row receives the growing
  // tokens. After [DONE] but before loadAll resolves, both can
  // overlap briefly ; once loadAll finishes we drop the live row
  // (via setLiveAssistant(null)) and the timeline naturally moves
  // onto the persisted assistant message.
  const lastAssistantIdx = (() => {
    for (let i = state.messages.length - 1; i >= 0; i -= 1) {
      if (state.messages[i].role === "assistant") return i;
    }
    return -1;
  })();

  const display: DisplayMessage[] = state.messages.map((m, idx) => {
    // Stages source precedence : live SSE timeline for the latest
    // assistant row WHEN this is the freshly-streamed turn (not yet
    // refetched from server) ; server-persisted stages otherwise.
    // Server stages survive navigation / refresh ; the live array
    // covers the brief window between [DONE] and `loadAll()` resolving.
    const liveCandidate =
      idx === lastAssistantIdx && liveStages.length > 0 && !streaming ? liveStages : undefined;
    return {
      role: m.role,
      content: m.content,
      key: m.id,
      stages: liveCandidate ?? m.stages ?? undefined,
    };
  });
  // Live (in-flight) assistant row : show ONLY while the server's
  // persisted assistant hasn't landed yet. After `loadAll()` resolves
  // post-[DONE], state.messages contains the server-side user +
  // assistant pair (length jumps by 2 from the pre-send snapshot) and
  // we suppress the live row to avoid a 1-frame duplicate flash.
  const serverAssistantArrived = state.messages.length >= messageCountAtSendRef.current + 2;
  if (liveAssistant !== null && !serverAssistantArrived) {
    display.push({
      role: "assistant",
      content: liveAssistant,
      key: "live",
      stages: liveStages.length > 0 ? liveStages : undefined,
      inFlight: streaming,
    });
  }

  return (
    <main
      className="flex h-[calc(100vh-3.5rem-4rem)] w-full flex-col px-6 py-6"
      data-testid="chat-view"
    >
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <nav className="text-xs text-neutral-500" aria-label="Breadcrumb">
            <Link
              href={`/projects/${encodeURIComponent(projectId)}/conversations`}
              className="hover:underline"
            >
              ← Conversations
            </Link>
          </nav>
          <h2 className="mt-1 text-xl font-semibold tracking-tight">{state.conversation.title}</h2>
        </div>
        <span className="text-xs text-neutral-500">
          {state.conversation.message_count} message
          {state.conversation.message_count === 1 ? "" : "s"}
        </span>
      </header>

      <section
        className="mt-4 flex-1 overflow-y-auto rounded-lg border border-neutral-200 bg-neutral-50 p-4"
        data-testid="messages-pane"
      >
        {display.length === 0 ? (
          <p className="text-sm text-neutral-500">
            No messages yet. Ask anything below — replies are augmented with this project's RAG
            sources.
          </p>
        ) : (
          <ul className="space-y-3">
            {display.map((m) => (
              <li key={m.key}>
                <MessageBubble
                  role={m.role}
                  content={m.content}
                  user={userIdentity}
                  assistant={assistantIdentity}
                  userColor={userColor}
                  stages={m.stages}
                  inFlight={m.inFlight}
                />
              </li>
            ))}
          </ul>
        )}
        <div ref={bottomRef} />
      </section>

      {error ? (
        <p className="mt-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}

      <form onSubmit={onSend} className="mt-3 flex items-end gap-2" data-testid="composer">
        <textarea
          value={composer}
          onChange={(e) => {
            setComposer(e.target.value);
          }}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter inserts a newline (standard
            // chat UX). Cmd/Ctrl+Enter kept as a secondary trigger
            // for keyboard-power users used to other apps.
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              (e.currentTarget.form as HTMLFormElement | null)?.requestSubmit();
            }
          }}
          rows={2}
          placeholder="Ask a question (Enter to send, Shift+Enter for a new line)…"
          className="flex-1 resize-y rounded-md border border-neutral-300 px-3 py-2 text-sm focus:outline-none focus:ring-2"
          disabled={streaming}
          data-testid="composer-input"
        />
        <button
          type="submit"
          disabled={streaming || !composer.trim()}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          data-testid="composer-send"
        >
          {streaming ? "Streaming…" : "Send"}
        </button>
      </form>
    </main>
  );
}

interface Identity {
  trigram: string;
  fullName: string;
}

function MessageBubble({
  role,
  content,
  user,
  assistant,
  userColor,
  stages,
  inFlight,
}: {
  role: MessageRole;
  content: string;
  user: Identity;
  assistant: Identity;
  userColor: string | null;
  stages?: StageEvent[];
  inFlight?: boolean;
}) {
  const isUser = role === "user";
  const id = isUser ? user : assistant;
  // Narrow the optional `stages` prop to a concrete array — TypeScript
  // can't carry the narrowing through JSX, so capturing it in a local
  // typed `const` keeps the chip + full-panel components type-safe
  // without the `stages!` non-null assertion biome flags as forbidden.
  const stageList: StageEvent[] = !isUser && stages ? stages : [];
  const hasStages = stageList.length > 0;

  // Pipeline open/closed state lives at the message-row level so we
  // can swap between two layouts based on it :
  //   - `pipelineOpen=false` (or no stages) : trigram + chip + bubble
  //     all on a SINGLE LINE, minimising vertical real estate once
  //     the reply is on screen.
  //   - `pipelineOpen=true` : the full timeline panel renders ABOVE
  //     the bubble (avatar still on its own column to the left), like
  //     the v3 layout, so the operator can read each phase + stats.
  // Streaming forces `open=true` so the operator sees live progress
  // without an extra click ; once the stream ends, the panel auto-
  // collapses but stays one click away via the chip.
  const [pipelineOpen, setPipelineOpen] = useState(inFlight === true);
  useEffect(() => {
    if (inFlight === true) setPipelineOpen(true);
    else if (inFlight === false) setPipelineOpen(false);
  }, [inFlight]);

  // Per-user bubble tint — inline RGB string built from the hex so
  // Tailwind's JIT doesn't need to know about user-supplied colours.
  const userBubbleStyle: React.CSSProperties | undefined =
    isUser && userColor && /^#[0-9a-fA-F]{6}$/.test(userColor)
      ? {
          backgroundColor: rgba(userColor, 0.12),
          borderColor: rgba(userColor, 0.35),
          color: shade(userColor, 0.55),
        }
      : undefined;
  const bubbleClasses = [
    "rounded-lg border px-4 py-2 text-sm whitespace-pre-wrap",
    isUser
      ? userColor
        ? ""
        : "border-blue-200 bg-blue-50 text-blue-900"
      : "border-neutral-200 bg-white text-neutral-900",
  ].join(" ");
  // Empty assistant bubble while inFlight → render the animated
  // ThinkingDots (used to be a standalone bubble — folded in here
  // so a streaming turn shows ONE row instead of two duplicates).
  const showThinkingDots = !isUser && inFlight === true && (content === "" || content == null);
  const bubbleContent = content ? content : isUser ? "" : showThinkingDots ? <ThinkingDots /> : "…";

  // Inline layout (one line) — used when the pipeline is collapsed
  // OR when there are no stages at all (most of the time on the user
  // side or on legacy assistant rows fetched from the server). The
  // chip sits between the avatar and the bubble ; clicking it expands
  // to the stacked layout below.
  if (!pipelineOpen) {
    return (
      <div
        className={["flex items-center gap-3", isUser ? "flex-row-reverse" : "flex-row"].join(" ")}
        data-testid={`message-${role}`}
      >
        <Avatar
          trigram={id.trigram}
          fullName={id.fullName}
          variant={isUser ? "user" : "assistant"}
          color={isUser ? userColor : null}
        />
        {hasStages ? (
          <PipelineChip stages={stageList} onExpand={() => setPipelineOpen(true)} />
        ) : null}
        <div className={`min-w-0 flex-1 ${bubbleClasses}`} style={userBubbleStyle}>
          {bubbleContent}
        </div>
      </div>
    );
  }

  // Stacked layout (two lines) — used when the pipeline panel is
  // expanded (manually, or automatically while streaming). The full
  // timeline takes the row's vertical space ; bubble follows below.
  return (
    <div
      className={["flex items-start gap-3", isUser ? "flex-row-reverse" : "flex-row"].join(" ")}
      data-testid={`message-${role}`}
    >
      <Avatar
        trigram={id.trigram}
        fullName={id.fullName}
        variant={isUser ? "user" : "assistant"}
        color={isUser ? userColor : null}
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        {hasStages ? (
          <StageTimelineFull stages={stageList} onCollapse={() => setPipelineOpen(false)} />
        ) : null}
        <div className={bubbleClasses} style={userBubbleStyle}>
          {bubbleContent}
        </div>
      </div>
    </div>
  );
}

/** Compact inline pill — collapsed pipeline state. Click to expand
 *  via the parent's `onExpand` callback (open/closed state lives in
 *  MessageBubble so we can switch the entire row layout between
 *  single-line and stacked, not just the panel widget itself). */
function PipelineChip({ stages, onExpand }: { stages: StageEvent[]; onExpand: () => void }) {
  const totalMs = stages.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0);
  const summary = totalMs > 0 ? `${formatDuration(totalMs)} total` : "in progress";
  return (
    <button
      type="button"
      onClick={onExpand}
      className="inline-flex shrink-0 items-center gap-1 rounded-full border border-neutral-200 bg-neutral-100 px-2 py-0.5 font-mono text-[10px] text-neutral-600 hover:bg-neutral-200"
      aria-expanded={false}
      data-testid="stage-chip"
      title={`Pipeline · ${summary}`}
    >
      <StageDot status={totalMs > 0 ? "done" : "running"} />
      <span>+ {totalMs > 0 ? formatDuration(totalMs) : "…"}</span>
    </button>
  );
}

/** Full expanded panel — header with collapse button + one row per
 *  pipeline phase with duration and optional stats. Same look as the
 *  v3 panel ; the open/closed state is owned by the parent now. */
function StageTimelineFull({
  stages,
  onCollapse,
}: {
  stages: StageEvent[];
  onCollapse: () => void;
}) {
  const totalMs = stages.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0);
  const summary = totalMs > 0 ? `${formatDuration(totalMs)} total` : "in progress";
  return (
    <div
      className="w-full rounded-md border border-neutral-200 bg-neutral-100/60 text-xs"
      data-testid="stage-timeline"
    >
      <button
        type="button"
        onClick={onCollapse}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-neutral-700 hover:bg-neutral-200/60"
        aria-expanded={true}
        data-testid="stage-toggle"
      >
        <span className="font-mono text-[11px] uppercase tracking-wide text-neutral-500">
          − pipeline
        </span>
        <span className="truncate text-[11px] text-neutral-500">{summary}</span>
      </button>
      <ul className="divide-y divide-neutral-200/60 px-2.5 pb-1.5 pt-0.5">
        {stages.map((s, i) => (
          <li
            // biome-ignore lint/suspicious/noArrayIndexKey: stage list is append-or-replace and order is stable
            key={`${s.name}-${i}`}
            className="flex items-center justify-between gap-2 py-1"
            data-testid={`stage-${s.name}`}
          >
            <span className="flex items-center gap-2">
              <StageDot status={s.status} />
              <span className="text-neutral-800">{s.label}</span>
            </span>
            <span className="font-mono text-[10px] text-neutral-500">
              {s.duration_ms != null ? formatDuration(s.duration_ms) : "…"}
              {s.stats ? ` · ${formatStats(s.stats)}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
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

/** Render a stage's stats dict as a one-line key=value summary.
 *  Trims to the first two entries to keep the line short ; the full
 *  payload is still available via the React devtools / network tab
 *  for debugging. */
/** Render a millisecond duration as a human-readable string. Sub-
 *  second values display 3 decimals (e.g. `0.029 s` for 29 ms) so a
 *  fast retrieval doesn't appear as a meaningless `0 s` ; durations
 *  of a second or more use 1 decimal (e.g. `1.4 s`). Pure formatting
 *  helper — the backend keeps emitting raw ms in the SSE payload. */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${(ms / 1000).toFixed(3)} s`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** Derive a conversation title from the user's first message. Trims
 *  whitespace, collapses inner runs of whitespace, and clips to 60
 *  characters at a word boundary (with an ellipsis when truncated).
 *  Falls back to the placeholder when the message yields nothing
 *  printable so we never persist an empty title. */
function deriveTitleFromMessage(message: string): string {
  const cleaned = message.trim().replace(/\s+/g, " ");
  if (cleaned.length === 0) return DEFAULT_NEW_CONVERSATION_TITLE;
  const MAX = 60;
  if (cleaned.length <= MAX) return cleaned;
  // Truncate at the last word boundary within the budget so we don't
  // chop mid-word. If no whitespace under MAX (rare : a long URL or
  // identifier), hard-cut at MAX-1 + ellipsis.
  const window = cleaned.slice(0, MAX);
  const lastSpace = window.lastIndexOf(" ");
  const cut = lastSpace > MAX / 2 ? lastSpace : MAX - 1;
  return `${cleaned.slice(0, cut).trimEnd()}…`;
}

function formatStats(stats: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(stats)) {
    if (parts.length === 2) break;
    parts.push(`${k}=${typeof v === "number" ? v : String(v)}`);
  }
  return parts.join(", ");
}

// ---------------------------------------------------------------------------
// Color helpers — duplicated from `components/avatar.tsx` on purpose
// (avoiding a lib/colors module for two consumers each with their own
// alpha needs).
// ---------------------------------------------------------------------------

function rgba(hex: string, alpha: number): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return hex;
  const n = Number.parseInt(m[1], 16);
  const r = (n >> 16) & 0xff;
  const g = (n >> 8) & 0xff;
  const b = n & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function shade(hex: string, ratio: number): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return hex;
  const n = Number.parseInt(m[1], 16);
  const r = Math.round(((n >> 16) & 0xff) * (1 - ratio));
  const g = Math.round(((n >> 8) & 0xff) * (1 - ratio));
  const b = Math.round((n & 0xff) * (1 - ratio));
  return `rgb(${r}, ${g}, ${b})`;
}
