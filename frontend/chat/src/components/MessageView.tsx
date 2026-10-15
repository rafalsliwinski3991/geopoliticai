import { useEffect, useState } from "react";
import { Message } from "../hooks/useConversation";
import { renderMarkdown } from "../lib/markdown";

// The report file name carries `-partial` only when characters were actually
// dropped; a complete 50,000-character report must not be labelled partial.
export function reportFileName(truncated: boolean): string {
  const date = new Date().toISOString().slice(0, 10);
  return truncated ? `report-${date}-partial.md` : `report-${date}.md`;
}

export const TRUNCATED_NOTE =
  "[This report was truncated at 50,000 characters.]";

const COPY_RESET_MS = 2000;

function downloadReport(message: Message & { role: "assistant" }) {
  const body = message.truncated ? `${message.text}\n\n${TRUNCATED_NOTE}` : message.text;
  const blob = new Blob([body], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = reportFileName(message.truncated);
  // Firefox ignores a programmatic click on an element outside the document,
  // and revoking the object URL in the same tick races the download.
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function copyReport(text: string) {
  await navigator.clipboard.writeText(text);
}

export function MessageView({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false);

  // The label is feedback about one click, not a second state: without the
  // reset a later re-copy gives no visible confirmation.
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), COPY_RESET_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  if (message.role === "user") {
    return (
      <div className="row">
        <div className="ask">
          <span className="who">You</span>
          <p>{message.text}</p>
        </div>
        <div />
      </div>
    );
  }
  if (message.role === "error") {
    return (
      <div className="row">
        <div className="say">
          <span className="who">Error</span>
          <p>{message.text}</p>
        </div>
        <div />
      </div>
    );
  }
  const isReport = message.kind === "report";
  return (
    <div className="row">
      <div className="say">
        <span className="who">PoliticalAgent</span>
        <div
          className="content"
          // A named article lets end-to-end tests find the answer by role, not position.
          role="article"
          aria-label="Answer"
          // The HTML is sanitized by `renderMarkdown` (DOMPurify + the URI
          // allow-list); the raw model text never reaches the DOM directly.
          dangerouslySetInnerHTML={{ __html: renderMarkdown(message.text) }}
        />
        {isReport && (
          <div className="actions">
            <button className="btn" onClick={() => downloadReport(message)}>
              Download .md
            </button>
            <button
              className="btn btn--quiet"
              onClick={async () => {
                await copyReport(message.text);
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
            {message.truncated && (
              <span className="notice">
                This report was too long to display in full — the download contains what was
                received, not the whole report.
              </span>
            )}
          </div>
        )}
      </div>
      <div />
    </div>
  );
}

export function OutlineCard({
  outline,
  notice,
}: {
  outline: string[];
  notice?: string;
}) {
  return (
    <div className="row">
      <div className="gate">
        <p>Here is the outline I would write. Reply to approve it, change it, or cancel.</p>
        <ol>
          {outline.map((section, index) => (
            <li key={index}>{section}</li>
          ))}
        </ol>
        {notice ? <p>{notice}</p> : null}
        <p className="gate-hint">Typing a reply works too.</p>
      </div>
    </div>
  );
}
