import { useCallback, useEffect, useState } from "react";
import { getAccessToken, TokenServiceError } from "./api/token";

type AuthState = "checking" | "ready" | "sign-in" | "error";

// Unit 8 ships the shell only: the composer, the conversation and the sidebar
// arrive with units 9 and 10. What must work here is the token path — the app
// cannot render a working turn without it, so it is fetched on mount rather
// than on the first send.
export default function App() {
  const [state, setState] = useState<AuthState>("checking");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getAccessToken()
      .then(() => {
        if (!cancelled) setState("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // A 401 redirects to the login page; the thrown error only unwinds
        // the promise. Anything else is a token-service outage, which a
        // reload should not be required to recover from.
        setState(error instanceof TokenServiceError ? "error" : "sign-in");
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setState("checking");
    setAttempt((n) => n + 1);
  }, []);

  return (
    <main>
      <h1>PoliticalAgent</h1>
      {state === "checking" ? (
        <p>Loading…</p>
      ) : state === "ready" ? (
        <p>Your conversations are kept to your account.</p>
      ) : state === "error" ? (
        <p>
          The sign-in check failed.{" "}
          <button onClick={retry}>Retry</button>
        </p>
      ) : (
        <p>Sign in required.</p>
      )}
    </main>
  );
}
