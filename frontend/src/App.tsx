import { FormEvent, useState } from "react";

type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;
};

type ChatResponse = {
  reply: string;
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
        body: JSON.stringify({ message }),
      });

      if (!response.ok) throw new Error(`Request failed (${response.status})`);

      const data: ChatResponse = await response.json();
      setMessages((current) => [
        ...current,
        { id: Date.now(), role: "assistant", text: data.reply },
      ]);
    } catch (requestError) {
      const detail =
        requestError instanceof Error ? requestError.message : "Unknown error";
      setError(`Could not reach EV Advisor. ${detail}`);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <section className="chat-card" aria-labelledby="page-title">
        <header className="chat-header">
          <div className="brand-mark" aria-hidden="true">EV</div>
          <div>
            <p className="eyebrow">Electric mobility, made clearer</p>
            <h1 id="page-title">EV Advisor</h1>
          </div>
        </header>

        <div className="messages" aria-live="polite">
          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              <span>{message.role === "user" ? "You" : "EV Advisor"}</span>
              <p>{message.text}</p>
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
