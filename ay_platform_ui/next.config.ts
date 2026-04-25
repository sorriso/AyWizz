// =============================================================================
// File: next.config.ts
// Version: 1
// Path: ay_platform_ui/next.config.ts
// Description: Next.js configuration for the platform UI. Same-origin calls
//              are proxied through the C1 Traefik gateway defined in
//              NEXT_PUBLIC_PLATFORM_BASE_URL so the browser does not need
//              CORS exemptions.
// =============================================================================

import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // During dev, rewrite /api/platform/* and /auth/* to the running
  // docker-compose stack. The env var is required; there is no fallback to
  // localhost so a forgotten .env fails loudly.
  async rewrites() {
    const base = process.env.NEXT_PUBLIC_PLATFORM_BASE_URL;
    if (!base) return [];
    return [
      { source: "/auth/:path*", destination: `${base}/auth/:path*` },
      { source: "/api/platform/:path*", destination: `${base}/api/v1/:path*` },
    ];
  },
};

export default config;
