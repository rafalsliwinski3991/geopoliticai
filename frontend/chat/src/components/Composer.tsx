import { useState } from "react";

export function Composer({
  busy,
  onSend,
}: {
  busy: boolean;
  onSend: (text: string) => void;
}) {
  const [value, setValue] = useState("");

  function submit() {
    const text = value.trim();
    if (!text || busy) return;
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
        <div className="field">
          <textarea
            id="q"
            rows={1}
            aria-label="Ask a question"
            maxLength={2000}
            placeholder={busy ? "Analyzing…" : "Ask about geopolitics…"}
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
          <button className="btn" type="submit" disabled={busy}>
            Send
          </button>
        </div>
        <div className="composer-foot">
          <p>Answers come from the sources read for this turn only. Up to 2,000 characters.</p>
        </div>
      </div>
    </form>
  );
}
