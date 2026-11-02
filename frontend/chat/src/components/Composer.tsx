import { useRef, useState } from "react";
import { DocumentChip } from "./DocumentChip";

export function Composer({
  busy,
  uploading,
  document,
  onSend,
  onAttach,
  onDetach,
}: {
  busy: boolean;
  uploading: boolean;
  document: string | null;
  onSend: (text: string) => void;
  onAttach: (file: File) => void;
  onDetach: () => void;
}) {
  const [value, setValue] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const blocked = busy || uploading;

  function submit() {
    const text = value.trim();
    if (!text || blocked) return;
    setValue("");
    onSend(text);
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="composer-inner">
        {document && (
          <DocumentChip filename={document} busy={blocked} onRemove={onDetach} />
        )}
        <div className="field">
          <textarea
            id="q"
            rows={1}
            aria-label="Ask a question"
            maxLength={2000}
            placeholder={
              uploading
                ? "Reading your document…"
                : busy
                  ? "Analyzing…"
                  : "Ask about geopolitics…"
            }
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              // Enter confirms the suggestion of a pending IME composition
              // (CJK input); submitting then would send half-formed text.
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
          />
          <input
            ref={fileInput}
            type="file"
            hidden
            aria-label="Attach a document"
            accept=".pdf,.txt,application/pdf,text/plain"
            onChange={(event) => {
              const file = event.target.files?.[0];
              // Clearing the value lets the same file be chosen again after it
              // was removed.
              event.target.value = "";
              if (file) onAttach(file);
            }}
          />
          <button
            className="btn btn--quiet"
            type="button"
            disabled={blocked}
            onClick={() => fileInput.current?.click()}
          >
            Attach
          </button>
          <button className="btn" type="submit" disabled={blocked}>
            Send
          </button>
        </div>
        <div className="composer-foot">
          <p>
            {document
              ? "Answers come from your document while one is attached."
              : "Answers come from the sources read for this turn only."}{" "}
            Up to 2,000 characters.
          </p>
        </div>
      </div>
    </form>
  );
}
