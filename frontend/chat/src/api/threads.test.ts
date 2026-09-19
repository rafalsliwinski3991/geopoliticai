import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listThreads, readThread, type ThreadSummary } from "./threads";

function tokenResponse() {
  return {
    ok: true,
    status: 200,
    json: async () => ({ access: "tok", expires_in: 900 }),
  } as unknown as Response;
}

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as unknown as Response;
}

// jsdom's `window.location` is frozen; intercept navigation at `assign`, as
// the token module's tests do.
const assign = vi.fn();

beforeEach(() => {
  assign.mockClear();
  vi.resetModules();
  vi.stubGlobal(
    "window",
    Object.assign(Object.create(Object.getPrototypeOf(window)), {
      ...window,
      location: { ...window.location, assign },
    }),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the threads API", () => {
  it("listThreads GETs /api/threads and unwraps threads + quota", async () => {
    // Arrange
    const threads: ThreadSummary[] = [
      { id: "t1", title: "Baltic energy", created_at: "2026-09-18T10:00:00Z" },
    ];
    const fetchMock = vi.fn((url: string) =>
      url === "/api/threads"
        ? Promise.resolve(
            jsonResponse({ threads, quota: { used: 6, limit: 20 } }),
          )
        : Promise.resolve(tokenResponse()),
    );
    vi.stubGlobal("fetch", fetchMock);
    // Act
    const result = await listThreads();
    // Assert
    expect(result.threads).toEqual(threads);
    expect(result.quota).toEqual({ used: 6, limit: 20 });
  });

  it("readThread GETs the thread resource and unwraps its messages", async () => {
    // Arrange
    const messages = [
      { role: "user", text: "hi" },
      { role: "assistant", text: "hello" },
    ];
    const fetchMock = vi.fn((url: string) =>
      url === "/api/threads/t1"
        ? Promise.resolve(jsonResponse({ thread_id: "t1", messages }))
        : Promise.resolve(tokenResponse()),
    );
    vi.stubGlobal("fetch", fetchMock);
    // Act
    const result = await readThread("t1");
    // Assert
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/threads/t1",
      expect.anything(),
    );
    expect(result.messages).toEqual(messages);
  });

  it("the bearer token rides on the threads request", async () => {
    // Arrange
    let seen: unknown;
    const fetchMock = vi.fn((url: string, init: RequestInit) => {
      if (url === "/api/threads") {
        seen = init.headers;
        return Promise.resolve(
          jsonResponse({ threads: [], quota: { used: 0, limit: 20 } }),
        );
      }
      return Promise.resolve(tokenResponse());
    });
    vi.stubGlobal("fetch", fetchMock);
    await listThreads();
    // Assert
    expect((seen as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("a 401 re-authenticates by redirecting to the login page", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url === "/accounts/token/"
          ? Promise.resolve(tokenResponse())
          : Promise.resolve(jsonResponse({}, 401)),
      ),
    );
    // Assert
    await expect(listThreads()).rejects.toThrow();
    expect(assign).toHaveBeenCalledWith(
      expect.stringContaining("/accounts/login/"),
    );
  });
});
