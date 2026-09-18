import DOMPurify from "dompurify";
import { marked } from "marked";

// The URI allow-list is the security behaviour the deleted security.test.mjs
// guarded: marked's link renderer must never emit a javascript: URL, no matter
// what the model returned.
marked.use({
  renderer: {
    link({ href, title, tokens }) {
      const text = this.parser.parseInline(tokens);
      const clean = DOMPurify.sanitize(href, { ALLOWED_URI_REGEXP });
      if (!clean) return text;
      const titleAttr = title ? ` title="${DOMPurify.sanitize(title)}"` : "";
      return `<a href="${clean}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
    },
  },
});

export const ALLOWED_URI_REGEXP = /^https?:\/\//i;

export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false }), {
    ALLOWED_URI_REGEXP,
  });
}
