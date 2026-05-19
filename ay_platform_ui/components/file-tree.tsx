// =============================================================================
// File: file-tree.tsx
// Version: 1
// Path: ay_platform_ui/components/file-tree.tsx
// Description: VSCode-like file tree component used by the Code source /
//              Documents section. Takes the flat `ArtifactNode[]` list
//              returned by `/api/v1/projects/{pid}/artifacts/runs/{rid}/tree`
//              and renders it as a hierarchy with collapsible folders.
//
//              Layout rules :
//                - One row per node ; folders show a caret (▸/▾) ;
//                  files show a small file glyph and the basename.
//                - Indentation = 16 px per depth level.
//                - Click on a folder row toggles open/closed (independent
//                  state per node). Click on a file row fires `onSelect`.
//                - Selected file row gets a blue tint ; folders never
//                  hold "selection" state — only files do.
//                - First mount expands every folder so small trees are
//                  visible without clicking. Operators can collapse the
//                  ones they don't need.
//
//              Profile-agnostic : `code` shows `src/`, `tests/`, ... ;
//              `docgen` shows `docs/`, `reports/`, ... — the component
//              doesn't care.
// =============================================================================

"use client";

import { useMemo, useState } from "react";

import type { ArtifactNode } from "@/lib/types";

interface TreeNode {
  name: string;
  path: string; // full path from root (file only ; for folders we compose synthetic ids)
  type: "file" | "folder";
  sizeBytes?: number;
  children?: TreeNode[];
}

interface FileTreeProps {
  nodes: ArtifactNode[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

/** Build the hierarchical tree from the flat node list. Sort entries
 *  alphabetically within each level, folders first then files (the
 *  VSCode convention). */
function buildTree(flat: ArtifactNode[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", type: "folder", children: [] };
  for (const node of flat) {
    if (node.kind !== "file") continue;
    const parts = node.path.split("/").filter(Boolean);
    let cursor = root;
    parts.forEach((part, idx) => {
      const isLeaf = idx === parts.length - 1;
      cursor.children ??= [];
      let next = cursor.children.find((c) => c.name === part);
      if (!next) {
        next = {
          name: part,
          path: parts.slice(0, idx + 1).join("/"),
          type: isLeaf ? "file" : "folder",
          sizeBytes: isLeaf ? node.size_bytes : undefined,
          children: isLeaf ? undefined : [],
        };
        cursor.children.push(next);
      }
      cursor = next;
    });
  }
  sortTree(root);
  return root.children ?? [];
}

function sortTree(node: TreeNode): void {
  if (!node.children) return;
  node.children.sort((a, b) => {
    if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  for (const child of node.children) sortTree(child);
}

/** All folder paths in the tree — used as the initial expanded-set so
 *  every level renders open on first mount. */
function collectFolderPaths(nodes: TreeNode[]): string[] {
  const out: string[] = [];
  const walk = (list: TreeNode[]) => {
    for (const n of list) {
      if (n.type === "folder") {
        out.push(n.path);
        if (n.children) walk(n.children);
      }
    }
  };
  walk(nodes);
  return out;
}

export function FileTree({ nodes, selectedPath, onSelect }: FileTreeProps) {
  const tree = useMemo(() => buildTree(nodes), [nodes]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(collectFolderPaths(tree)));

  function toggle(path: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  if (tree.length === 0) {
    return <p className="px-3 py-3 text-sm text-neutral-500">No files in this run.</p>;
  }

  return (
    <div className="max-h-[60vh] overflow-y-auto py-1" data-testid="file-tree">
      <ul aria-label="Files in this run">
        {tree.map((node) => (
          <TreeRow
            key={node.path}
            node={node}
            depth={0}
            selectedPath={selectedPath}
            expanded={expanded}
            onToggle={toggle}
            onSelect={onSelect}
          />
        ))}
      </ul>
    </div>
  );
}

interface TreeRowProps {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
}

function TreeRow({ node, depth, selectedPath, expanded, onToggle, onSelect }: TreeRowProps) {
  const indentPx = depth * 16;
  if (node.type === "folder") {
    const open = expanded.has(node.path);
    return (
      <li>
        <button
          type="button"
          onClick={() => onToggle(node.path)}
          style={{ paddingLeft: `${indentPx + 8}px` }}
          className="flex w-full items-center gap-1 py-1 pr-3 text-left text-xs text-neutral-700 hover:bg-neutral-100 dark:text-neutral-200 dark:hover:bg-neutral-800"
          data-testid={`file-tree-folder-${node.path}`}
        >
          <span className="inline-block w-3 text-neutral-400">{open ? "▾" : "▸"}</span>
          <span aria-hidden="true">📁</span>
          <span className="font-medium">{node.name}</span>
        </button>
        {open && node.children && (
          <ul>
            {node.children.map((child) => (
              <TreeRow
                key={child.path}
                node={child}
                depth={depth + 1}
                selectedPath={selectedPath}
                expanded={expanded}
                onToggle={onToggle}
                onSelect={onSelect}
              />
            ))}
          </ul>
        )}
      </li>
    );
  }
  const active = node.path === selectedPath;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        style={{ paddingLeft: `${indentPx + 8 + 12}px` /* align with folder text */ }}
        className={[
          "flex w-full items-center gap-1 py-1 pr-3 text-left font-mono text-xs transition-colors",
          active
            ? "bg-blue-100 text-blue-900 dark:bg-blue-900 dark:text-blue-100"
            : "text-neutral-700 hover:bg-neutral-100 dark:text-neutral-200 dark:hover:bg-neutral-800",
        ].join(" ")}
        data-testid={`file-tree-file-${node.path}`}
        data-active={active ? "true" : "false"}
        title={
          node.sizeBytes !== undefined ? `${node.path} · ${formatBytes(node.sizeBytes)}` : node.path
        }
      >
        <span aria-hidden="true">{_fileGlyph(node.name)}</span>
        <span className="truncate">{node.name}</span>
      </button>
    </li>
  );
}

function _fileGlyph(name: string): string {
  const lower = name.toLowerCase();
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "📝";
  if (lower.endsWith(".py")) return "🐍";
  if (lower.endsWith(".ts") || lower.endsWith(".tsx")) return "🔷";
  if (lower.endsWith(".js") || lower.endsWith(".jsx")) return "🟨";
  if (
    lower.endsWith(".yml") ||
    lower.endsWith(".yaml") ||
    lower.endsWith(".toml") ||
    lower.endsWith(".json")
  )
    return "⚙️";
  if (lower.endsWith(".pdf")) return "📕";
  if (
    lower.endsWith(".png") ||
    lower.endsWith(".jpg") ||
    lower.endsWith(".jpeg") ||
    lower.endsWith(".svg")
  )
    return "🖼️";
  return "📄";
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
