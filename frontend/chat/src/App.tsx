import { useConversation } from "./hooks/useConversation";
import { Composer } from "./components/Composer";
import { MessageView, OutlineCard } from "./components/MessageView";

export default function App() {
  const { messages, paused, outline, progress, isLoading, send } = useConversation();

  return (
    <main>
      <h1>PoliticalAgent</h1>
      <section aria-label="Conversation">
        {messages.map((message, index) => (
          <MessageView key={index} message={message} />
        ))}
        {progress.length > 0 && (
          <ul aria-label="Progress">
            {progress.map((step, index) => (
              <li key={index}>{step.label}</li>
            ))}
          </ul>
        )}
        {paused && <OutlineCard outline={outline} />}
      </section>
      <Composer busy={isLoading} onSend={send} />
    </main>
  );
}
