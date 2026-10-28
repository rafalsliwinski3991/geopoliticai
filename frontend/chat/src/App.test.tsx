import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, act, fireEvent, cleanup } from "@testing-library/react";

// app.test must re-import the app per test: the token module inside it keeps
// module-level state that must not leak between tests.
const importApp = async () => (await import("./App")).default;

const WELCOME_INTRO =
  "I am PoliticalAgent, a geopolitical research assistant. I can run quick source-backed research, in-depth analyses, Delphi council forecasts, and structured reports from our conversation.";
const WELCOME_POLISH_NOTE = "Możesz rozmawiać ze mną po angielsku lub po polsku.";

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
  // The stored conversation key outlives a test: a later test in this file
  // must not inherit it and replay an unrelated transcript.
  window.localStorage.removeItem("politicalagent.thread_id");
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

  it("a new conversation shows the welcome message, which is not an article", async () => {
    // Arrange
    stubFetch(tokenOk);
    const App = await importApp();

    // Act
    render(<App />);
    await screen.findByRole("button", { name: "Send" });

    // Assert
    expect(screen.getByText(WELCOME_INTRO)).toBeTruthy();
    expect(screen.getByText(WELCOME_POLISH_NOTE)).toBeTruthy();
    expect(screen.queryAllByRole("article")).toEqual([]);
  });

  it("the welcome message disappears once a message is sent", async () => {
    // Arrange
    const fetchMock = stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByRole("button", { name: "Send" });
    const input = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;

    // Act
    fireEvent.change(input, { target: { value: "Cześć" } });
    fireEvent.submit(input.closest("form")!);

    // Assert
    expect(await screen.findByText("Cześć")).toBeTruthy();
    expect(screen.queryByText(WELCOME_POLISH_NOTE)).toBeNull();
    // The completed turn's refresh must land inside this test: a promise that
    // outlives the test would fire against the next test's unstubbed fetch.
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads").length).toBe(2);
    });
  });

  it("the welcome message returns after a new conversation is started", async () => {
    // Arrange
    const fetchMock = stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByRole("button", { name: "Send" });
    const input = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.submit(input.closest("form")!);
    await screen.findByText("hello");
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads").length).toBe(2);
    });

    // Act
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));

    // Assert
    expect(screen.getByText(WELCOME_POLISH_NOTE)).toBeTruthy();
  });

  it("the welcome message stays hidden when a saved conversation is reopened", async () => {
    // Arrange
    stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByRole("link", { name: /Baltic energy/ });

    // Act
    fireEvent.click(screen.getByRole("link", { name: /Baltic energy/ }));
    await screen.findByText("earlier answer");

    // Assert
    expect(screen.queryByText(WELCOME_POLISH_NOTE)).toBeNull();
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

  it("the sidebar is inert while a turn is still streaming", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/accounts/token/") return Promise.resolve(tokenOk);
        if (url === "/api/threads") {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ threads: [], quota: { used: 0, limit: 20 } }),
          } as unknown as Response);
        }
        // A stream that never finishes: the turn stays in flight.
        return Promise.resolve({
          ok: true,
          status: 200,
          body: new ReadableStream({
            start() {
              // Never closes: the turn stays in flight for the whole test.
            },
          }),
        } as unknown as Response);
      }),
    );
    const App = await importApp();
    render(<App />);
    await screen.findByRole("button", { name: "Send" });
    const input = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "long turn" } });
    fireEvent.submit(input.closest("form")!);
    const newChat = await screen.findByRole("button", { name: "New conversation" });
    expect((newChat as HTMLButtonElement).disabled).toBe(true);
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
    await screen.findByRole("link", { name: /Baltic energy/ });
    fireEvent.click(screen.getByRole("link", { name: /Baltic energy/ }));
    expect(await screen.findByText("earlier question")).toBeTruthy();
    expect(await screen.findByText("earlier answer")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads/t1").length).toBe(1);
    // The selected row carries the mockup's marker (chat.html:186-188).
    expect(
      (
        await screen.findByRole("link", { name: /Baltic energy/ })
      ).getAttribute("aria-current"),
    ).toBe("page");
  });

  it("a reload restores the stored conversation's messages, not just its heading", async () => {
    // A previous session left the thread id behind: the reload must re-read
    // the transcript from the threads API on the first listing, without a
    // sidebar click.
    window.localStorage.setItem("politicalagent.thread_id", "t1");
    const fetchMock = stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    expect(await screen.findByText("earlier question")).toBeTruthy();
    expect(await screen.findByText("earlier answer")).toBeTruthy();
    // The heading comes from the listing's match; the transcript from the
    // one read this reload triggers.
    expect(screen.getByRole("heading", { name: "Baltic energy" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Baltic energy/ }).getAttribute("aria-current")).toBe(
      "page",
    );
    // Exactly one read: the post-turn refresh must not replay the transcript
    // over a live conversation.
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads/t1").length).toBe(1);
  });

  it("a turn starting while the reload restore is pending discards the restore", async () => {
    // The restore read hangs until this test resolves it: the user submits
    // first, and the late transcript must not overwrite the live turn.
    let resolveRead: (value: unknown) => void = () => {};
    window.localStorage.setItem("politicalagent.thread_id", "t1");
    const fetchMock = vi.fn((url: string) => {
      if (url === "/accounts/token/") return Promise.resolve(tokenOk);
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
        return new Promise((resolve) => {
          resolveRead = resolve;
        });
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
    const App = await importApp();
    render(<App />);
    await screen.findByRole("button", { name: "Send" });
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads/t1").length).toBe(1),
    );
    const input = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.submit(input.closest("form")!);
    await screen.findByText("hello");
    await act(async () => {
      resolveRead({
        ok: true,
        status: 200,
        json: async () => ({
          thread_id: "t1",
          messages: [
            { role: "user", text: "earlier question" },
            { role: "assistant", text: "earlier answer" },
          ],
        }),
      });
    });
    expect(screen.queryByText("earlier question")).toBeNull();
    expect(screen.getByText("hello")).toBeTruthy();
  });

  it("the thread list and quota refresh after every completed turn", async () => {
    const fetchMock = stubFetch(tokenOk);
    const App = await importApp();
    render(<App />);
    await screen.findByRole("link", { name: /Baltic energy/ });
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads").length).toBe(1);
    const input = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "next turn" } });
    fireEvent.submit(input.closest("form")!);
    await screen.findByText("next turn");
    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.filter(([url]) => url === "/api/threads").length).toBe(2);
    });
  });

  describe("mobile conversation drawer", () => {
    const openDrawer = async () => {
      stubFetch(tokenOk);
      const App = await importApp();
      render(<App />);
      await screen.findByRole("link", { name: /Baltic energy/ });
      const toggle = screen.getByRole("button", { name: "Chats" });
      fireEvent.click(toggle);
      return toggle;
    };
    const drawer = () => screen.getByRole("complementary");

    it("the Chats toggle opens and closes the conversation drawer", async () => {
      stubFetch(tokenOk);
      const App = await importApp();
      render(<App />);
      await screen.findByRole("link", { name: /Baltic energy/ });
      const toggle = screen.getByRole("button", { name: "Chats" });
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
      expect(toggle.getAttribute("aria-controls")).toBe("chat-sidebar");
      fireEvent.click(toggle);
      expect(toggle.getAttribute("aria-expanded")).toBe("true");
      expect(drawer().classList.contains("open")).toBe(true);
      fireEvent.click(toggle);
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
      expect(drawer().classList.contains("open")).toBe(false);
    });

    it("choosing a thread or a new conversation closes the drawer", async () => {
      const toggle = await openDrawer();
      fireEvent.click(screen.getByRole("link", { name: /Baltic energy/ }));
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
      fireEvent.click(toggle);
      expect(toggle.getAttribute("aria-expanded")).toBe("true");
      fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
    });

    it("opening the drawer mid-turn still moves focus into it", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn((url: string) => {
          if (url === "/accounts/token/") return Promise.resolve(tokenOk);
          if (url === "/api/threads") {
            return Promise.resolve({
              ok: true,
              status: 200,
              json: async () => ({ threads: [], quota: { used: 0, limit: 20 } }),
            } as unknown as Response);
          }
          return Promise.resolve({
            ok: true,
            status: 200,
            body: new ReadableStream({ start() {} }),
          } as unknown as Response);
        }),
      );
      const App = await importApp();
      render(<App />);
      await screen.findByRole("button", { name: "Send" });
      const input = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
      fireEvent.change(input, { target: { value: "long turn" } });
      fireEvent.submit(input.closest("form")!);
      await vi.waitFor(() =>
        expect(
          (screen.getByRole("button", { name: "New conversation" }) as HTMLButtonElement)
            .disabled,
        ).toBe(true),
      );
      fireEvent.click(screen.getByRole("button", { name: "Chats" }));
      expect(document.activeElement).toBe(drawer());
    });

    it("leaving the mobile breakpoint closes the drawer", async () => {
      let notify: (event: { matches: boolean }) => void = () => {};
      vi.stubGlobal(
        "matchMedia",
        vi.fn(() => ({
          matches: true,
          addEventListener: (_: string, listener: typeof notify) => {
            notify = listener;
          },
          removeEventListener: () => {},
        })),
      );
      const toggle = await openDrawer();
      expect(toggle.getAttribute("aria-expanded")).toBe("true");
      act(() => notify({ matches: false }));
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
    });

    it("Escape and the backdrop close the drawer", async () => {
      const toggle = await openDrawer();
      fireEvent.keyDown(document, { key: "Escape" });
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
      fireEvent.click(toggle);
      fireEvent.click(screen.getByTestId("drawer-backdrop"));
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
    });

    it("an open drawer makes the conversation inert and takes focus", async () => {
      const toggle = await openDrawer();
      const main = document.querySelector("main")!;
      expect(main.hasAttribute("inert")).toBe(true);
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "New conversation" }),
      );
      fireEvent.keyDown(document, { key: "Escape" });
      expect(main.hasAttribute("inert")).toBe(false);
      expect(document.activeElement).toBe(toggle);
    });
  });
});
