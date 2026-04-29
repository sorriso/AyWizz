// =============================================================================
// File: apiClient.ts
// Version: 1
// Path: ay_platform_ui/lib/apiClient.ts
// Description: Thin wrapper over `fetch` that prepends the runtime-config
//              `apiBaseUrl` to every call and (optionally) attaches the
//              user's JWT bearer token. Components use this rather than
//              calling `fetch` directly so the API base URL is honoured
//              uniformly.
// =============================================================================

import type { PlatformConfig } from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly url: string,
    public readonly body: string,
  ) {
    super(`API ${status} ${url}: ${body || "(empty body)"}`);
    this.name = "ApiError";
  }
}

/** Token storage key — same shape as auth-matrix tests use, but in
 *  localStorage rather than HTTP-only cookie. v1 trade-off : XSS
 *  exposure vs CSRF resilience ; HTTP-only cookies move that to the
 *  next iteration with proper backend `/auth/login` cookie support. */
const TOKEN_KEY = "aywizz.token";

export function readStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function writeStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiClient {
  constructor(private readonly cfg: PlatformConfig) {}

  private url(path: string): string {
    const base = this.cfg.runtime.apiBaseUrl;
    return base ? `${base}${path}` : path;
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    const url = this.url(path);
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    const token = readStoredToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const resp = await fetch(url, { ...init, headers, cache: "no-store" });
    if (!resp.ok) {
      const body = await resp.text().catch(() => "");
      throw new ApiError(resp.status, url, body);
    }
    if (resp.status === 204) return undefined as T;
    return (await resp.json()) as T;
  }

  /** POST /auth/login — returns the access token. The caller (login
   *  page) forwards it to `auth.setToken(token)` so the AuthProvider
   *  owns persistence + decoded-claims state ; this method
   *  intentionally does NOT write to localStorage directly. */
  async login(username: string, password: string): Promise<string> {
    type LoginResponse = {
      access_token: string;
      token_type: string;
      expires_in: number;
    };
    const body = await this.request<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    return body.access_token;
  }
}
