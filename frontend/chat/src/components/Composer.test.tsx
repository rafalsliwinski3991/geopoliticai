import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { Composer } from "./Composer";

describe("the composer", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("Enter submits and clears; Shift+Enter does not submit", () => {
    // Arrange
    const onSend = vi.fn();
    // Act
    render(<Composer busy={false} onSend={onSend} />);
    const area = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(area, { target: { value: "hello" } });
    fireEvent.keyDown(area, { key: "Enter", shiftKey: true });
    // Assert
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(area, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("hello");
    expect(area.value).toBe("");
  });

  it("a pending IME composition does not submit on Enter", () => {
    // Arrange
    const onSend = vi.fn();
    // Act
    render(<Composer busy={false} onSend={onSend} />);
    const area = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(area, { target: { value: "こんにちは" } });
    // fireEvent cannot set isComposing (it silently drops unknown init), so a
    // real KeyboardEvent carries the composing flag — as the browser does.
    area.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        isComposing: true,
        bubbles: true,
        cancelable: true,
      }),
    );
    // Assert
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(area, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("こんにちは");
  });

  it("a busy composer ignores the submit key", () => {
    // Arrange
    const onSend = vi.fn();
    // Act
    render(<Composer busy={true} onSend={onSend} />);
    const area = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(area, { target: { value: "hello" } });
    fireEvent.keyDown(area, { key: "Enter" });
    // Assert
    expect(onSend).not.toHaveBeenCalled();
    expect(area.value).toBe("hello");
  });
});
