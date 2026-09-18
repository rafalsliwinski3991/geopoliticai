import { useCallback, useEffect, useState } from "react";
import { getAccessToken, TokenServiceError } from "./api/token";
import { mintThreadId, storeThreadId, useConversation } from "./hooks/useConversation";
import { Composer } from "./components/Composer";
import { MessageView, OutlineCard } from "./components/MessageView";

type AuthState = "checking" | "ready" | "sign-in" | "error";

export default function App() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [attempt, setAttempt] = useState(0);
  const { messages, paused, outline, progress, isLoading, send, reset } = useConversation();

  // Authenticate on mount, not on the first send: a login redirect that
  // waits for a submitted message would discard that message.
  useEffect(() => {
    let cancelled = false;
    getAccessToken()
      .then(() => {
        if (!cancelled) setAuth("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // A 401 redirects to the login page; the thrown error only unwinds
        // the promise. Anything else is a token-service outage, which must
        // not permanently mark the session unauthenticated.
        setAuth(error instanceof TokenServiceError ? "error" : "sign-in");
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setAuth("checking");
    setAttempt((n) => n + 1);
  }, []);

  // A fresh conversation key and a clean slate: without this, changing topics
  // keeps feeding every turn to the same LangGraph checkpoint.
  const newChat = useCallback(() => {
    storeThreadId(mintThreadId());
    reset();
  }, [reset]);

  if (auth !== "ready") {
    return (
      <main>
        <h1>PoliticalAgent</h1>
        {auth === "checking" ? (
          <p>Loading…</p>
        ) : auth === "error" ? (
          <p>
            The sign-in check failed. <button onClick={retry}>Retry</button>
          </p>
        ) : (
          <p>Sign in required.</p>
        )}
      </main>
    );
  }

  return (
    <main>
      <h1>PoliticalAgent</h1>
      <section aria-label="Conversation">
        {messages.map((message, index) => (
          <MessageView key={index} message={message} />
        ))}
        {progress.length > 0 && (
          <ul aria-label="Progress">
            {progress.map((step, index) => (
              <li key={index}>{step.label}</li>
            ))}
          </ul>
        )}
        {paused && <OutlineCard outline={outline} />}
      </section>
      <Composer busy={isLoading} onSend={send} />
      <button onClick={newChat} disabled={isLoading}>
        New chat
      </button>
    </main>
  );
}
