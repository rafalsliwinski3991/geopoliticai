import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DocumentChip } from "./DocumentChip";

const FILENAME = "Q3 report.pdf";

afterEach(() => {
  cleanup();
});

describe("DocumentChip", () => {
  it("shows the attached file's name", () => {
    // Arrange
    const onRemove = vi.fn();
    render(<DocumentChip filename={FILENAME} busy={false} onRemove={onRemove} />);
    // Act
    const name = screen.queryByText(FILENAME);
    // Assert
    expect(name).toBeTruthy();
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

  it("Remove is disabled while busy, so a running turn cannot lose its document", async () => {
    // Arrange
    const onRemove = vi.fn();
    render(<DocumentChip filename={FILENAME} busy={true} onRemove={onRemove} />);
    const remove = screen.getByRole("button", { name: "Remove document" }) as HTMLButtonElement;
    // Act
    await userEvent.click(remove);
    // Assert
    expect(remove.disabled).toBe(true);
    expect(onRemove).not.toHaveBeenCalled();
  });
});
