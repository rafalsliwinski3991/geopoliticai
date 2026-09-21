import { LOGIN_URL, getAccessToken } from "./token";

export type ThreadSummary = {
  id: string;
  title: string;
  created_at: string;
};

export type Quota = { used: number; limit: number };

export type ThreadListing = {
  threads: ThreadSummary[];
  quota: Quota;
};

export type StoredMessage = { role: "user" | "assistant"; text: string };

export type StoredThread = {
  thread_id: string;
  messages: StoredMessage[];
};

const THREADS_URL = "/api/threads";

async function fetchThreadResource<T>(path: string): Promise<T> {
  const token = await getAccessToken();
  const response = await fetch(`${THREADS_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.status === 401) {
    // A dead session behaves exactly as in the token module: the redirect is
    // the sign-in UX, the thrown error just unwinds the caller's promise.
    window.location.assign(LOGIN_URL);
    throw new Error("Not authenticated");
  }
  if (!response.ok) {
    throw new Error(`Thread request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function listThreads(): Promise<ThreadListing> {
  return fetchThreadResource("");
}

export async function readThread(threadId: string): Promise<StoredThread> {
  return fetchThreadResource(`/${threadId}`);
}
