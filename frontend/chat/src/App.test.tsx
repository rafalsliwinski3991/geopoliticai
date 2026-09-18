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
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url === "/accounts/token/") return Promise.resolve(tokenResponse);
      return Promise.resolve({
        ok: true,
        status: 200,
        body: new ReadableStream({
          start(controller) {
            controller.close();
          },
        }),
      } as unknown as Response);
    }),
  );
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
  });

  it("New chat resets the conversation", async () => {
    stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByRole("button", { name: "Send" });
    const input = screen.getByLabelText("Ask a question") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.submit(input.closest("form")!);
    expect(await screen.findByText("hello")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.queryByText("hello")).toBeNull();
  });
});
