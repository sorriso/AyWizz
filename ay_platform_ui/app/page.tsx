// =============================================================================
// File: page.tsx
// Version: 1
// Path: ay_platform_ui/app/page.tsx
// Description: Scaffold landing page. Fetches /auth/config through Traefik
//              to show the UI can round-trip a request to the platform
//              gateway. This is the smallest proof the UI/server chain is
//              alive — no chat, no requirements, no auth flow yet.
// =============================================================================

import { fetchAuthConfig } from "@/lib/platform";

export default async function LandingPage() {
  const cfg = await fetchAuthConfig();

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="text-4xl font-semibold tracking-tight">ay platform</h1>
      <p className="mt-4 text-lg text-neutral-600">
        Requirements-driven artifact generation for code, documentation and
        presentations.
      </p>

      <section className="mt-10 rounded-lg border border-neutral-200 bg-white p-6">
        <h2 className="text-sm uppercase tracking-wide text-neutral-500">
          Platform status
        </h2>
        {cfg ? (
          <p className="mt-2 text-base">
            Auth mode:{" "}
            <code className="rounded bg-neutral-100 px-2 py-0.5">
              {cfg.mode}
            </code>
          </p>
        ) : (
          <p className="mt-2 text-base text-red-700">
            Cannot reach the platform gateway. Is the docker-compose stack up?
          </p>
        )}
      </section>

      <footer className="mt-16 text-xs text-neutral-400">
        UI scaffold v0 — feature work is gated on end-to-end server stack
        validation.
      </footer>
    </main>
  );
}
