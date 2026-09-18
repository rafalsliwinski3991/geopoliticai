import { describe, expect, it } from "vitest";
import { TRUNCATED_NOTE, reportFileName } from "./MessageView";
import { renderMarkdown, ALLOWED_URI_REGEXP } from "../lib/markdown";

describe("report actions", () => {
  it("names the download -partial only when characters were dropped", () => {
    const date = new Date().toISOString().slice(0, 10);
    expect(reportFileName(true)).toBe(`report-${date}-partial.md`);
    expect(reportFileName(false)).toBe(`report-${date}.md`);
  });

  it("the truncated file body says what it is", () => {
    expect(TRUNCATED_NOTE).toContain("truncated at 50,000 characters");
  });
});

describe("markdown sanitization (was security.test.mjs)", () => {
  it("strips script tags from model text", () => {
    const html = renderMarkdown("hello <script>alert(1)</script>");
    expect(html).not.toContain("<script");
    expect(html).toContain("hello");
  });

  it("drops javascript: hrefs via the URI allow-list", () => {
    const html = renderMarkdown("[click](javascript:alert(1))");
    expect(html).not.toContain("javascript:");
  });

  it("keeps ordinary https links", () => {
    expect(ALLOWED_URI_REGEXP.test("https://reuters.com/x")).toBe(true);
    const html = renderMarkdown("[x](https://reuters.com)");
    expect(html).toContain("https://reuters.com");
  });
});

describe("product copy rules (was ux.test.mjs)", () => {
  const sources = import.meta.glob("./**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  it("keeps internal vocabulary out of the user-facing copy", () => {
    for (const [path, text] of Object.entries(sources)) {
      if (path.endsWith(".test.ts") || path.endsWith(".test.tsx")) continue;
      const lower = text.toLowerCase();
      expect(lower.includes("allow-listed"), path).toBe(false);
      expect(lower.includes("brave"), path).toBe(false);
    }
  });
});
