import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// Static checks on the frontend shell's user-facing behavior: the frontend is
// a single HTML file with no build step, so these tests assert on its source.
const FRONTEND_HTML = fileURLToPath(new URL("../index.html", import.meta.url));
const html = await readFile(FRONTEND_HTML, "utf8");

function between(text, start, end) {
  // Source slice from the first `start` anchor up to the first `end`
  // anchor, for asserting inside one method's body.
  const startIndex = text.indexOf(start);
  const endIndex = text.indexOf(end);
  assert.ok(startIndex !== -1, `${JSON.stringify(start)} not found`);
  assert.ok(endIndex !== -1, `${JSON.stringify(end)} not found`);
  assert.ok(startIndex < endIndex);
  return text.slice(startIndex, endIndex);
}

test("query input caps length at API limit", () => {
  // The input cannot submit more characters than the API accepts.
  assert.match(html, /maxlength="2000"/);
});

test("SSE error statuses map to friendly messages", () => {
  // Each known server error status has purpose-built copy, and the SSE
  // error branch renders it through the friendly-error helper.
  for (const key of ["error_422", "error_503", "error_502", "error_generic"]) {
    assert.match(html, new RegExp(`${key}:`));
  }
  assert.match(html, /function friendlySseError\(data\)/);
  assert.match(html, /friendlySseError\(data\)/);
});

test("friendly error copy is action oriented and jargon free", () => {
  // 422 offers rephrasing, 503 frames the outage as temporary, 502 and the
  // fallback ask to retry — and no internal vocabulary reaches the bubble.
  const lower = html.toLowerCase();
  assert.match(lower, /rephrasing it/);
  assert.match(lower, /temporarily unavailable/);
  assert.match(lower, /please try again/);
  assert.ok(!lower.includes("allow-listed"));
  assert.ok(!lower.includes("brave"));
});

test("frontend sends a sticky thread id", () => {
  // The frontend persists a conversation id and sends it to the API.
  assert.match(html, /THREAD_STORAGE_KEY/);
  assert.match(html, /localStorage\.getItem/);
  assert.match(html, /crypto\.randomUUID/);
  assert.match(html, /thread_id: this\.threadId/);
});

test("frontend offers a new chat button", () => {
  // The UI can reset the conversation to a freshly minted thread.
  assert.match(html, /newChat\(\)/);
  assert.match(html, /new_chat: "New chat"/);
  assert.match(html, /class="new-chat"/);
});

test("pause frame is handled and sets paused state", () => {
  // A `pause` frame flips the paused state and pushes the outline card.
  assert.match(html, /data\.type === "pause"/);
  assert.match(html, /this\.paused = true/);
});

test("input posts resume body while paused and query body otherwise", () => {
  // The request body is a union: a paused thread resumes, anything else
  // asks a fresh question.
  assert.match(html, /\{ resume: text, thread_id: this\.threadId \}/);
  assert.match(html, /\{ query: text, thread_id: this\.threadId \}/);
});

test("paused is cleared only where the pause is really gone", () => {
  // `paused` decides whether the next input posts `{resume}` or
  // `{query}`, and a `{query}` destroys the pending report. So it is
  // cleared only where the pause is provably gone: `newChat()`, a
  // delivered `result`, and an SSE error with status 409. Any other
  // error may be transient and leave the thread resumable, and a
  // wrongly-kept `paused` self-corrects in one round trip: the stale
  // `{resume}` draws a 409, which is the case that clears it. The
  // network `catch` clears nothing — a dropped connection or timeout
  // says nothing about server state.
  const newChat = html.indexOf("newChat() {");
  const sendMessage = html.indexOf("async sendMessage()");
  assert.ok(newChat !== -1);
  assert.ok(sendMessage !== -1);
  assert.ok(newChat < sendMessage);
  assert.match(html.slice(newChat, sendMessage), /this\.paused = false/);
  assert.match(
    between(html, 'data.type === "result"', 'data.type === "error"'),
    /this\.paused = false/,
  );

  const errorBranch = between(html, 'data.type === "error"', "} finally {");
  assert.equal(errorBranch.match(/this\.paused = false/g)?.length ?? 0, 1);
  assert.match(errorBranch, /if \(data\.status === 409\) this\.paused = false;/);

  const networkCatch = between(html, "} catch (error) {", "} finally {");
  assert.ok(!networkCatch.includes("this.paused = false"));
});

test("409 error status has friendly copy", () => {
  // A resume on a thread that is no longer paused is an expected failure,
  // so it gets purpose-built copy like the other known statuses.
  assert.match(html, /error_409:/);
  assert.match(html, /409: I18N\.error_409/);
});

test("report messages have download and copy actions", () => {
  // Report messages gain two client-side actions: a `.md` download —
  // named `-partial` when the report was truncated, whose file body itself
  // says what it is — and a copy button.
  assert.match(html, /downloadReport\(msg\)/);
  assert.match(html, /copyReport\(msg/);
  const downloadBody = between(html, "downloadReport(msg) {", "copyReport(msg, event) {");
  assert.match(downloadBody, /const body = msg\.truncated/);
  assert.match(downloadBody, /\[This report was truncated at 50,000 characters\.\]/);
  assert.match(downloadBody, /type: "text\/markdown/);
  assert.match(downloadBody, /report-\$\{stamp\}\.md/);
  assert.match(downloadBody, /-partial\.md/);
});

test("copy button captures event target before await", () => {
  // `currentTarget` is only set while the event is being dispatched, so
  // reading it after the clipboard await yields null and the button would
  // never say "Copied".
  const capture = html.indexOf("const button = event?.currentTarget;");
  const clipboardAwait = html.indexOf("await navigator.clipboard.writeText");
  assert.ok(capture !== -1);
  assert.ok(clipboardAwait !== -1);
  assert.ok(capture < clipboardAwait);
});

test("truncated notice copy is bound to reported truncation", () => {
  // The page flags a truncated report through purpose-built copy, shown
  // only when the result was both a report and truncated.
  assert.match(html, /truncated_notice:/);
  assert.match(html, /data\.kind === "report"/);
  assert.match(html, /msg\.report && msg\.truncated/);
});

test("outline card renders via x-text and guards the x-html binding", () => {
  // The outline carries model-produced text, so it renders through
  // `x-text` only — and because `x-show` hides an element without stopping
  // its bindings evaluating, the `x-html` binding must be ternary-guarded so
  // outline messages never reach `renderContent`.
  const outlineCard = html.indexOf('class="message outline"');
  const xHtmlBinding = html.indexOf("x-html=", outlineCard);
  const guard = html.indexOf("msg.role === 'outline' ? '' : renderContent(msg)");
  assert.ok(outlineCard !== -1);
  assert.ok(xHtmlBinding !== -1);
  assert.ok(guard !== -1);
  assert.ok(outlineCard < xHtmlBinding);
  assert.ok(xHtmlBinding < guard);
  const outlineSlice = html.slice(outlineCard, xHtmlBinding);
  assert.match(outlineSlice, /x-text/);
  assert.ok(!outlineSlice.includes("x-html"));
});
