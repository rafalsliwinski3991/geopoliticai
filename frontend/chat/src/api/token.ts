// The access token is held here and nowhere else — never localStorage, never a
// cookie (Q24, edge case 9). A reload re-fetches it from the session cookie,
// which is the credential that actually persists.
const TOKEN_URL = "/accounts/token/";
const LOGIN_URL = "/accounts/login/?next=/chat";
const REFRESH_MARGIN_MS = 60_000;

let token: string | null = null;
let expiresAt = 0;
let inFlight: Promise<string> | null = null;

export async function getAccessToken(): Promise<string> {
  if (token && Date.now() < expiresAt - REFRESH_MARGIN_MS) return token;
  // One shared promise: a page that fires the thread list and a turn at the
  // same moment must not mint two tokens.
  inFlight ??= fetchToken().finally(() => {
    inFlight = null;
  });
  return inFlight;
}

async function fetchToken(): Promise<string> {
  const response = await fetch(TOKEN_URL, { credentials: "include" });
  if (response.status === 401) {
    window.location.assign(LOGIN_URL);
    throw new Error("Not authenticated");
  }
  if (!response.ok) throw new Error(`Token request failed (${response.status})`);
  const data = (await response.json()) as { access: string; expires_in: number };
  token = data.access;
  expiresAt = Date.now() + data.expires_in * 1000;
  return token;
}
