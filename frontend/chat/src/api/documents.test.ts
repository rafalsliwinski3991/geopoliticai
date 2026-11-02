import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { removeDocument, uploadDocument } from "./documents";

const THREAD_ID = "t1";
const REPORT = new File(["Hello"], "Q3 report.txt", { type: "text/plain" });

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

// Answers the token request, and the document request with `reply`.
function stubFetch(reply: Response) {
  const fetchMock = vi.fn((url: string, _init?: RequestInit) =>
    url === "/accounts/token/" ? Promise.resolve(tokenResponse()) : Promise.resolve(reply),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function documentCall(fetchMock: ReturnType<typeof stubFetch>) {
  const call = fetchMock.mock.calls.find(([url]) => url !== "/accounts/token/");
  if (!call) throw new Error("no document request was sent");
  return { url: call[0], init: call[1] as RequestInit };
}

// jsdom's `window.location` is frozen; intercept navigation at `assign`, as
// the threads module's tests do.
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

describe("uploadDocument", () => {
  it("POSTs the file as raw bytes under its encoded name and returns the view", async () => {
    // Arrange
    const fetchMock = stubFetch(
      jsonResponse({ filename: "Q3 report.txt", chunks: 4 }),
    );
    // Act
    const result = await uploadDocument(THREAD_ID, REPORT);
    // Assert
    const { url, init } = documentCall(fetchMock);
    expect(url).toBe("/api/threads/t1/document?filename=Q3%20report.txt");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(REPORT);
    expect(init.headers).toEqual({
      Authorization: "Bearer tok",
      "Content-Type": "application/octet-stream",
    });
    expect(result).toEqual({ filename: "Q3 report.txt", chunks: 4 });
  });

  it("a refusal throws the backend's own message", async () => {
    // Arrange
    stubFetch(
      jsonResponse({ detail: "That file is over the 25 MB limit." }, 413),
    );
    // Act + Assert
    await expect(uploadDocument(THREAD_ID, REPORT)).rejects.toThrow(
      "That file is over the 25 MB limit.",
    );
  });

  it("a refusal with no readable detail still throws, naming the status", async () => {
    // Arrange
    stubFetch(jsonResponse({}, 504));
    // Act + Assert
    await expect(uploadDocument(THREAD_ID, REPORT)).rejects.toThrow("504");
  });

  it("a 401 re-authenticates by redirecting to the login page", async () => {
    // Arrange
    stubFetch(jsonResponse({}, 401));
    // Act + Assert
    await expect(uploadDocument(THREAD_ID, REPORT)).rejects.toThrow();
    expect(assign).toHaveBeenCalledWith(
      expect.stringContaining("/accounts/login/"),
    );
  });
});

describe("removeDocument", () => {
  it("sends DELETE to the thread's document with the bearer token", async () => {
    // Arrange
    const fetchMock = stubFetch({ ok: true, status: 204 } as Response);
    // Act
    await removeDocument(THREAD_ID);
    // Assert
    const { url, init } = documentCall(fetchMock);
    expect(url).toBe("/api/threads/t1/document");
    expect(init.method).toBe("DELETE");
    expect(init.headers).toEqual({ Authorization: "Bearer tok" });
  });

  it("a 401 re-authenticates by redirecting to the login page", async () => {
    // Arrange
    stubFetch(jsonResponse({}, 401));
    // Act + Assert
    await expect(removeDocument(THREAD_ID)).rejects.toThrow();
    expect(assign).toHaveBeenCalledWith(
      expect.stringContaining("/accounts/login/"),
    );
  });
});
