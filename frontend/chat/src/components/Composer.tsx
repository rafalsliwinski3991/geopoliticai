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
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <input
        aria-label="Ask a question"
        maxLength={2000}
        placeholder={busy ? "Analyzing…" : "Ask about geopolitics…"}
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit" disabled={busy}>
        Send
      </button>
    </form>
  );
}
