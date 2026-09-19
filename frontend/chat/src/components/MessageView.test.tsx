import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, act, cleanup, fireEvent } from "@testing-library/react";
import { MessageView, OutlineCard, TRUNCATED_NOTE, reportFileName } from "./MessageView";
import { renderMarkdown, ALLOWED_URI_REGEXP } from "../lib/markdown";

describe("report actions", () => {
  it("names the download -partial only when characters were dropped", () => {
    // Arrange
    const date = new Date().toISOString().slice(0, 10);
    // Assert
    expect(reportFileName(true)).toBe(`report-${date}-partial.md`);
    expect(reportFileName(false)).toBe(`report-${date}.md`);
  });

  it("the truncated file body says what it is", () => {
    // Assert
    expect(TRUNCATED_NOTE).toContain("truncated at 50,000 characters");
  });
});

describe("markdown sanitization (was security.test.mjs)", () => {
  it("strips script tags from model text", () => {
    // Arrange
    const html = renderMarkdown("hello <script>alert(1)</script>");
    // Assert
    expect(html).not.toContain("<script");
    expect(html).toContain("hello");
  });

  it("drops javascript: hrefs via the URI allow-list", () => {
    // Arrange
    const html = renderMarkdown("[click](javascript:alert(1))");
    // Assert
    expect(html).not.toContain("javascript:");
  });

  it("keeps ordinary https links", () => {
    // Assert
    expect(ALLOWED_URI_REGEXP.test("https://reuters.com/x")).toBe(true);
    const html = renderMarkdown("[x](https://reuters.com)");
    expect(html).toContain("https://reuters.com");
  });

  it("escapes the quote in a link title instead of closing the attribute", () => {
    // Arrange
    const html = renderMarkdown('[x](https://a "a\\" onmouseover=\\"alert(1) x=\\"")');
    // The injected quote became an entity inside the title value, so the
    // anchor survives with one attribute and no handler of its own.
    // Assert
    expect(html).toContain('title="a&quot; onmouseover=&quot;alert(1) x=&quot;"');
    expect(html).not.toContain('onmouseover="alert');
  });
});

describe("product copy rules (was ux.test.mjs)", () => {
  const sources = import.meta.glob("./**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  it("keeps internal vocabulary out of the user-facing copy", () => {
    // Arrange
    for (const [path, text] of Object.entries(sources)) {
      if (path.endsWith(".test.ts") || path.endsWith(".test.tsx")) continue;
      const lower = text.toLowerCase();
      // Assert
      expect(lower.includes("allow-listed"), path).toBe(false);
      expect(lower.includes("brave"), path).toBe(false);
      // No node names leak into user-facing copy either.
      for (const node of ["search_and_fetch", "classify", "expert", "reporter"]) {
        expect(lower.includes(node), path).toBe(false);
      }
    }
  });
});

describe("message rendering", () => {
  it("renders a user message as text, never as HTML", () => {
    // Act
    render(<MessageView message={{ role: "user", text: '<img src=x onerror="alert(1)">' }} />);
    // The markup is shown literally; no element was created from it.
    // Assert
    expect(document.querySelector("img")).toBeNull();
    screen.getByText('<img src=x onerror="alert(1)">');
  });
});

describe("report actions", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  const report = {
    role: "assistant",
    text: "Report body.",
    kind: "report",
    truncated: false,
  } as const;

  it("appends the download anchor to the document and defers the revoke", async () => {
    // Arrange
    const revoke = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:x", revokeObjectURL: revoke });
    // Act
    render(<MessageView message={report} />);
    fireEvent.click(screen.getByRole("button", { name: "Download .md" }));
    // The anchor was added for the click and is gone again.
    // Assert
    expect(document.querySelector("a[download]")).toBeNull();
    // Revoking in the same tick races the download; it must be deferred.
    expect(revoke).not.toHaveBeenCalled();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(revoke).toHaveBeenCalledWith("blob:x");
    vi.unstubAllGlobals();
  });

  it("resets the Copied label after two seconds", async () => {
    // Arrange
    vi.useFakeTimers();
    const write = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: write } });
    // Act
    render(<MessageView message={report} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await act(async () => {});
    // Assert
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
  });

  it("renders duplicate outline sections with unique keys", () => {
    // Arrange
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    // Act
    render(<OutlineCard outline={["Same", "Same"]} />);
    const items = screen.getAllByRole("listitem");
    // Assert
    expect(items).toHaveLength(2);
    expect(items.map((item) => item.textContent)).toEqual(["Same", "Same"]);
    // React logs "Duplicate keys" through console.error.
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});
