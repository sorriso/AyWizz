// =============================================================================
// File: page.tsx
// Version: 3
// Path: ay_platform_ui/app/(protected)/projects/[pid]/conversations/page.tsx
// Description: Conversations list (Phase D). One row per conversation
//              the caller owns, scoped to the active project. A single
//              "New conversation" button creates a placeholder
//              conversation and navigates to the chat ; the chat page
//              auto-renames it from the first user message so the
//              operator never types the same thing twice.
//
//              v3 : replaces the upfront title-input form with a
//              one-click button. Rationale : earlier UX asked for a
//              title BEFORE the chat, which operators repeatedly
//              filled with their actual question — then landed on an
//              empty composer and had to retype it. The chat page
//              now owns the title (auto-rename via PATCH on the
//              first send).
//
//              v2 (2026-05-11) : full implementation, replaces the
//              Phase D placeholder.
// =============================================================================

"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { ApiClient, ApiError } from "@/lib/apiClient";
import type { Conversation } from "@/lib/types";

import { useConfigState } from "../../../../providers";

/** Placeholder title shipped with every new conversation. The chat
 *  page rewrites it via PATCH the first time the user sends a
 *  message ; until then it acts as a visible "untitled" marker in
 *  the list. Kept short on purpose — anything longer competes for
 *  attention with the actual conversation contents. */
const DEFAULT_NEW_CONVERSATION_TITLE = "New conversation";

type ListState =
  | { status: "loading" }
  | { status: "ready"; items: Conversation[] }
  | { status: "error"; message: string };

export default function ConversationsListPage() {
  const params = useParams<{ pid: string }>();
  const router = useRouter();
  const projectId = decodeURIComponent(params.pid);
  const configState = useConfigState();
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [refreshCounter, setRefreshCounter] = useState(0);

  const apiClient = useMemo(() => {
    if (configState.status !== "ready") return null;
    return new ApiClient(configState.config);
  }, [configState]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: refresh trigger
  useEffect(() => {
    if (!apiClient) return;
    let cancelled = false;
    setState({ status: "loading" });
    apiClient
      .listConversations()
      .then((resp) => {
        if (cancelled) return;
        // Filter to project-scoped conversations (C3's list endpoint
        // returns ALL conversations owned by the caller across
        // projects ; we narrow client-side).
        const projectItems = resp.conversations.filter((c) => c.project_id === projectId);
        setState({ status: "ready", items: projectItems });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? `HTTP ${err.status}` : String(err);
        setState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [apiClient, projectId, refreshCounter]);

  return (
    <main className="mx-auto max-w-7xl px-6 py-10">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Conversations</h2>
          <p className="mt-1 text-sm text-neutral-500">
            Chat with the platform's RAG-augmented assistant over this project's sources.
          </p>
        </div>
        {state.status === "ready" ? (
          <p className="text-sm text-neutral-500" data-testid="conversations-count">
            {state.items.length} conversation{state.items.length === 1 ? "" : "s"}
          </p>
        ) : null}
      </header>

      <NewConversationCard
        projectId={projectId}
        apiClient={apiClient}
        onCreated={(cid) => {
          router.push(
            `/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(cid)}`,
          );
        }}
      />

      <section className="mt-8">
        {state.status === "loading" ? (
          <p className="text-neutral-500">Loading conversations…</p>
        ) : state.status === "error" ? (
          <p className="text-red-700" role="alert">
            Failed to load: {state.message}
          </p>
        ) : state.items.length === 0 ? (
          <div
            className="rounded-lg border border-dashed border-neutral-300 p-10 text-center"
            data-testid="conversations-empty-state"
          >
            <p className="text-neutral-600">No conversations yet.</p>
            <p className="mt-1 text-sm text-neutral-500">
              Start one above to chat over the project's source corpus.
            </p>
          </div>
        ) : (
          <ConversationsList
            conversations={state.items}
            projectId={projectId}
            apiClient={apiClient}
            onChanged={() => setRefreshCounter((n) => n + 1)}
          />
        )}
      </section>
    </main>
  );
}

function NewConversationCard({
  projectId,
  apiClient,
  onCreated,
}: {
  projectId: string;
  apiClient: ApiClient | null;
  onCreated: (cid: string) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onStart(): Promise<void> {
    if (!apiClient) return;
    setSubmitting(true);
    setError(null);
    try {
      const conv = await apiClient.createConversation({
        title: DEFAULT_NEW_CONVERSATION_TITLE,
        project_id: projectId,
      });
      onCreated(conv.id);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section
      className="mt-6 rounded-lg border border-neutral-200 bg-white p-5"
      data-testid="new-conversation-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
            Start a new conversation
          </h3>
          <p className="mt-1 text-xs text-neutral-500">
            The conversation will be auto-named from your first question.
          </p>
        </div>
        <button
          type="button"
          onClick={onStart}
          disabled={submitting || !apiClient}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          data-testid="new-conversation-submit"
        >
          {submitting ? "Creating…" : "+ New conversation"}
        </button>
      </div>
      {error ? (
        <p className="mt-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function ConversationsList({
  conversations,
  projectId,
  apiClient,
  onChanged,
}: {
  conversations: Conversation[];
  projectId: string;
  apiClient: ApiClient | null;
  onChanged: () => void;
}) {
  return (
    <ul className="space-y-2" data-testid="conversations-list">
      {conversations.map((c) => (
        <ConversationRow
          key={c.id}
          conversation={c}
          projectId={projectId}
          apiClient={apiClient}
          onChanged={onChanged}
        />
      ))}
    </ul>
  );
}

function ConversationRow({
  conversation,
  projectId,
  apiClient,
  onChanged,
}: {
  conversation: Conversation;
  projectId: string;
  apiClient: ApiClient | null;
  onChanged: () => void;
}) {
  const [deleting, setDeleting] = useState(false);

  async function onDelete(e: React.MouseEvent): Promise<void> {
    e.preventDefault();
    e.stopPropagation();
    if (!apiClient) return;
    if (!window.confirm(`Delete conversation "${conversation.title}"?`)) return;
    setDeleting(true);
    try {
      await apiClient.deleteConversation(conversation.id);
      onChanged();
    } catch (err) {
      window.alert(`Delete failed: ${String(err)}`);
      setDeleting(false);
    }
  }

  return (
    <li>
      <Link
        href={`/projects/${encodeURIComponent(projectId)}/conversations/${encodeURIComponent(conversation.id)}`}
        className="flex items-center justify-between gap-3 rounded-md border border-neutral-200 bg-white px-4 py-3 transition-colors hover:bg-neutral-50"
        data-testid={`conversation-row-${conversation.id}`}
      >
        <div className="min-w-0">
          <p className="truncate font-medium text-neutral-900">{conversation.title}</p>
          <p className="mt-0.5 text-xs text-neutral-500">
            {conversation.message_count} message
            {conversation.message_count === 1 ? "" : "s"} ·{" "}
            {new Date(conversation.updated_at).toLocaleString()}
          </p>
        </div>
        <button
          type="button"
          onClick={onDelete}
          disabled={deleting}
          className="rounded-md border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
          data-testid={`conversation-delete-${conversation.id}`}
        >
          {deleting ? "…" : "Delete"}
        </button>
      </Link>
    </li>
  );
}
