import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DocumentChip } from "./DocumentChip";

const FILENAME = "Q3 report.pdf";

afterEach(() => {
  cleanup();
});

describe("DocumentChip", () => {
  it("shows the attached file's name", () => {
    // Arrange
    const onRemove = vi.fn();
    // Act
    render(<DocumentChip filename={FILENAME} busy={false} onRemove={onRemove} />);
    // Assert
    expect(screen.getByText(FILENAME)).toBeTruthy();
  });

  it("Remove calls onRemove once", () => {
    // Arrange
    const onRemove = vi.fn();
    render(<DocumentChip filename={FILENAME} busy={false} onRemove={onRemove} />);
    // Act
    fireEvent.click(screen.getByRole("button", { name: "Remove document" }));
    // Assert
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("Remove is disabled while busy, so a running turn cannot lose its document", () => {
    // Arrange
    const onRemove = vi.fn();
    // Act
    render(<DocumentChip filename={FILENAME} busy={true} onRemove={onRemove} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove document" }));
    // Assert
    expect(
      (screen.getByRole("button", { name: "Remove document" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(onRemove).not.toHaveBeenCalled();
  });
});
