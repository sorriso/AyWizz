// =============================================================================
// File: layout.tsx
// Version: 1
// Path: ay_platform_ui/app/layout.tsx
// Description: Root layout. Imports Tailwind styles and sets the document
//              metadata. Page-level UI is scaffold-only in v0 — see
//              ay_platform_ui/README.md for the feature roadmap.
// =============================================================================

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ay platform",
  description: "Requirements-driven artifact generation platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
