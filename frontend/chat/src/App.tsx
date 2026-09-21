import { useCallback, useEffect, useRef, useState } from "react";
import { getAccessToken, TokenServiceError } from "./api/token";
import {
  listThreads,
  readThread,
  type Quota,
  type ThreadSummary,
} from "./api/threads";
import { mintThreadId, loadThreadId, storeThreadId, useConversation } from "./hooks/useConversation";
import { Composer } from "./components/Composer";
import { MessageView, OutlineCard } from "./components/MessageView";
import { Sidebar } from "./components/Sidebar";

type AuthState = "checking" | "ready" | "sign-in" | "error";

export default function App() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [attempt, setAttempt] = useState(0);
  const { messages, paused, outline, progress, isLoading, send, reset, restore } =
    useConversation();
  // The thread list loads alongside authentication; it fails soft — a sidebar
  // that cannot load must never block an ongoing conversation.
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [quota, setQuota] = useState<Quota>({ used: 0, limit: 0 });
  const [activeThread, setActiveThread] = useState<ThreadSummary | null>(null);

  // Authenticate on mount, not on the first send: a login redirect that
  // waits for a submitted message would discard that message.
  useEffect(() => {
    let cancelled = false;
    getAccessToken()
      .then(() => {
        if (!cancelled) setAuth("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // A 401 redirects to the login page; the thrown error only unwinds
        // the promise. Anything else is a token-service outage, which must
        // not permanently mark the session unauthenticated.
        setAuth(error instanceof TokenServiceError ? "error" : "sign-in");
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const refreshThreads = useCallback(() => {
    listThreads()
      .then((listing) => {
        setThreads(listing.threads);
        setQuota(listing.quota);
        // Every refresh after a turn settles the thread the turn actually
        // used, so a conversation started in this tab becomes the active one:
        // without this the heading stays "New conversation" forever and the
        // sidebar never marks the real current thread. `newChat` clears the
        // selection and stores a fresh id, so on an empty thread the match
        // simply fails and the current selection stays.
        setActiveThread(
          (current) =>
            listing.threads.find((thread) => thread.id === loadThreadId()) ??
            current,
        );
      })
      .catch((error: unknown) => {
        // The 401 path already navigated; other failures stay silent here.
        if (!(error instanceof Error && error.message.startsWith("Not auth"))) {
          console.error("Thread list refresh failed", error);
        }
      });
  }, []);

  useEffect(() => {
    if (auth === "ready") refreshThreads();
  }, [auth, refreshThreads]);

  const retry = useCallback(() => {
    setAuth("checking");
    setAttempt((n) => n + 1);
  }, []);

  // A fresh conversation key and a clean slate: without this, changing topics
  // keeps feeding every turn to the same LangGraph checkpoint.
  const newChat = useCallback(() => {
    setActiveThread(null);
    storeThreadId(mintThreadId());
    reset();
  }, [reset]);

  // The latest openThread selection wins: a thread read that resolves after a
  // later selection must not overwrite it.
  const openRequestRef = useRef(0);

  const openThread = useCallback(
    (threadId: string) => {
      const requested = openRequestRef.current + 1;
      openRequestRef.current = requested;
      readThread(threadId)
        .then((stored) => {
          if (requested !== openRequestRef.current) return;
          restore(threadId, stored.messages);
          const summary = threads.find((thread) => thread.id === threadId) ?? null;
          setActiveThread(summary);
        })
        .catch((error: unknown) => {
          // The selection is a navigation, not a failure state: keep the
          // current conversation and surface nothing worse than a console
          // note; the sidebar stays usable.
          console.error("Could not open that conversation", error);
        });
    },
    [restore, threads],
  );

  if (auth !== "ready") {
    return (
      <div className="app chat-solo">
        <main className="main">
          <div className="scroll">
            <div className="conv">
              <div className="row">
                <div className="gate">
                  <h1 className="wordmark">Political<em>Agent</em></h1>
                  {auth === "checking" ? (
                    <p>Loading…</p>
                  ) : auth === "error" ? (
                    <p>
                      The sign-in check failed.{" "}
                      <button className="btn" onClick={retry}>
                        Retry
                      </button>
                    </p>
                  ) : (
                    <p>Sign in required.</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  const handleSend = (text: string) => {
    // The turn's completion also settles the new thread's title and the spent
    // quota — both only exist after the turn finishes (the plan's one-request
    // refresh rule). The refreshed listing is reconciled with the thread the
    // turn actually used, so a conversation started in this tab becomes the
    // active one: without this the heading stays "New conversation" and the
    // sidebar never marks the real current thread.
    void send(text).finally(refreshThreads);
  };

  return (
    <div className="app">
      <Sidebar
        threads={threads}
        quota={quota}
        activeId={activeThread?.id ?? null}
        onOpen={openThread}
        onNewChat={newChat}
      />
      <main className="main">
        <div className="main-top">
          <h1>{activeThread?.title ?? "New conversation"}</h1>
          {/* The sidebar hides below the mobile breakpoint; this is the only
              new-conversation control that survives there. Without it, a
              mobile user stays welded to one checkpoint forever. */}
          <button
            className="btn new-thread-mobile"
            type="button"
            disabled={isLoading}
            onClick={newChat}
          >
            New
          </button>
        </div>
        <div className="scroll">
          <section aria-label="Conversation" className="conv">
            {messages.map((message, index) => (
              <MessageView key={index} message={message} />
            ))}
            {progress.length > 0 && (
              <div className="row">
                <div className="say">
                  <span className="who">Pipeline</span>
                  <ul aria-label="Progress" className="progress">
                    {progress.map((step, index) => (
                      <li key={index}>{step.label}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
            {paused && <OutlineCard outline={outline} />}
          </section>
        </div>
        <Composer busy={isLoading} onSend={handleSend} />
      </main>
    </div>
  );
}
