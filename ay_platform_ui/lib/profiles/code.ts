// =============================================================================
// File: code.ts
// Version: 1
// Path: ay_platform_ui/lib/profiles/code.ts
// Description: The `code` production profile — the only one shipped
//              in v1. Drives the project sidebar : Overview, Sources,
//              Conversations, Requirements, Validation, Settings.
//              Future code-domain features (orchestrator runs, code
//              artefacts, etc.) will be additional sections here.
// =============================================================================

import type { ProfileDefinition } from "./types";

export const CODE_PROFILE: ProfileDefinition = {
  id: "code",
  label: "Code",
  tagline: "Source-driven requirements, validation and generation",
  sections: [
    {
      id: "overview",
      label: "Overview",
      path: "overview",
      iconName: "home",
      description: "Project summary, recent activity and quick stats.",
    },
    {
      id: "sources",
      label: "Sources",
      path: "sources",
      iconName: "folder",
      description: "Upload and manage the source corpus feeding RAG.",
    },
    {
      id: "conversations",
      label: "Conversations",
      path: "conversations",
      iconName: "chat",
      description: "Chat with the platform's RAG-augmented assistant.",
    },
    {
      id: "requirements",
      label: "Requirements",
      path: "requirements",
      iconName: "document",
      description: "Browse and edit the project's specification corpus.",
    },
    {
      id: "validation",
      label: "Validation",
      path: "validation",
      iconName: "shield-check",
      description: "Run validation pipelines and inspect their findings.",
    },
    {
      id: "settings",
      label: "Settings",
      path: "settings",
      iconName: "cog",
      description: "Project metadata, members and integrations.",
    },
  ],
};
