import { useEffect, useState } from "react";
import { getAccessToken } from "./api/token";

// Unit 8 ships the shell only: the composer, the conversation and the sidebar
// arrive with units 9 and 10. What must work here is the token path — the app
// cannot render a working turn without it.
export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAccessToken()
      .then(() => {
        if (!cancelled) setAuthenticated(true);
      })
      .catch(() => {
        if (!cancelled) setAuthenticated(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>PoliticalAgent</h1>
      {authenticated === null ? (
        <p>Loading…</p>
      ) : authenticated ? (
        <p>Your conversations are kept to your account.</p>
      ) : (
        <p>Sign in required.</p>
      )}
    </main>
  );
}
