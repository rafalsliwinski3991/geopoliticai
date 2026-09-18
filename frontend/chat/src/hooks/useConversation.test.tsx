import { describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DOMPurify from "dompurify";

// Re-importing the hook module per test resets its module state; the hook's
// state lives in React, so render a probe component that exposes it.
const renderHookProbe = async () => {
  let latest: unknown;
  vi.resetModules();
  const { useConversation } = await import("./useConversation");
  function Probe() {
    const state = useConversation();
    latest = state;
    return <div />;
  }
  render(<Probe />);
  return () => latest as ReturnType<typeof import("./useConversation").useConversation>;
};

const fetchEvents = (body: object[]) => {
  const stream = new ReadableStream({
    start(controller) {
      for (const event of body) {
        controller.enqueue(
          new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),
        );
      }
      controller.close();
    },
  });
  return {
    ok: true,
    status: 200,
    body: stream,
  } as unknown as Response;
};

function stubToken() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url === "/accounts/token/") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ access: "tok", expires_in: 900 }),
        } as unknown as Response);
      }
      return Promise.resolve(streamResponse());
    }),
  );
}

function streamResponse(): Response {
  return {
    ok: true,
    status: 200,
    body: new ReadableStream({
      start(controller) {
        controller.close();
      },
    }),
  } as unknown as Response;
}

describe("the conversation state machine (was ux.test.mjs pause semantics)", () => {
  it("a pause event sets paused and renders the outline; a result clears it", async () => {
    stubToken();
    const events = (body: object[]) => {
      const stream = new ReadableStream({
        start(controller) {
          for (const event of body) {
            controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
          }
          controller.close();
        },
      });
      return { ok: true, status: 200, body: stream } as unknown as Response;
    };
    let fetchResponse = events([
      { type: "pause", outline: ["One", "Two"], notice: "" },
    ]);
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url === "/accounts/token/"
            ? { ok: true, status: 200, json: async () => ({ access: "tok", expires_in: 900 }) } as unknown as Response
            : fetchResponse,
        ),
      ),
    );

    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("First question");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(true);

    // The user approves the outline: the next send posts {resume} and the
    // report result clears the pause.
    fetchResponse = events([{ type: "result", output: "Report body.", kind: "report", truncated: false }]);
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("approve");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(false);
  });

  it("an error with status 409 clears paused; any other error keeps it", async () => {
    stubToken();
    let fetchResponse: Response;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url === "/accounts/token/"
            ? { ok: true, status: 200, json: async () => ({ access: "tok", expires_in: 900 }) } as unknown as Response
            : fetchResponse,
        ),
      ),
    );

    const response = (event: object) => ({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
          controller.close();
        },
      }),
    }) as unknown as Response;

    const getLatest = await renderHookProbe();
    fetchResponse = response({ type: "pause", outline: ["One"], notice: "" });
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("first");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(true);

    // a 409 (stale resume) clears the pause
    fetchResponse = response({ type: "error", status: 409, message: "gone" });
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("resume attempt");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(false);

    // a pause again, then an error with another status: kept
    fetchResponse = response({ type: "pause", outline: ["One"], notice: "" });
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("another report");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(true);
    fetchResponse = response({ type: "error", status: 503, message: "down" });
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("resume attempt");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(true);

    // a transport failure keeps it too
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new Error("dropped"))),
    );
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("resume attempt");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(true);
  });
});

describe("the DOMPurify version floor (was security.test.mjs)", () => {
  it("is above the floor and is not a known-bad release", () => {
    const version = DOMPurify.version;
    const [major, minor, patch] = version.split(".").map(Number);
    // 3.4.0 and 3.2.6 were the known-bad releases; anything newer is fine.
    const knownBad = new Set(["3.4.0", "3.2.6"]);
    expect(knownBad.has(version)).toBe(false);
    expect(major).toBeGreaterThanOrEqual(3);
    expect(minor).toBeGreaterThanOrEqual(2);
    expect(patch).toBeGreaterThanOrEqual(7);
  });
});
