import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, act, fireEvent, cleanup } from "@testing-library/react";

// app.test must re-import the app per test: the token module inside it keeps
// module-level state that must not leak between tests.
const importApp = async () => (await import("./App")).default;

const tokenOk = {
  ok: true,
  status: 200,
  json: async () => ({ access: "tok", expires_in: 900 }),
} as unknown as Response;

function stubFetch(tokenResponse: Response) {
  const fetchMock = vi.fn((url: string) => {
    if (url === "/accounts/token/") return Promise.resolve(tokenResponse);
    if (url === "/api/threads") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          threads: [
            { id: "t1", title: "Baltic energy", created_at: "2026-09-18T10:00:00Z" },
          ],
          quota: { used: 6, limit: 20 },
        }),
      } as unknown as Response);
    }
    if (url === "/api/threads/t1") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          thread_id: "t1",
          messages: [
            { role: "user", text: "earlier question" },
            { role: "assistant", text: "earlier answer" },
          ],
        }),
      } as unknown as Response);
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(controller) {
          controller.close();
        },
      }),
    } as unknown as Response);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the app shell", () => {
  it("authenticates on mount and renders the chat when ready", async () => {
    stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    expect(await screen.findByRole("button", { name: "Send" })).toBeTruthy();
  });

  it("a token-service outage offers a retry instead of a dead sign-in state", async () => {
    let status = 502;
    stubFetch({
      get ok() {
        return status < 400;
      },
      status,
      json: async () => ({}),
    } as unknown as Response);
    const App = await importApp();
    render(<App />);
    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    status = 200;
    await act(async () => {
      fireEvent.click(retry);
    });
    expect(await screen.findByRole("button", { name: "Send" })).toBeTruthy();
  });

  it("a 401 renders the sign-in state", async () => {
    stubFetch({ ok: false, status: 401, json: async () => ({}) } as unknown as Response);
    const App = await importApp();
    render(<App />);
    expect(await screen.findByText("Sign in required.")).toBeTruthy();
    // The gate screen must still carry a page heading for screen readers.
    expect(screen.getByRole("heading", { name: "PoliticalAgent" })).toBeTruthy();
  });

  it("the New conversation control resets the conversation", async () => {
    const fetchMock = stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByRole("button", { name: "Send" });
    const input = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.submit(input.closest("form")!);
    expect(await screen.findByText("hello")).toBeTruthy();
    // The completed turn's refresh must land inside this test: a promise that
    // outlives the test would fire against the next test's unstubbed fetch.
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads").length).toBe(2);
    });
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByText("hello")).toBeNull();
  });

  it("the sidebar lists threads and reflects the quota meter", async () => {
    stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByRole("button", { name: "Send" });
    expect(await screen.findByText("Baltic energy")).toBeTruthy();
    expect(screen.getByText("6 of 20")).toBeTruthy();
  });

  it("selecting a thread issues one read and replaces the conversation", async () => {
    const fetchMock = stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByText("Baltic energy");
    fireEvent.click(screen.getByText("Baltic energy"));
    expect(await screen.findByText("earlier question")).toBeTruthy();
    expect(await screen.findByText("earlier answer")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads/t1").length).toBe(1);
  });

  it("the thread list and quota refresh after every completed turn", async () => {
    const fetchMock = stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByText("Baltic energy");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads").length).toBe(1);
    const input = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "next turn" } });
    fireEvent.submit(input.closest("form")!);
    await screen.findByText("next turn");
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads").length).toBe(2);
    });
  });
});
