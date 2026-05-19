// =============================================================================
// File: page.tsx
// Version: 4
// Path: ay_platform_ui/app/(protected)/projects/[pid]/working-area/page.tsx
//
// v4 (2026-05-19): Increment 3 phase 3a — selected run/doc are
// mirrored into the cross-nav WorkspaceProvider store (restore-once
// on hydration + persist-on-change), so switching tab or refreshing
// returns the operator to the same run/document.
//
// v3 (2026-05-19): layout fit. `h-[calc(100vh-6rem)]` under-budgeted
// the navbar + version footer chrome, so the 3-pane main overflowed
// the viewport and the chat composer's Send button sat below the
// fold (needed a page scroll). Now `flex flex-col h-[calc(100dvh-
// 8rem)]` with the grid as `flex-1 min-h-0` — fills exactly the
// space under the header, Send always visible, panes scroll
// internally (same "nothing overflows the viewport" behaviour the
// Conversations page got).
// Description: DocGen working area — 3-pane layout dedicated to the
//              chat-driven document generation flow. The Documents
//              tab (artifacts) is for browsing + versioning ; this
//              page is where the operator iterates with the assistant
//              to produce new docs.
//
//              Sourced from the same artifacts surface
//              (`/api/v1/projects/{pid}/artifacts/runs/...`) so the
//              tree shows the same files as Documents/Files. Same
//              conversations as the dedicated Conversations page
//              (both filter `listConversations()` by project_id).
//
//              v2 (2026-05-18) : honours an optional `?path=<doc>`
//              URL param (alongside `?conv=`). The Conversations
//              inline tool-call strip deep-links here so the operator
//              lands on the freshly created / updated document in the
//              viewer with the originating conversation pre-selected
//              (Phase 2.C.3).
//
//              v1 (2026-05-14) : extracted out of the artifacts page
//              after the user split "view + versioning" (Documents)
//              from "chat to generate" (Working area) into two
//              top-level sidebar entries.
// =============================================================================

"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useProjectUi } from "@/app/(protected)/workspace-store";
import { useReadyConfig } from "@/app/providers";
import { ChatSidebar, type QuotedSnippet } from "@/components/chat-sidebar";
import { CodeViewer } from "@/components/code-viewer";
import { FileTree } from "@/components/file-tree";
import { ApiClient, ApiError } from "@/lib/apiClient";
import type { ArtifactNode, ArtifactRun } from "@/lib/types";

interface RunsLoad {
  status: "loading" | "ready" | "error";
  runs?: ArtifactRun[];
  error?: string;
}

interface TreeLoad {
  status: "idle" | "loading" | "ready" | "error";
  nodes?: ArtifactNode[];
  error?: string;
}

interface BlobLoad {
  status: "idle" | "loading" | "ready" | "binary" | "error";
  text?: string;
  contentType?: string;
  error?: string;
}

export default function WorkingAreaPage() {
  const params = useParams<{ pid: string }>();
  const projectId = decodeURIComponent(params.pid);
  const searchParams = useSearchParams();
  // Optional pre-selected conversation, sourced from the URL
  // `?conv=<id>` param. Populated by the "Open in Working area"
  // button on the Conversations list page.
  const initialConversationId = searchParams.get("conv");
  // Optional pre-selected document path (`?path=<doc>`), set by the
  // Conversations inline tool-call deep-link. Consumed exactly once
  // (on the first tree load that contains it) so later run switches
  // or manual selections aren't hijacked back to it.
  const initialPath = searchParams.get("path");
  const deepLinkConsumedRef = useRef(false);
  const cfg = useReadyConfig();
  const apiClient = useMemo(() => new ApiClient(cfg), [cfg]);

  // Cross-tab-nav UI store (Increment 3 phase 3a). Mirror pattern :
  // local state stays the working source of truth for this page's
  // effect web ; we only RESTORE the last selection from the store
  // once on mount/hydration and PERSIST it on change. So switching
  // tab (or F5) returns the operator to the same run/document.
  const { ui, setUi } = useProjectUi(projectId);
  const restoredRef = useRef(false);

  const [runsLoad, setRunsLoad] = useState<RunsLoad>({ status: "loading" });
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [treeLoad, setTreeLoad] = useState<TreeLoad>({ status: "idle" });
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [blobLoad, setBlobLoad] = useState<BlobLoad>({ status: "idle" });
  const [quoted, setQuoted] = useState<QuotedSnippet | null>(null);
  const [pendingQuote, setPendingQuote] = useState<string | null>(null);
  // Bumped by the chat sidebar's `onDocsMutated` after a successful
  // create/update/delete tool call. Drives a re-fetch of the runs
  // list + the active run's tree so the new/changed document shows
  // without a manual reload. `live-docs` is auto-selected when it
  // appears (it's where chat-direct mutations land).
  const [docsNonce, setDocsNonce] = useState(0);

  // RESTORE (once) the last run/doc from the cross-nav store. Runs
  // when the store finishes hydrating (sessionStorage) ; guarded so
  // it never fights the user's later selections. If the store is
  // empty (first visit) it no-ops and the normal auto-select wins.
  useEffect(() => {
    if (restoredRef.current) return;
    if (ui.selectedRunId || ui.selectedPath) {
      restoredRef.current = true;
      if (ui.selectedRunId) setSelectedRunId(ui.selectedRunId);
      if (ui.selectedPath) setSelectedPath(ui.selectedPath);
    }
  }, [ui.selectedRunId, ui.selectedPath]);

  // PERSIST run/doc selection so a tab switch or F5 returns here.
  useEffect(() => {
    setUi({ selectedRunId, selectedPath });
  }, [selectedRunId, selectedPath, setUi]);

  // Load runs on mount + after each doc mutation. Auto-select the
  // `live-docs` run if present (chat-direct corpus) else the most
  // recent ; never clobber an explicit user selection that still
  // exists in the refreshed list. `docsNonce` is a re-run trigger,
  // not referenced in the body — biome's static analysis can't see
  // that, hence the suppression (same pattern as the conversations
  // refresh-counter effect).
  // biome-ignore lint/correctness/useExhaustiveDependencies: docsNonce is a refresh trigger
  useEffect(() => {
    let cancelled = false;
    apiClient
      .listArtifactRuns(projectId)
      .then((resp) => {
        if (cancelled) return;
        setRunsLoad({ status: "ready", runs: resp.runs });
        setSelectedRunId((prev) => {
          if (prev && resp.runs.some((r) => r.run_id === prev)) return prev;
          const live = resp.runs.find((r) => r.run_id === "live-docs");
          if (live) return live.run_id;
          return resp.runs.length > 0 ? resp.runs[0].run_id : null;
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setRunsLoad({
          status: "error",
          error: err instanceof ApiError ? `Failed to load runs (${err.status})` : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [apiClient, projectId, docsNonce]);

  // Tree on selectedRunId change.
  useEffect(() => {
    if (!selectedRunId) {
      setTreeLoad({ status: "idle" });
      return;
    }
    let cancelled = false;
    setTreeLoad({ status: "loading" });
    setSelectedPath(null);
    setBlobLoad({ status: "idle" });
    apiClient
      .getArtifactTree(projectId, selectedRunId)
      .then((resp) => {
        if (cancelled) return;
        setTreeLoad({ status: "ready", nodes: resp.nodes });
        // Deep-link target wins on its first appearance, then we
        // never reapply it (operator stays in control afterwards).
        if (
          !deepLinkConsumedRef.current &&
          initialPath &&
          resp.nodes.some((n) => n.path === initialPath)
        ) {
          deepLinkConsumedRef.current = true;
          setSelectedPath(initialPath);
        } else if (resp.nodes.length > 0) {
          setSelectedPath(resp.nodes[0].path);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setTreeLoad({
          status: "error",
          error: err instanceof ApiError ? `Failed to load tree (${err.status})` : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [apiClient, projectId, selectedRunId, initialPath]);

  // Soft tree refresh after a doc mutation : re-fetch the active
  // run's nodes WITHOUT resetting `selectedPath` (keep the viewer on
  // the file the operator is reading). Skips the initial render
  // (docsNonce === 0) — the selectedRunId effect above already
  // populated the tree.
  useEffect(() => {
    if (docsNonce === 0 || !selectedRunId) return;
    let cancelled = false;
    apiClient
      .getArtifactTree(projectId, selectedRunId)
      .then((resp) => {
        if (cancelled) return;
        setTreeLoad({ status: "ready", nodes: resp.nodes });
        // Drop the viewer selection only if the file vanished.
        setSelectedPath((prev) => (prev && resp.nodes.some((n) => n.path === prev) ? prev : null));
      })
      .catch(() => {
        // Non-fatal — the stale tree stays ; next manual run switch
        // re-fetches cleanly.
      });
    return () => {
      cancelled = true;
    };
  }, [apiClient, projectId, selectedRunId, docsNonce]);

  // Blob on selectedPath change.
  useEffect(() => {
    if (!selectedRunId || !selectedPath) {
      setBlobLoad({ status: "idle" });
      return;
    }
    let cancelled = false;
    setBlobLoad({ status: "loading" });
    apiClient
      .getArtifactBlobText(projectId, selectedRunId, selectedPath)
      .then(({ text, contentType }) => {
        if (cancelled) return;
        const isText =
          contentType.startsWith("text/") ||
          contentType === "application/json" ||
          contentType === "application/javascript" ||
          contentType === "application/x-python";
        setBlobLoad(
          isText ? { status: "ready", text, contentType } : { status: "binary", contentType },
        );
      })
      .catch((err) => {
        if (cancelled) return;
        setBlobLoad({
          status: "error",
          error: err instanceof ApiError ? `Failed to load file (${err.status})` : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [apiClient, projectId, selectedRunId, selectedPath]);

  // Text selection capture (scoped to the viewer pane via data attr).
  useEffect(() => {
    function handler() {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed) {
        setPendingQuote(null);
        return;
      }
      const text = sel.toString();
      if (!text.trim()) {
        setPendingQuote(null);
        return;
      }
      const viewerNode = document.querySelector("[data-working-viewer='true']");
      if (!viewerNode) {
        setPendingQuote(null);
        return;
      }
      const anchorNode = sel.anchorNode;
      if (anchorNode && viewerNode.contains(anchorNode)) {
        setPendingQuote(text);
      } else {
        setPendingQuote(null);
      }
    }
    document.addEventListener("selectionchange", handler);
    return () => document.removeEventListener("selectionchange", handler);
  }, []);

  return (
    <main
      className="mx-auto flex h-[calc(100dvh-8rem)] min-h-0 max-w-7xl flex-col px-6 py-6"
      data-testid="working-area"
    >
      <header className="mb-3">
        <h2 className="text-2xl font-semibold tracking-tight">Working area</h2>
        <p className="mt-1 text-sm text-neutral-500">
          Chat with the assistant to draft and refine documents. Select text in the viewer to quote
          it into the conversation.
        </p>
      </header>

      {/* `flex-1 min-h-0` makes the 3-pane grid fill exactly the
          space left under the header (no guessed header-height
          subtraction), so the chat column's pinned composer + Send
          button are always within the viewport — no page scroll. */}
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[16rem_minmax(0,1fr)_22rem]">
        {/* Left : run picker + tree */}
        <aside className="flex min-h-0 flex-col gap-3 overflow-hidden">
          <div className="shrink-0">
            <RunsList load={runsLoad} selectedRunId={selectedRunId} onSelect={setSelectedRunId} />
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            {selectedRunId ? (
              <TreePanel load={treeLoad} selectedPath={selectedPath} onSelect={setSelectedPath} />
            ) : (
              <p className="rounded-md border border-neutral-200 bg-white px-3 py-3 text-sm text-neutral-500">
                Pick a run to see its files.
              </p>
            )}
          </div>
        </aside>

        {/* Middle : viewer + floating Quote-in-chat button */}
        <section
          data-working-viewer="true"
          className="relative flex min-h-0 flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white"
          data-testid="working-viewer-pane"
        >
          {selectedPath ? (
            <div className="flex items-center justify-between gap-3 border-b border-neutral-200 px-4 py-2">
              <p className="truncate font-mono text-sm text-neutral-900">{selectedPath}</p>
              {blobLoad.status === "ready" || blobLoad.status === "binary" ? (
                <span className="shrink-0 text-xs text-neutral-500">{blobLoad.contentType}</span>
              ) : null}
            </div>
          ) : null}
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Viewer blobLoad={blobLoad} selectedPath={selectedPath} />
          </div>
          {pendingQuote && selectedPath && (
            <div className="absolute bottom-3 left-1/2 -translate-x-1/2">
              <button
                type="button"
                onClick={() => {
                  setQuoted({ path: selectedPath, text: pendingQuote });
                  window.getSelection()?.removeAllRanges();
                  setPendingQuote(null);
                }}
                className="rounded-full bg-blue-600 px-4 py-2 text-xs font-semibold text-white shadow-lg hover:bg-blue-700"
                data-testid="working-quote-button"
              >
                Quote in chat ({pendingQuote.length} chars)
              </button>
            </div>
          )}
        </section>

        {/* Right : chat sidebar */}
        <aside className="min-h-0 overflow-hidden rounded-lg border border-neutral-200 bg-white">
          <ChatSidebar
            cfg={cfg}
            projectId={projectId}
            quoted={quoted}
            onClearQuote={() => setQuoted(null)}
            initialConversationId={initialConversationId}
            onDocsMutated={() => setDocsNonce((n) => n + 1)}
          />
        </aside>
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Internal helpers — kept inline to avoid an extra module while the
// shapes stabilise. If a third consumer (beyond artifacts page +
// working area) ever needs these, extract to `components/`.
// ---------------------------------------------------------------------------

function RunsList({
  load,
  selectedRunId,
  onSelect,
}: {
  load: RunsLoad;
  selectedRunId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white">
      <header className="border-b border-neutral-200 px-3 py-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
        Runs
      </header>
      {load.status === "loading" ? (
        <p className="px-3 py-3 text-sm text-neutral-500">Loading…</p>
      ) : load.status === "error" ? (
        <p className="px-3 py-3 text-sm text-red-700" role="alert">
          {load.error}
        </p>
      ) : !load.runs || load.runs.length === 0 ? (
        <p className="px-3 py-3 text-sm text-neutral-500">No runs yet.</p>
      ) : (
        <ul className="max-h-32 overflow-y-auto divide-y divide-neutral-100">
          {load.runs.map((r) => {
            const active = r.run_id === selectedRunId;
            return (
              <li key={r.run_id}>
                <button
                  type="button"
                  onClick={() => onSelect(r.run_id)}
                  className={[
                    "block w-full truncate px-3 py-1.5 text-left text-xs",
                    active ? "bg-blue-50 text-blue-900" : "text-neutral-700 hover:bg-neutral-50",
                  ].join(" ")}
                >
                  <span className="font-medium">{r.label ?? r.run_id.slice(0, 8)}</span>
                  <span className="ml-1 text-neutral-400">· {r.file_count} files</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function TreePanel({
  load,
  selectedPath,
  onSelect,
}: {
  load: TreeLoad;
  selectedPath: string | null;
  onSelect: (path: string) => void;
}) {
  return (
    <div className="h-full rounded-lg border border-neutral-200 bg-white">
      <header className="border-b border-neutral-200 px-3 py-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
        Files
      </header>
      {load.status === "loading" ? (
        <p className="px-3 py-3 text-sm text-neutral-500">Loading…</p>
      ) : load.status === "error" ? (
        <p className="px-3 py-3 text-sm text-red-700" role="alert">
          {load.error}
        </p>
      ) : (
        <FileTree nodes={load.nodes ?? []} selectedPath={selectedPath} onSelect={onSelect} />
      )}
    </div>
  );
}

function Viewer({ blobLoad, selectedPath }: { blobLoad: BlobLoad; selectedPath: string | null }) {
  if (!selectedPath) {
    return (
      <p className="px-4 py-10 text-center text-sm text-neutral-500">
        Pick a file in the tree to preview it.
      </p>
    );
  }
  if (blobLoad.status === "loading") {
    return <p className="px-4 py-10 text-sm text-neutral-500">Loading file…</p>;
  }
  if (blobLoad.status === "error") {
    return (
      <p className="px-4 py-10 text-sm text-red-700" role="alert">
        {blobLoad.error}
      </p>
    );
  }
  if (blobLoad.status === "binary") {
    return (
      <p className="px-4 py-10 text-sm text-neutral-500">
        Binary file ({blobLoad.contentType}). Download to inspect.
      </p>
    );
  }
  if (blobLoad.status === "ready") {
    return <CodeViewer text={blobLoad.text ?? ""} path={selectedPath} />;
  }
  return null;
}
