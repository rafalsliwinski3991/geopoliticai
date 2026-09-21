import DOMPurify from "dompurify";
import { marked } from "marked";

export const ALLOWED_URI_REGEXP = /^https?:\/\//i;

// Escape for interpolation into a double-quoted attribute. DOMPurify parses
// its input as HTML, not as a URL or an attribute value, so sanitize() alone
// neither validates a URI nor escapes the quote that would close one.
function escapeAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

// The URI allow-list is the security behaviour the deleted security.test.mjs
// guarded: marked's link renderer must never emit a javascript: URL, no matter
// what the model returned. The outer renderMarkdown sanitize is a second
// layer, not the primary control.
marked.use({
  renderer: {
    link({ href, title, tokens }) {
      const text = this.parser.parseInline(tokens);
      if (!ALLOWED_URI_REGEXP.test(href)) return text;
      const titleAttr = title ? ` title="${escapeAttribute(title)}"` : "";
      return `<a href="${escapeAttribute(href)}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
    },
  },
});

export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false }), {
    ALLOWED_URI_REGEXP,
  });
}
