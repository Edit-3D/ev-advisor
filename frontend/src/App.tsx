import { FormEvent, useState } from "react";

type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
};

type Citation = {
  url: string;
  title: string;
  document_filename: string;
  section_heading: string;
};

type ChatResponse = {
  reply: string;
  conversation_id: string;
  citations: Citation[];
};

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function App() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 0,
      role: "assistant",
      text: "Hi! I’m EV Advisor. Tell me what you need from an electric vehicle.",
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();

    if (!message || isLoading) return;

    setMessages((current) => [
      ...current,
      { id: Date.now(), role: "user", text: message },
    ]);
    setInput("");
    setError(null);
    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, conversation_id: conversationId }),
      });

      if (!response.ok) {
        if (response.status === 504) {
          throw new Error("EV Advisor took too long to respond. Please try again.");
        }
        throw new Error(`Request failed (${response.status})`);
      }

      const data: ChatResponse = await response.json();
      setConversationId(data.conversation_id);
      setMessages((current) => [
        ...current,
        {
          id: Date.now(),
          role: "assistant",
          text: data.reply,
          citations: data.citations,
        },
      ]);
    } catch (requestError) {
      const detail =
        requestError instanceof Error ? requestError.message : "Unknown error";
      setError(`Could not reach EV Advisor. ${detail}`);
    } finally {
      setIsLoading(false);
    }
  }

  function startNewChat() {
    if (isLoading) return;
    setConversationId(null);
    setError(null);
    setInput("");
    setMessages([
      {
        id: Date.now(),
        role: "assistant",
        text: "New conversation started. What would you like to know about EVs?",
      },
    ]);
  }

  return (
    <main className="page-shell">
      <section className="chat-card" aria-labelledby="page-title">
        <header className="chat-header">
          <div className="brand-mark" aria-hidden="true">EV</div>
          <div className="brand-copy">
            <p className="eyebrow">Electric mobility, made clearer</p>
            <h1 id="page-title">EV Advisor</h1>
          </div>
          <button className="new-chat" type="button" onClick={startNewChat} disabled={isLoading}>
            New Chat
          </button>
        </header>

        <div className="messages" aria-live="polite">
          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              <span>{message.role === "user" ? "You" : "EV Advisor"}</span>
              <p>{message.text}</p>
              {message.citations && message.citations.length > 0 && (
                <ul className="citations" aria-label="Sources">
                  {message.citations.map((citation) => (
                    <li key={`${message.id}-${citation.url}`}>
                      <a href={citation.url} target="_blank" rel="noreferrer">
                        {citation.title}: {citation.section_heading}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          ))}
          {isLoading && <p className="loading">EV Advisor is responding…</p>}
        </div>

        {error && <p className="error" role="alert">{error}</p>}

        <form className="composer" onSubmit={handleSubmit}>
          <label htmlFor="message">What are you looking for?</label>
          <div className="composer-row">
            <input
              id="message"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="e.g. A practical EV for winter commuting"
              disabled={isLoading}
              autoComplete="off"
            />
            <button type="submit" disabled={isLoading || !input.trim()}>
              {isLoading ? "Sending…" : "Send"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}

export default App;
