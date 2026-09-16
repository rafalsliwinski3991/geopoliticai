import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const html = await readFile(
  fileURLToPath(new URL("../index.html", import.meta.url)),
  "utf8",
);

test("frontend sanitizes markdown before x-html", () => {
  // Assert
  assert.match(html, /DOMPurify\.sanitize/);
  assert.match(html, /dompurify@3\.4\.13/);
  assert.doesNotMatch(html, /dompurify@3\.4\.0/);
  assert.doesNotMatch(html, /dompurify@3\.2\.6/);
  assert.match(html, /ALLOWED_URI_REGEXP: \/\^https\?:\\\/\\\/\/i/);
  assert.match(html, /marked\.parse/);
});
