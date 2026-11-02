import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { Composer } from "./Composer";

const IDLE = {
  busy: false,
  uploading: false,
  document: null,
  onAttach: () => {},
  onDetach: () => {},
};
const REPORT = new File(["Q3 revenue was 41 million"], "report.txt", { type: "text/plain" });

describe("the composer", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("Enter submits and clears; Shift+Enter does not submit", () => {
    // Arrange
    const onSend = vi.fn();
    // Act
    render(<Composer {...IDLE} onSend={onSend} />);
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
    render(<Composer {...IDLE} onSend={onSend} />);
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
    render(<Composer {...IDLE} busy={true} onSend={onSend} />);
    const area = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(area, { target: { value: "hello" } });
    fireEvent.keyDown(area, { key: "Enter" });
    // Assert
    expect(onSend).not.toHaveBeenCalled();
    expect(area.value).toBe("hello");
  });

  it("choosing a file hands it to onAttach", () => {
    // Arrange
    const onAttach = vi.fn();
    render(<Composer {...IDLE} onSend={vi.fn()} onAttach={onAttach} />);
    const input = screen.getByLabelText("Attach a document") as HTMLInputElement;
    // Act
    fireEvent.change(input, { target: { files: [REPORT] } });
    // Assert
    expect(onAttach).toHaveBeenCalledWith(REPORT);
  });

  it("the file picker offers only PDF and text files", () => {
    // Arrange
    render(<Composer {...IDLE} onSend={vi.fn()} />);
    // Act
    const input = screen.getByLabelText("Attach a document") as HTMLInputElement;
    // Assert
    expect(input.getAttribute("accept")).toBe(".pdf,.txt,application/pdf,text/plain");
  });

  it("an upload in progress changes the placeholder and disables Send", () => {
    // Arrange
    render(<Composer {...IDLE} uploading={true} onSend={vi.fn()} />);
    // Act
    const placeholder = screen.queryByPlaceholderText("Reading your document…");
    const send = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
    // Assert
    expect(placeholder).toBeTruthy();
    expect(send.disabled).toBe(true);
  });

  it("an upload in progress ignores the submit key", () => {
    // Arrange
    const onSend = vi.fn();
    render(<Composer {...IDLE} uploading={true} onSend={onSend} />);
    const area = screen.getByLabelText("Ask a question") as HTMLTextAreaElement;
    fireEvent.change(area, { target: { value: "hello" } });
    // Act
    fireEvent.keyDown(area, { key: "Enter" });
    // Assert
    expect(onSend).not.toHaveBeenCalled();
  });

  it("an attached document shows its chip, and Remove calls onDetach", () => {
    // Arrange
    const onDetach = vi.fn();
    render(<Composer {...IDLE} document="report.txt" onSend={vi.fn()} onDetach={onDetach} />);
    // Act
    fireEvent.click(screen.getByRole("button", { name: "Remove document" }));
    // Assert
    expect(screen.getByText("report.txt")).toBeTruthy();
    expect(onDetach).toHaveBeenCalledTimes(1);
  });

  it("with no document attached there is no chip", () => {
    // Arrange
    render(<Composer {...IDLE} onSend={vi.fn()} />);
    // Act
    const chip = screen.queryByRole("button", { name: "Remove document" });
    // Assert
    expect(chip).toBeNull();
  });

  it("the footer says answers come from the document while one is attached", () => {
    // Arrange
    render(<Composer {...IDLE} document="report.txt" onSend={vi.fn()} />);
    // Act
    const footer = screen.queryByText(/Answers come from your document while one is attached\./);
    // Assert
    expect(footer).toBeTruthy();
  });
});
