import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { groupThreads, QuotaMeter, Sidebar } from "./Sidebar";
import type { ThreadSummary } from "../api/threads";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function thread(id: string, created_at: string): ThreadSummary {
  return { id, title: `${id} title`, created_at };
}

// Local noon, arbitrary day. The grouping must follow the viewer's local
// midnight, never UTC.
const NOON = new Date(2026, 8, 18, 12, 0, 0);

describe("groupThreads", () => {
  it("groups the three bands by local midnight", () => {
    // Arrange
    const groups = groupThreads(
      [
        thread("today", new Date(2026, 8, 18, 9, 0).toISOString()),
        thread("yesterday", new Date(2026, 8, 17, 23, 0).toISOString()),
        thread("earlier", new Date(2026, 8, 1, 0, 0).toISOString()),
      ],
      NOON,
    );
    // Assert
    expect(groups.today.map((t) => t.id)).toEqual(["today"]);
    expect(groups.yesterday.map((t) => t.id)).toEqual(["yesterday"]);
    expect(groups.earlier.map((t) => t.id)).toEqual(["earlier"]);
  });

  it("a thread stamped exactly at local midnight is today — the day just started", () => {
    // Arrange
    const midnight = new Date(2026, 8, 18, 0, 0, 0);
    const groups = groupThreads(
      [thread("midnight", midnight.toISOString())],
      NOON,
    );
    // Assert
    expect(groups.today.map((t) => t.id)).toEqual(["midnight"]);
    expect(groups.yesterday).toEqual([]);
  });

  it("one day before the boundary is yesterday even at the same clock time", () => {
    // Arrange
    const groups = groupThreads(
      [
        thread("same-week", new Date(2026, 8, 17, 12).toISOString()),
        thread("a-week-ago", new Date(2026, 8, 16, 12, 59).toISOString()),
      ],
      NOON,
    );
    // Assert
    expect(groups.yesterday.map((t) => t.id)).toEqual(["same-week"]);
    expect(groups.earlier.map((t) => t.id)).toEqual(["a-week-ago"]);
  });
});

describe("the sidebar", () => {
  it("an empty list renders the empty state and no headings", () => {
    // Act
    render(<Sidebar threads={[]} quota={{ used: 0, limit: 20 }} activeId={null} onOpen={() => {}} onNewChat={() => {}} now={NOON} />);
    // Assert
    expect(screen.getByText("No conversations yet. Ask something to start one.")).toBeTruthy();
    expect(screen.queryByText("Today")).toBeNull();
    expect(screen.queryByText("Yesterday")).toBeNull();
    expect(screen.queryByText("Earlier")).toBeNull();
  });

  it("renders the group headings and the newest-first thread rows", () => {
    // Act
    render(
      <Sidebar
        threads={[
          thread("a", new Date(2026, 8, 18, 9).toISOString()),
          thread("b", new Date(2026, 8, 17, 8).toISOString()),
          thread("c", new Date(2026, 8, 1, 7).toISOString()),
        ]}
        quota={{ used: 2, limit: 20 }}
        activeId="a"
        onOpen={() => {}}
        onNewChat={() => {}}
        now={NOON}
      />,
    );
    // Assert
    expect(screen.getByText("Today")).toBeTruthy();
    expect(screen.getByText("Yesterday")).toBeTruthy();
    expect(screen.getByText("Earlier")).toBeTruthy();
    const active = screen.getByRole("link", { name: /b title/ });
    expect(screen.getByRole("link", { name: /a title/ }).getAttribute("aria-current")).toBe("page");
    expect(active.getAttribute("aria-current")).toBeNull();
    // No turn count on the thread rows (§7): the time-of-day stamp only.
    expect(screen.queryByText(/\d+ turn/)).toBeNull();
  });

  it("selecting a thread opens it", () => {
    // Arrange
    const onOpen = vi.fn();
    // Act
    render(
      <Sidebar
        threads={[thread("a", new Date(2026, 8, 18, 9).toISOString())]}
        quota={{ used: 0, limit: 20 }}
        activeId="a"
        onOpen={onOpen}
        onNewChat={() => {}}
        now={NOON}
      />,
    );
    // Assert
    expect(
      screen.getByRole("link", { name: /a title/ }).getAttribute("aria-current"),
    ).toBe("page");
    fireEvent.click(screen.getByRole("link", { name: /a title/ }));
    expect(onOpen).toHaveBeenCalledWith("a");
  });

  it("a busy sidebar ignores selections — the streaming turn owns the screen", () => {
    const onOpen = vi.fn();
    const onNewChat = vi.fn();
    render(
      <Sidebar
        threads={[thread("a", new Date(2026, 8, 18, 9).toISOString())]}
        quota={{ used: 0, limit: 20 }}
        activeId={null}
        busy
        onOpen={onOpen}
        onNewChat={onNewChat}
        now={NOON}
      />,
    );
    expect((screen.getByRole("button", { name: "New conversation" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("link", { name: /a title/ }));
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(onOpen).not.toHaveBeenCalled();
    expect(onNewChat).not.toHaveBeenCalled();
  });

  it("the New conversation button calls onNewChat", () => {
    // Arrange
    const onNewChat = vi.fn();
    // Act
    render(
      <Sidebar
        threads={[]}
        quota={{ used: 0, limit: 20 }}
        activeId={null}
        onOpen={() => {}}
        onNewChat={onNewChat}
        now={NOON}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    // Assert
    expect(onNewChat).toHaveBeenCalled();
  });
});

describe("the quota meter", () => {
  it("renders the used and limit counts and the fill width", () => {
    // Act
    render(<QuotaMeter quota={{ used: 6, limit: 20 }} />);
    // Assert
    expect(screen.getByText("Research turns today")).toBeTruthy();
    expect(screen.getByText("6 of 20")).toBeTruthy();
    const fill = screen.getByRole("img", { name: "6 of 20 research turns used today" }).querySelector("i")!;
    expect(fill.style.width).toBe("30%");
  });

  it("a saturated meter is announced as such", () => {
    // Act
    render(<QuotaMeter quota={{ used: 20, limit: 20 }} />);
    // Assert
    expect(screen.getByText("20 of 20")).toBeTruthy();
    expect(
      screen.getByRole("img", { name: "Daily research limit reached" }).querySelector("i")!.style.width,
    ).toBe("100%");
  });

  it("the bootstrap zero-limit state is neutral, not reached", () => {
    // Before the first thread listing lands, App initializes quota to
    // {used: 0, limit: 0}: 0/0 is neither 30% wide nor a saturation warning.
    // Act
    render(<QuotaMeter quota={{ used: 0, limit: 0 }} />);
    // Assert
    expect(screen.getByText("0 of 0")).toBeTruthy();
    expect(screen.queryByRole("img", { name: "Daily research limit reached" })).toBeNull();
    const fill = screen.getByRole("img", { name: "0 of 0 research turns used today" }).querySelector("i")!;
    expect(fill.style.width).toBe("0%");
  });
});
