import { LOGIN_URL, getAccessToken } from "./token";

export type UploadedDocument = { filename: string; chunks: number };

const THREADS_URL = "/api/threads";

async function sendDocumentRequest(
  threadId: string,
  query: string,
  init: { method: string; contentType?: string; body?: File },
): Promise<Response> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (init.contentType) headers["Content-Type"] = init.contentType;
  const response = await fetch(`${THREADS_URL}/${threadId}/document${query}`, {
    method: init.method,
    headers,
    body: init.body,
  });
  if (response.status === 401) {
    // Same as the threads module: the redirect is the sign-in UX, the thrown
    // error just unwinds the caller's promise.
    window.location.assign(LOGIN_URL);
    throw new Error("Not authenticated");
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Document request failed (${response.status})`,
    );
  }
  return response;
}

export async function uploadDocument(
  threadId: string,
  file: File,
): Promise<UploadedDocument> {
  const response = await sendDocumentRequest(
    threadId,
    `?filename=${encodeURIComponent(file.name)}`,
    { method: "POST", contentType: "application/octet-stream", body: file },
  );
  return (await response.json()) as UploadedDocument;
}

export async function removeDocument(threadId: string): Promise<void> {
  await sendDocumentRequest(threadId, "", { method: "DELETE" });
}
