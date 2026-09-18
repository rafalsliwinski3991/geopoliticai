import { useCallback, useState } from "react";
import { getAccessToken } from "../api/token";
import { HttpError, ServerEvent, streamTurn } from "../lib/sse";

export type Message =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      text: string;
      kind: "answer" | "report";
      truncated: boolean;
      streaming?: boolean;
    }
  | { role: "error"; text: string };

const THREAD_ID_KEY = "politicalagent.thread_id";

// Known pipeline failures get the action-oriented copy the deleted frontend
// translated before rendering; 429 keeps the backend's own message because the
// daily-limit text is already user-facing, and any unknown status falls back
// to the raw message.
const PIPELINE_ERROR_COPY: Record<number, string> = {
  409: "That report is no longer waiting for a decision. Ask again to start a new one.",
  422: "I couldn't find enough usable sources for that question. Try rephrasing it.",
  502: "Something went wrong while writing the answer. Please try again.",
  503: "The news search is temporarily unavailable. Please try again in a few minutes.",
};
const GENERIC_ERROR = "Something went wrong. Please try again.";

let memoryThreadId: string | null = null;

export function mintThreadId(): string {
  // `crypto.randomUUID` needs a secure context. Production is HTTPS and local
  // dev is localhost, both of which qualify; the fallback covers reaching a
  // dev box over plain HTTP on a LAN address. This value is a conversation
  // key, never a credential.
  const uuid = window.crypto?.randomUUID?.();
  if (uuid) return uuid;
  return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function storeThreadId(id: string): void {
  memoryThreadId = id;
  try {
    localStorage.setItem(THREAD_ID_KEY, id);
  } catch {
    // Storage can be unavailable (SecurityError when disabled or sandboxed):
    // the in-memory id above still applies for this session.
  }
}

export function loadThreadId(): string {
  try {
    const existing = localStorage.getItem(THREAD_ID_KEY);
    if (existing) return existing;
    const minted = mintThreadId();
    localStorage.setItem(THREAD_ID_KEY, minted);
    return minted;
  } catch {
    // Same unavailable-storage case: keep one in-memory id so consecutive
    // sends stay in the same conversation.
    memoryThreadId ??= mintThreadId();
    return memoryThreadId;
  }
}

// The paused rule the rewrite must preserve, stated so it cannot be lost:
// clear `paused` on a `result` and on an `error` with status 409; keep it on
// every other error and on any transport failure. A dropped connection says
// nothing about server state — clearing it would turn the retry into a
// `{query}` and destroy the pending report. A wrongly-kept `paused`
// self-corrects, because a stale `{resume}` draws a 409.
export function useConversation() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [paused, setPaused] = useState(false);
  const [outline, setOutline] = useState<string[]>([]);
  const [progress, setProgress] = useState<{ node: string; label: string }[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const send = useCallback(
    async (text: string) => {
      // A turn owns its progress list: stale steps from earlier turns must
      // not survive into it.
      setProgress([]);
      setIsLoading(true);
      setMessages((previous) => [...previous, { role: "user", text }]);
      try {
        const token = await getAccessToken();
        for await (const event of streamTurn(
          paused
            ? { resume: text, thread_id: loadThreadId() }
            : { query: text, thread_id: loadThreadId() },
          token,
        )) {
          handle(event);
        }
      } catch (error) {
        // Transport failure or an HTTP error before the stream opened. The
        // paused state is deliberately untouched: a stale `{resume}` draws a
        // 409, which is the case that clears it.
        setMessages((previous) => [
          ...previous,
          {
            role: "error",
            text: error instanceof HttpError && error.status
              ? error.message
              : `Connection error: ${error instanceof Error ? error.message : error}`,
          },
        ]);
      } finally {
        // Every way a turn can end must leave no message claiming to stream:
        // a turn that died mid-answer (dropped connection, timeout, error or
        // pause after tokens) otherwise leaks its flag into the next turn,
        // whose first token would be appended to the old bubble.
        setMessages((previous) =>
          previous.map((message) =>
            message.role === "assistant" && message.streaming
              ? { ...message, streaming: false }
              : message,
          ),
        );
        setIsLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [paused],
  );

  const reset = useCallback(() => {
    setMessages([]);
    setPaused(false);
    setOutline([]);
    setProgress([]);
    setIsLoading(false);
  }, []);

  function handle(event: ServerEvent) {
    switch (event.type) {
      case "progress":
        setProgress((previous) => [...previous, { node: event.node, label: event.label }]);
        break;
      case "token":
        // Tokens accumulate into the one assistant message the turn is
        // streaming; a chunk that arrives when no streaming message exists
        // starts it. The `result` frame carries the full text again and
        // replaces the streamed transcript wholesale.
        setMessages((previous) => {
          const last = previous[previous.length - 1];
          if (last && last.role === "assistant" && last.streaming) {
            const copy = previous.slice(0, -1);
            return [
              ...copy,
              { ...last, text: last.text + event.content },
            ];
          }
          return [
            ...previous,
            {
              role: "assistant",
              text: event.content,
              kind: "answer" as const,
              truncated: false,
              streaming: true,
            },
          ];
        });
        break;
      case "pause":
        setPaused(true);
        setOutline(event.outline);
        // The streamed draft stops being a draft; the notice below it is the
        // turn's real output.
        setMessages((previous) => {
          const last = previous[previous.length - 1];
          const closed =
            last && last.role === "assistant" && last.streaming
              ? [...previous.slice(0, -1), { ...last, streaming: false }]
              : previous;
          return [
            ...closed,
            {
              role: "assistant" as const,
              text: event.notice ?? "",
              kind: "answer" as const,
              truncated: false,
            },
          ];
        });
        break;
      case "result":
        setPaused(false);
        setMessages((previous) => {
          const last = previous[previous.length - 1];
          if (last && last.role === "assistant" && last.streaming) {
            const copy = previous.slice(0, -1);
            return [
              ...copy,
              {
                ...last,
                text: event.output,
                kind: event.kind,
                truncated: event.truncated,
                streaming: false,
              },
            ];
          }
          return [
            ...previous,
            {
              role: "assistant",
              text: event.output,
              kind: event.kind,
              truncated: event.truncated,
            },
          ];
        });
        break;
      case "error":
        if (event.status === 409) setPaused(false);
        // An error after tokens invalidates the partial answer: a hard
        // pipeline failure must not leave half an answer sitting in the
        // transcript as ordinary output.
        setMessages((previous) => {
          const last = previous[previous.length - 1];
          const kept =
            last && last.role === "assistant" && last.streaming
              ? previous.slice(0, -1)
              : previous;
          return [
            ...kept,
            {
              role: "error" as const,
              text: PIPELINE_ERROR_COPY[event.status ?? -1] ?? event.message ?? GENERIC_ERROR,
            },
          ];
        });
        break;
    }
  }

  return { messages, paused, outline, progress, isLoading, send, reset };
}
