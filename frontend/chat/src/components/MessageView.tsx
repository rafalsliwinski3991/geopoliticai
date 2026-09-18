import { useState } from "react";
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

function downloadReport(message: Message & { role: "assistant" }) {
  const body = message.truncated ? `${message.text}\n\n${TRUNCATED_NOTE}` : message.text;
  const blob = new Blob([body], { type: "text/markdown" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = reportFileName(message.truncated);
  link.click();
  URL.revokeObjectURL(url);
}

async function copyReport(text: string) {
  await navigator.clipboard.writeText(text);
}

export function MessageView({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false);

  if (message.role === "user") {
    return <p className="message user">{message.text}</p>;
  }
  if (message.role === "error") {
    return <p className="message error">{message.text}</p>;
  }
  const isReport = message.kind === "report";
  return (
    <div className="message assistant">
      <div
        className="content"
        // The HTML is sanitized by `renderMarkdown` (DOMPurify + the URI
        // allow-list); the raw model text never reaches the DOM directly.
        dangerouslySetInnerHTML={{ __html: renderMarkdown(message.text) }}
      />
      {isReport && (
        <div className="actions">
          <button onClick={() => downloadReport(message)}>Download .md</button>
          <button
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
    <div className="outline">
      <h2>Proposed report outline</h2>
      {notice ? <p>{notice}</p> : null}
      <ol>
        {outline.map((section) => (
          <li key={section}>{section}</li>
        ))}
      </ol>
      <p>Reply to approve, change, or cancel — or just ask something else.</p>
    </div>
  );
}
