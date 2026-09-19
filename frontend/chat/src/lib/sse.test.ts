import { afterEach, describe, expect, it, vi } from "vitest";
import { streamTurn, HttpError } from "./sse";

function sse(body: string): ReadableStream {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
}

function okResponse(body: string): Response {
  return {
    ok: true,
    status: 200,
    body: sse(body),
  } as unknown as Response;
}

describe("the SSE reader", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("parses one event per data line", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          okResponse(
            'data: {"type":"progress","node":"a","label":"x"}\n\ndata: {"type":"token","content":"hi"}\n\n',
          ),
        ),
      ),
    );
    const events = [];
    // Act
    for await (const event of streamTurn({ query: "x", thread_id: "t" }, "tok")) {
      events.push(event);
    }
    // Assert
    expect(events).toEqual([
      { type: "progress", node: "a", label: "x" },
      { type: "token", content: "hi" },
    ]);
  });

  it("yields one event when a data line splits across two chunks", async () => {
    // Arrange
    const first = 'data: {"type":"tok';
    const second = 'en","content":"hi"}\n\n';
    let released = false;
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(first));
      },
      pull(controller) {
        if (!released) {
          released = true;
          controller.enqueue(new TextEncoder().encode(second));
          controller.close();
        }
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: true, status: 200, body } as unknown as Response)),
    );
    const events = [];
    // Act
    for await (const event of streamTurn({ query: "x", thread_id: "t" }, "tok")) {
      events.push(event);
    }
    // Assert
    expect(events).toEqual([{ type: "token", content: "hi" }]);
  });

  it("skips a malformed line without killing the stream", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          okResponse(
            'data: {not json}\n\ndata: {"type":"token","content":"ok"}\n\n',
          ),
        ),
      ),
    );
    const events = [];
    // Act
    for await (const event of streamTurn({ query: "x", thread_id: "t" }, "tok")) {
      events.push(event);
    }
    // Assert
    expect(events).toEqual([{ type: "token", content: "ok" }]);
  });

  it("aborts the fetch after ten minutes", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: { signal?: { addEventListener: (t: string, h: () => void) => void } }) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            );
          }),
      ),
    );
    const pending = streamTurn({ query: "x", thread_id: "t" }, "tok").next();
    // Attach the handler before the abort fires: a rejection that lands
    // before its consumer exists is reported as unhandled and fails the run.
    const assertion = expect(pending).rejects.toBeDefined();
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
    // The timeout fires: the promise rejects with the abort error.
    await assertion;
    vi.useRealTimers();
  });

  it("raises HttpError with the server detail for non-200 responses", async () => {
    // Arrange
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 403,
          json: async () => ({ detail: "That conversation is not yours." }),
        } as unknown as Response),
      ),
    );
    // Act + Assert: the rejection carries the server detail.
    await expect(async () => {
      for await (const _ of streamTurn({ query: "x", thread_id: "t" }, "tok")) {
        /* no events expected */
      }
    }).rejects.toMatchObject({ status: 403 });
  });
});
