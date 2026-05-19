// =============================================================================
// File: workspace-store.tsx
// Version: 2
// Path: ay_platform_ui/app/(protected)/workspace-store.tsx
// Description: Increment 3 (phase 3a) — Tier-1 per-project UI-state
//              store. Mounted in `(protected)/layout.tsx` ABOVE the
//              Next router outlet, so it survives navigation between
//              tabs (Working area <-> Conversations <-> Documents):
//              switching tab no longer loses the selected run/doc,
//              the active conversation, or the composer draft.
//
//              Two-tier model (operator's explicit split):
//                - THIS store = local UI state only (ephemeral,
//                  presentation). Hydrated from `sessionStorage`
//                  (per project) so it ALSO survives a hard refresh.
//                - The processing-flow / audit trail (tool calls,
//                  pipeline) is NOT here — it is persisted server
//                  side as `MessagePublic.events` and re-rendered
//                  from the DB (traceability by construction).
//
//              v2 : idiomatic `useState`-backed map (the v1 ref +
//              version-bump hack fought the exhaustive-deps lint and
//              was non-standard). The no-op guard returns the SAME
//              map reference so React bails the render — no storm.
//
//              Phase 3b (deferred) will move the SSE send-loop into
//              this provider so a LIVE generation keeps running when
//              the operator navigates away and back. Not in 3a — the
//              audit trail already survives reload via the DB ledger.
// =============================================================================

"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

/** Ephemeral per-project UI state. Presentation only — never the
 *  source of truth for anything persisted server-side. */
export interface ProjectUiState {
  /** Conversation selected in Working area / last opened. */
  activeConversationId: string | null;
  /** Artifact run selected in the Working area tree panel. */
  selectedRunId: string | null;
  /** Document path open in the Working area viewer. */
  selectedPath: string | null;
  /** Unsent composer text, so a half-typed message survives a tab
   *  switch or refresh. */
  composerDraft: string;
}

const EMPTY: ProjectUiState = {
  activeConversationId: null,
  selectedRunId: null,
  selectedPath: null,
  composerDraft: "",
};

interface WorkspaceStore {
  /** Read the (possibly empty) UI slice for a project. */
  get: (projectId: string) => ProjectUiState;
  /** Shallow-merge a patch into a project's UI slice. */
  patch: (projectId: string, patch: Partial<ProjectUiState>) => void;
}

const Ctx = createContext<WorkspaceStore | null>(null);

const STORAGE_KEY = "aywizz.workspace.ui.v1";

type UiMap = Record<string, ProjectUiState>;

/** Read the whole map from sessionStorage. Defensive : any parse
 *  failure or non-browser context yields an empty map (UI state is
 *  non-critical — never throw over it). */
function loadAll(): UiMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? (parsed as UiMap) : {};
  } catch {
    return {};
  }
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [map, setMap] = useState<UiMap>({});

  // Hydrate once from sessionStorage (survives F5). In an effect so
  // SSR / first paint is deterministic.
  useEffect(() => {
    const stored = loadAll();
    if (Object.keys(stored).length > 0) setMap(stored);
  }, []);

  // Persist (best-effort) on every change.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(map));
    } catch {
      // Quota / disabled storage — UI state is non-critical, ignore.
    }
  }, [map]);

  const patch = useCallback((projectId: string, p: Partial<ProjectUiState>) => {
    setMap((prev) => {
      const cur = prev[projectId] ?? EMPTY;
      const next = { ...cur, ...p };
      // No-op guard : return the SAME map reference when nothing
      // actually changed so React bails the re-render (controlled
      // inputs call setters with unchanged values constantly).
      if (
        next.activeConversationId === cur.activeConversationId &&
        next.selectedRunId === cur.selectedRunId &&
        next.selectedPath === cur.selectedPath &&
        next.composerDraft === cur.composerDraft
      ) {
        return prev;
      }
      return { ...prev, [projectId]: next };
    });
  }, []);

  const get = useCallback((projectId: string): ProjectUiState => map[projectId] ?? EMPTY, [map]);

  const store = useMemo<WorkspaceStore>(() => ({ get, patch }), [get, patch]);

  return <Ctx.Provider value={store}>{children}</Ctx.Provider>;
}

/** Hook : the UI-state slice for one project + a typed patcher.
 *  Safe to call outside the provider (returns an inert EMPTY slice +
 *  no-op patch) so a page can't crash if the provider is missing. */
export function useProjectUi(projectId: string): {
  ui: ProjectUiState;
  setUi: (patch: Partial<ProjectUiState>) => void;
} {
  const store = useContext(Ctx);
  const ui = store ? store.get(projectId) : EMPTY;
  const setUi = useCallback(
    (p: Partial<ProjectUiState>) => store?.patch(projectId, p),
    [store, projectId],
  );
  return { ui, setUi };
}
