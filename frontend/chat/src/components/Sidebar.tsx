import type { Quota, ThreadSummary } from "../api/threads";

// The three bands sort by the viewer's local midnight (the plan's §7 note:
// computed from created_at, no server grouping). A thread stamped exactly at
// local midnight is already today — the day has just started.
export function groupThreads(threads: ThreadSummary[], now: Date) {
  const start = (day: Date) =>
    new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime();
  const today = start(now);
  const yesterday = start(new Date(today - 1));
  const todayThreads: ThreadSummary[] = [];
  const yesterdayThreads: ThreadSummary[] = [];
  const earlierThreads: ThreadSummary[] = [];
  for (const thread of threads) {
    const created = new Date(thread.created_at).getTime();
    if (created >= today) {
      todayThreads.push(thread);
    } else if (created >= yesterday) {
      yesterdayThreads.push(thread);
    } else {
      earlierThreads.push(thread);
    }
  }
  return {
    today: todayThreads,
    yesterday: yesterdayThreads,
    earlier: earlierThreads,
  };
}

export function QuotaMeter({ quota }: { quota: Quota }) {
  // The bootstrap listing state is {used: 0, limit: 0}: 0/0 is neither a
  // percentage nor a saturation warning, so an unknown limit stays neutral.
  const known = quota.limit > 0;
  const saturated = known && quota.used >= quota.limit;
  const label = saturated
    ? "Daily research limit reached"
    : `${quota.used} of ${quota.limit} research turns used today`;
  const width = known
    ? `${Math.min(100, Math.round((quota.used / quota.limit) * 100))}%`
    : "0%";
  // CSS-embedded style: the mockup's meter is one flat <i> bar.
  return (
    <div className="quota-block">
      <div className="quota">
        <span>Research turns today</span>
        <span>
          {quota.used} of {quota.limit}
        </span>
      </div>
      <div className="meter" role="img" aria-label={label}>
        <i style={{ width }} />
      </div>
    </div>
  );
}

function clockTime(createdAt: string): string {
  return new Date(createdAt).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function Sidebar({
  threads,
  quota,
  activeId,
  busy,
  open = false,
  onOpen,
  onNewChat,
  now = new Date(),
}: {
  threads: ThreadSummary[];
  quota: Quota;
  activeId: string | null;
  // While a turn streams, the whole selection column is inert: dropping or
  // switching conversations mid-turn would let the still-running turn write
  // into the wrong conversation. This restores the guard the old "New chat"
  // button carried as disabled={isLoading}.
  busy: boolean;
  // Mobile drawer state; the desktop layout ignores it.
  open?: boolean;
  onOpen: (threadId: string) => void;
  onNewChat: () => void;
  now?: Date;
}) {
  const groups = groupThreads(threads, now);
  const band = (heading: string, items: ThreadSummary[]) =>
    items.length === 0 ? null : (
      <>
        <h2>{heading}</h2>
        {items.map((thread) => (
          <a
            key={thread.id}
            href="#"
            className="thread"
            aria-current={thread.id === activeId ? ("page" as const) : undefined}
            onClick={(event) => {
              event.preventDefault();
              if (busy) return;
              onOpen(thread.id);
            }}
            aria-disabled={busy}
          >
            {thread.title}
            <span className="when">{clockTime(thread.created_at)}</span>
          </a>
        ))}
      </>
    );

  return (
    <aside id="chat-sidebar" tabIndex={-1} className={open ? "side open" : "side"}>
      <div className="side-top">
        <a className="wordmark" href="/">
          Political<em>Agent</em>
        </a>
        <button className="new-thread" type="button" disabled={busy} onClick={onNewChat}>
          New conversation
        </button>
      </div>

      <nav className="threads" aria-label="Conversations">
        {threads.length === 0 ? (
          <p className="threads-empty">
            No conversations yet. Ask something to start one.
          </p>
        ) : (
          <>
            {band("Today", groups.today)}
            {band("Yesterday", groups.yesterday)}
            {band("Earlier", groups.earlier)}
          </>
        )}
      </nav>

      <div className="side-foot">
        <QuotaMeter quota={quota} />
        <a href="/accounts/">Your account</a>
      </div>
    </aside>
  );
}
