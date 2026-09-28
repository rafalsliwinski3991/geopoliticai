import { describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DOMPurify from "dompurify";
import { storeThreadId } from "./useConversation";

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

// Helpers only.

// Renders every streamed turn event, recording the wire body of the POST so
// tests can assert whether the turn was a `{query}` or a `{resume}`.
function stubStreaming(payloads: object[][], postedBodies: unknown[] = []) {
  let index = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (url === "/accounts/token/") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ access: "tok", expires_in: 900 }),
        } as unknown as Response);
      }
      if (init?.body) postedBodies.push(JSON.parse(init.body as string));
      const events = payloads[Math.min(index, payloads.length - 1)];
      index += 1;
      const stream = new ReadableStream({
        start(controller) {
          for (const event of events) {
            controller.enqueue(
              new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),
            );
          }
          controller.close();
        },
      });
      return Promise.resolve({ ok: true, status: 200, body: stream } as unknown as Response);
    }),
  );
}

describe("streaming token display", () => {
  it("accumulates streamed tokens into one bubble that result replaces with the full output", async () => {
    stubStreaming([
      [
        { type: "token", content: "First half. " },
        { type: "token", content: "Second half." },
        { type: "result", output: "Full answer text.", kind: "answer", truncated: false },
      ],
    ]);
    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("What changed?");
    });
    const { messages } = getLatest() as {
      messages: { role: string; text: string; kind?: string }[];
    };
    const assistants = messages.filter((message) => message.role === "assistant");
    // One streamed bubble, not one per chunk, and no duplicated full text.
    expect(assistants).toHaveLength(1);
    expect(assistants[0]!.text).toBe("Full answer text.");
    expect(assistants[0]!.kind).toBe("answer");
  });
});

describe("turn boundaries", () => {
  it("an error frame after tokens drops the streaming draft and its status copy is friendly", async () => {
    stubStreaming([
      [
        { type: "token", content: "Partial" },
        { type: "error", status: 503, message: "raw server text" },
      ],
      [
        { type: "token", content: "Fresh." },
        { type: "result", output: "Fresh.", kind: "answer", truncated: false },
      ],
    ]);
    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("one");
    });
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("two");
    });
    const { messages } = getLatest() as {
      messages: { role: string; text: string }[];
    };
    const errors = messages.filter((message) => message.role === "error");
    const assistants = messages.filter((message) => message.role === "assistant");
    // Known statuses get the translated copy, not the raw message.
    expect(errors).toHaveLength(1);
    expect(errors[0]!.text).toBe(
      "The news search is temporarily unavailable. Please try again in a few minutes.",
    );
    // The interrupted turn's partial answer is gone and the next turn's
    // answer is its own bubble in the right place.
    expect(assistants).toHaveLength(1);
    expect(assistants[0]!.text).toBe("Fresh.");
  });

  it("a dropped connection leaves the flag cleared so the retry starts a fresh bubble", async () => {
    let calls = 0;
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
        calls += 1;
        if (calls === 1) {
          return Promise.resolve({
            ok: true,
            status: 200,
            body: new ReadableStream({
              start(controller) {
                controller.enqueue(
                  new TextEncoder().encode(
                    `data: ${JSON.stringify({ type: "token", content: "Partial" })}\n\n`,
                  ),
                );
                controller.error(new Error("dropped"));
              },
            }),
          } as unknown as Response);
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          body: new ReadableStream({
            start(controller) {
              controller.enqueue(
                new TextEncoder().encode(
                  `data: ${JSON.stringify({ type: "token", content: "Fresh." })}\n\ndata: ${JSON.stringify({ type: "result", output: "Fresh.", kind: "answer", truncated: false })}\n\n`,
                ),
              );
              controller.close();
            },
          }),
        } as unknown as Response);
      }),
    );
    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("one");
    });
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("retry");
    });
    const { messages } = getLatest() as {
      messages: { role: string; text: string }[];
    };
    const errors = messages.filter((message) => message.role === "error");
    const assistants = messages.filter((message) => message.role === "assistant");
    expect(errors).toHaveLength(1);
    expect(errors[0]!.text).toContain("Connection error");
    expect(assistants).toHaveLength(1);
    expect(assistants[0]!.text).toBe("Fresh.");
  });

  it("progress lists the running turn's steps", async () => {
    const frame = (event: object) =>
      new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`);
    let stream!: ReadableStreamDefaultController<Uint8Array>;
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
        return Promise.resolve({
          ok: true,
          status: 200,
          // Stays open after the progress frame: the turn is still running.
          body: new ReadableStream<Uint8Array>({
            start(controller) {
              stream = controller;
              controller.enqueue(frame({ type: "progress", node: "a", label: "Step" }));
            },
          }),
        } as unknown as Response);
      }),
    );
    const getLatest = await renderHookProbe();
    let turn!: Promise<void>;
    act(() => {
      turn = getLatest().send("one");
    });
    await vi.waitFor(() =>
      expect(getLatest().progress).toEqual([{ node: "a", label: "Step" }]),
    );
    await act(async () => {
      stream.enqueue(frame({ type: "result", output: "A", kind: "answer", truncated: false }));
      stream.close();
      await turn;
    });
    expect(getLatest().progress).toEqual([]);
  });

  it("progress never carries a finished turn's steps", async () => {
    stubStreaming([
      [
        { type: "progress", node: "a", label: "Turn one step" },
        { type: "result", output: "A", kind: "answer", truncated: false },
      ],
      [
        { type: "progress", node: "b", label: "Turn two step" },
        { type: "result", output: "B", kind: "answer", truncated: false },
      ],
    ]);
    const seen: string[][] = [];
    let latest: unknown;
    vi.resetModules();
    const { useConversation } = await import("./useConversation");
    function Probe() {
      const state = useConversation();
      latest = state;
      seen.push(state.progress.map((step) => step.label));
      return <div />;
    }
    render(<Probe />);
    const send = (text: string) =>
      (latest as ReturnType<typeof useConversation>).send(text);
    await act(async () => {
      await send("one");
    });
    expect((latest as ReturnType<typeof useConversation>).progress).toEqual([]);
    const turnOneRenders = seen.length;
    await act(async () => {
      await send("two");
    });
    expect((latest as ReturnType<typeof useConversation>).progress).toEqual([]);
    expect(seen.slice(turnOneRenders).flat()).not.toContain("Turn one step");
  });

  it("progress clears when the turn's answer arrives", async () => {
    stubStreaming([
      [
        { type: "progress", node: "a", label: "Step" },
        { type: "result", output: "A", kind: "answer", truncated: false },
      ],
    ]);
    const getLatest = await renderHookProbe();
    await act(async () => {
      await getLatest().send("one");
    });
    expect(getLatest().progress).toEqual([]);
  });

  it("progress clears when a turn ends in an error frame", async () => {
    stubStreaming([
      [
        { type: "progress", node: "a", label: "Step" },
        { type: "error", status: 502, message: "bad" },
      ],
    ]);
    const getLatest = await renderHookProbe();
    await act(async () => {
      await getLatest().send("one");
    });
    expect(getLatest().progress).toEqual([]);
  });

  it("progress clears when a turn pauses", async () => {
    stubStreaming([
      [
        { type: "progress", node: "a", label: "Step" },
        { type: "pause", outline: ["One"], notice: "" },
      ],
    ]);
    const getLatest = await renderHookProbe();
    await act(async () => {
      await getLatest().send("one");
    });
    expect(getLatest().progress).toEqual([]);
    expect(getLatest().paused).toBe(true);
  });

  it("a 429 error frame keeps the backend's own message", async () => {
    stubStreaming([
      [{ type: "error", status: 429, message: "Daily limit of 20 research turns reached." }],
    ]);
    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("one");
    });
    const { messages } = getLatest() as {
      messages: { role: string; text: string }[];
    };
    expect(messages.at(-1)).toEqual({
      role: "error",
      text: "Daily limit of 20 research turns reached.",
    });
  });

  it("falls back to one in-memory thread id when localStorage is unavailable", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
      setItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
    });
    const postedBodies: unknown[] = [];
    stubStreaming(
      [
        [{ type: "result", output: "A", kind: "answer", truncated: false }],
        [{ type: "result", output: "B", kind: "answer", truncated: false }],
      ],
      postedBodies,
    );
    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("one");
    });
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("two");
    });
    vi.unstubAllGlobals();
    const bodies = postedBodies as { thread_id?: string }[];
    expect(bodies[0]!.thread_id).toBeTruthy();
    expect(bodies[1]!.thread_id).toBe(bodies[0]!.thread_id);
  });

  it("storeThreadId switches the conversation key for the next turn", async () => {
    localStorage.removeItem("politicalagent.thread_id");
    const postedBodies: unknown[] = [];
    stubStreaming(
      [
        [{ type: "result", output: "A", kind: "answer", truncated: false }],
        [{ type: "result", output: "B", kind: "answer", truncated: false }],
      ],
      postedBodies,
    );
    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("one");
    });
    await act(async () => {
      storeThreadId("t-brand-new");
    });
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("two");
    });
    const bodies = postedBodies as { thread_id?: string }[];
    expect(bodies[1]!.thread_id).toBe("t-brand-new");
  });

  it("reset clears the conversation state", async () => {
    stubStreaming([[{ type: "pause", outline: ["One"], notice: "" }]]);
    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("one");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(true);
    await act(async () => {
      (getLatest() as { reset: () => void }).reset();
    });
    const state = getLatest() as {
      messages: unknown[];
      paused: boolean;
      progress: unknown[];
    };
    expect(state.messages).toEqual([]);
    expect(state.paused).toBe(false);
    expect(state.progress).toEqual([]);
  });
});

describe("the paused wire body", () => {
  it("posts {resume} while paused and {query} otherwise", async () => {
    const postedBodies: unknown[] = [];
    stubStreaming([
      [{ type: "pause", outline: ["One"], notice: "" }],
      [{ type: "result", output: "Report.", kind: "report", truncated: false }],
    ], postedBodies);
    const getLatest = await renderHookProbe();
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("ask");
    });
    expect((getLatest() as { paused: boolean }).paused).toBe(true);
    await act(async () => {
      await (getLatest() as { send: (t: string) => Promise<void> }).send("approve");
    });
    const bodies = postedBodies as { query?: string; resume?: string; thread_id?: string }[];
    expect(bodies[0]).toEqual({ query: "ask", thread_id: bodies[0]!.thread_id });
    expect(bodies[0]!.resume).toBeUndefined();
    expect(bodies[1]!.resume).toBe("approve");
    expect(bodies[1]!.query).toBeUndefined();
    // The same thread id persists across both turns.
    expect(bodies[1]!.thread_id).toBe(bodies[0]!.thread_id);
  });
});

describe("the DOMPurify version floor (was security.test.mjs)", () => {
  it("is above the floor and is not a known-bad release", () => {
    const version = DOMPurify.version;
    const knownBad = new Set(["3.4.0", "3.2.6"]);
    // Anything strictly later than 3.2.6 in semver order is acceptable; the
    // known-bad releases must never reappear.
    expect(knownBad.has(version)).toBe(false);
    expect(versionGreater(version, "3.2.6")).toBe(true);
  });
});

function versionGreater(actual: string, floor: string): boolean {
  const [a, b, c] = actual.split(".").map(Number);
  const [x, y, z] = floor.split(".").map(Number);
  if ((a ?? 0) !== (x ?? 0)) return (a ?? 0) > (x ?? 0);
  if ((b ?? 0) !== (y ?? 0)) return (b ?? 0) > (y ?? 0);
  return (c ?? 0) > (z ?? 0);
}
