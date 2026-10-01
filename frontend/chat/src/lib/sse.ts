export type ServerEvent =
  | { type: "progress"; node: string; label: string }
  | { type: "token"; content: string }
  | {
      type: "pause";
      outline: string[];
      notice?: string;
      revisions_used?: number;
      revisions_allowed?: number;
    }
  | {
      type: "result";
      output: string;
      kind: "answer" | "report";
      truncated: boolean;
    }
  | { type: "error"; status?: number; message?: string };

export class HttpError extends Error {
  status: number;

  constructor(status: number, message?: string) {
    super(message ?? `Request failed (${status})`);
    this.status = status;
  }
}

// A forecast may run 14 minutes (brainstorm 2026Sep30 Q14), and the browser
// cannot know a turn's route before it asks, so every turn gets 15. nginx's
// 600s `proxy_read_timeout` is the silence allowed between two frames, not a
// total, and every long path emits progress well inside it. The 15-minute
// access token is checked once at request start, so a stream may outlive it —
// which is why header auth works here at all and why EventSource, which
// cannot send a header, must never be used (brainstorm §4.3).
const STREAM_TIMEOUT_MS = 15 * 60 * 1000;
const SSE_PREFIX = "data: ";

export async function* streamTurn(
  body: { query: string; thread_id: string } | { resume: string; thread_id: string },
  token: string,
): AsyncGenerator<ServerEvent> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS);
  try {
    const response = await fetch("/api/run_pipeline/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      signal: controller.signal,
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const detail = (await response.json().catch(() => ({}))) as { detail?: string };
      throw new HttpError(response.status, detail.detail);
    }
    if (response.body === null) {
      throw new Error("The stream arrived without a body.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // The last element is a partial line: a `data:` frame can split across
      // two network chunks, and parsing it early loses the event.
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith(SSE_PREFIX)) continue;
        try {
          yield JSON.parse(line.slice(SSE_PREFIX.length)) as ServerEvent;
        } catch {
          // malformed SSE line — skip, exactly as today
        }
      }
    }
  } finally {
    clearTimeout(timeout);
    // The consumer can abandon the generator (a break, or mid-stream unmount):
    // leaving the fetch body open would keep the backend generating into a
    // socket nobody reads. Aborting an already-finished request is a no-op.
    controller.abort();
  }
}
