// =============================================================================
// File: apiClient.test.ts
// Version: 2
// Path: ay_platform_ui/tests/unit/lib/apiClient.test.ts
// Description: Unit tests for the HTTP client wrapper. Covers :
//                - URL composition (relative vs absolute apiBaseUrl)
//                - Authorization header injection from localStorage
//                - login() returns the token without persisting
//                - ApiError thrown on non-2xx with status + body
//                - localStorage helpers (read/write/clear)
//
//              v2 (2026-05-21): version-history methods (R-200-147) —
//              `listProjectCommits` forwards an optional `path` filter
//              and `getDocumentTextAtRef` builds the `?ref=<sha>` read
//              URL + returns the decoded text + content type.
// =============================================================================

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiClient,
  ApiError,
  clearStoredToken,
  readStoredToken,
  writeStoredToken,
} from "@/lib/apiClient";
import type { PlatformConfig } from "@/lib/types";

const SAME_ORIGIN_CFG: PlatformConfig = {
  runtime: { apiBaseUrl: "", publicBaseUrl: "" },
  ux: {
    api_version: "v1",
    auth_mode: "local",
    brand: {
      name: "AyWizz",
      short_name: "AY",
      accent_color_hex: "#000",
    },
    features: {
      chat_enabled: true,
      kg_enabled: true,
      cross_tenant_enabled: false,
      file_download_enabled: true,
    },
  },
};

const CROSS_ORIGIN_CFG: PlatformConfig = {
  ...SAME_ORIGIN_CFG,
  runtime: {
    apiBaseUrl: "https://api.example.com",
    publicBaseUrl: "https://app.example.com",
  },
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

describe("token storage helpers", () => {
  it("write+read round-trips a token", () => {
    writeStoredToken("token-123");
    expect(readStoredToken()).toBe("token-123");
  });

  it("read returns null when no token has been written", () => {
    expect(readStoredToken()).toBeNull();
  });

  it("clear removes the stored token", () => {
    writeStoredToken("token-456");
    clearStoredToken();
    expect(readStoredToken()).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// URL composition
// ---------------------------------------------------------------------------

describe("ApiClient URL composition", () => {
  it("uses a relative URL when apiBaseUrl is empty", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          access_token: "t",
          token_type: "bearer",
          expires_in: 3600,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await client.login("alice", "pw");

    expect(fetchMock).toHaveBeenCalledWith(
      "/auth/login",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("prepends apiBaseUrl when set (cross-origin deployment)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          access_token: "t",
          token_type: "bearer",
          expires_in: 3600,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient(CROSS_ORIGIN_CFG);
    await client.login("alice", "pw");

    expect(fetchMock).toHaveBeenCalledWith("https://api.example.com/auth/login", expect.anything());
  });
});

// ---------------------------------------------------------------------------
// login() — returns token, does NOT persist
// ---------------------------------------------------------------------------

describe("ApiClient.login", () => {
  it("returns the access_token from the LoginResponse body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            access_token: "jwt-abc",
            token_type: "bearer",
            expires_in: 3600,
          }),
      }),
    );

    const client = new ApiClient(SAME_ORIGIN_CFG);
    const token = await client.login("alice", "pw");

    expect(token).toBe("jwt-abc");
  });

  it("does NOT write to localStorage — AuthProvider owns persistence", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            access_token: "jwt-abc",
            token_type: "bearer",
            expires_in: 3600,
          }),
      }),
    );

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await client.login("alice", "pw");

    expect(readStoredToken()).toBeNull();
  });

  it("posts a JSON body with username + password", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          access_token: "t",
          token_type: "bearer",
          expires_in: 3600,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await client.login("alice", "pw-123");

    const callArgs = fetchMock.mock.calls[0];
    const init = callArgs[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ username: "alice", password: "pw-123" }));
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});

// ---------------------------------------------------------------------------
// Authorization header injection
// ---------------------------------------------------------------------------

describe("ApiClient authorization header", () => {
  it("attaches Authorization: Bearer when a token is in localStorage", async () => {
    writeStoredToken("stored-token");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          access_token: "fresh",
          token_type: "bearer",
          expires_in: 3600,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await client.login("alice", "pw");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer stored-token");
  });

  it("omits Authorization when no token is stored", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          access_token: "t",
          token_type: "bearer",
          expires_in: 3600,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await client.login("alice", "pw");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// ApiError on non-2xx
// ---------------------------------------------------------------------------

describe("ApiClient error handling", () => {
  it("throws ApiError with status + url + body on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        text: () => Promise.resolve('{"detail":"invalid credentials"}'),
      }),
    );

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await expect(client.login("alice", "wrong")).rejects.toBeInstanceOf(ApiError);
    try {
      await client.login("alice", "wrong");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(401);
      expect(apiErr.url).toBe("/auth/login");
      expect(apiErr.body).toContain("invalid credentials");
    }
  });

  it("includes status + body in the error message for log clarity", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        text: () => Promise.resolve("service unavailable"),
      }),
    );

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await expect(client.login("alice", "pw")).rejects.toThrow(/503.*service unavailable/);
  });

  it("handles a 4xx with empty body gracefully", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: () => Promise.resolve(""),
      }),
    );

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await expect(client.login("a", "b")).rejects.toThrow(/empty body/);
  });
});

// ---------------------------------------------------------------------------
// Version history (R-200-147) — per-file commits + read-at-ref
// ---------------------------------------------------------------------------

describe("ApiClient version history", () => {
  it("listProjectCommits forwards the optional path filter", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ commits: [], page: 1 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await client.listProjectCommits("proj-d", 1, "docs/intro.md");

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/v1/projects/proj-d/git/commits?page=1");
    expect(url).toContain("&path=docs%2Fintro.md");
  });

  it("listProjectCommits omits the path query when not provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ commits: [], page: 1 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await client.listProjectCommits("proj-d");

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("&path=");
  });

  it("getDocumentTextAtRef builds the ?ref read URL and returns text + type", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve("# v1\n"),
      headers: new Headers({ "Content-Type": "text/markdown" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const client = new ApiClient(SAME_ORIGIN_CFG);
    const out = await client.getDocumentTextAtRef("proj-d", "docs/intro.md", "sha-1");

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/v1/projects/proj-d/documents/docs/intro.md?ref=sha-1");
    expect(out).toEqual({ text: "# v1\n", contentType: "text/markdown" });
  });

  it("getDocumentTextAtRef throws ApiError on a 404 (unknown ref)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        text: () => Promise.resolve('{"detail":"not found at ref"}'),
      }),
    );

    const client = new ApiClient(SAME_ORIGIN_CFG);
    await expect(
      client.getDocumentTextAtRef("proj-d", "docs/intro.md", "bad"),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
