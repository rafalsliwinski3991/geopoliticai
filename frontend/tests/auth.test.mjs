import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

// Static checks on the token bridge in the Alpine shell (unit 5). The bridge
// is deleted together with this file in unit 9; the React token module carries
// the same behaviour forward under `frontend/chat/`.
const html = await readFile(
  fileURLToPath(new URL("../index.html", import.meta.url)),
  "utf8",
);

function between(text, start, end) {
  const startIndex = text.indexOf(start);
  const endIndex = text.indexOf(end);
  assert.ok(startIndex !== -1, `${JSON.stringify(start)} not found`);
  assert.ok(endIndex !== -1, `${JSON.stringify(end)} not found`);
  assert.ok(startIndex < endIndex);
  return text.slice(startIndex, endIndex);
}

test("the token bridge fetches the token with the session cookie", () => {
  assert.match(html, /async function getAccessToken\(\)/);
  assert.match(
    html,
    /fetch\("\/accounts\/token\/", \{ credentials: "include" \}\)/,
  );
});

test("the bridge attaches the Authorization header to the stream request", () => {
  const fetchBlock = between(
    html,
    'fetch("/api/run_pipeline/stream"',
    "signal: controller.signal",
  );
  assert.match(fetchBlock, /Authorization: `Bearer \$\{await getAccessToken\(\)\}`/);
});

test("a 401 from the token endpoint redirects to login, once", () => {
  const bridge = between(
    html,
    "async function getAccessToken()",
    'document.addEventListener("alpine:init"',
  );
  assert.match(bridge, /window\.location\.href = "\/accounts\/login\/\?next=\/"/);
  assert.match(bridge, /sessionStorage\.getItem\("token-redirected"\)/);
  assert.match(bridge, /sessionStorage\.setItem\("token-redirected", "1"\)/);
  assert.match(bridge, /sessionStorage\.removeItem\("token-redirected"\)/);
});

test("the token is cached and re-fetched near expiry", () => {
  const bridge = between(
    html,
    "async function getAccessToken()",
    'document.addEventListener("alpine:init"',
  );
  assert.match(bridge, /accessTokenExpiry - 60_000/);
  assert.match(bridge, /data\.expires_in \* 1000/);
});

test("429 has friendly copy", () => {
  assert.match(html, /error_429: "You have used today's research turns\. Chat still works\."/);
  assert.match(html, /429: I18N\.error_429/);
});
