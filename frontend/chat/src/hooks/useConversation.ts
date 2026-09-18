import { useCallback, useState } from "react";
import { getAccessToken } from "../api/token";
import { HttpError, ServerEvent, streamTurn } from "../lib/sse";

export type Message =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; kind: "answer" | "report"; truncated: boolean }
  | { role: "error"; text: string };

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
      setIsLoading(true);
      setMessages((previous) => [...previous, { role: "user", text }]);
      try {
        const token = await getAccessToken();
        for await (const event of streamTurn(
          paused
            ? { resume: text, thread_id: threadId() }
            : { query: text, thread_id: threadId() },
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
        setIsLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [paused],
  );

  function threadId(): string {
    const KEY = "politicalagent.thread_id";
    const existing = localStorage.getItem(KEY);
    if (existing) return existing;
    const minted = crypto.randomUUID();
    localStorage.setItem(KEY, minted);
    return minted;
  }

  function handle(event: ServerEvent) {
    switch (event.type) {
      case "progress":
        setProgress((previous) => [...previous, { node: event.node, label: event.label }]);
        break;
      case "token":
        // Tokens stream into the last assistant message; a turn starts with
        // the result's text assembled from the streamed chunks.
        setMessages((previous) => {
          const last = previous[previous.length - 1];
          if (last && last.role === "assistant" && !last.text) {
            const copy = previous.slice(0, -1);
            return [
              ...copy,
              { ...last, text: event.content, kind: "answer" as const },
            ];
          }
          return [
            ...previous,
            {
              role: "assistant",
              text: event.content,
              kind: "answer" as const,
              truncated: false,
            },
          ];
        });
        break;
      case "pause":
        setPaused(true);
        setOutline(event.outline);
        setMessages((previous) => [
          ...previous,
          {
            role: "assistant",
            text: event.notice ?? "",
            kind: "answer",
            truncated: false,
          },
        ]);
        break;
      case "result":
        setPaused(false);
        setMessages((previous) => {
          const last = previous[previous.length - 1];
          if (last && last.role === "assistant" && last.text === event.output) {
            const copy = previous.slice(0, -1);
            return [
              ...copy,
              { ...last, kind: event.kind, truncated: event.truncated },
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
        setMessages((previous) => [
          ...previous,
          { role: "error", text: event.message ?? "Something went wrong. Please try again." },
        ]);
        break;
    }
  }

  return { messages, paused, outline, progress, isLoading, send };
}
