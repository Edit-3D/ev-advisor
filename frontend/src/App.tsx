import { FormEvent, useState } from "react";
import MarkdownMessage from "./MarkdownMessage";

type Citation = { url: string; title: string; document_filename: string; section_heading: string };
type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  agentsInvoked?: string[];
  toolsCalled?: string[];
};
type ChatResponse = {
  reply: string;
  conversation_id: string;
  citations: Citation[];
  agents_invoked?: string[];
  tools_called?: string[];
};

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const EXAMPLE_QUESTIONS = [
  "Find three Volvo EVs with at least 400 km rated range.",
  "Compare the Volvo EX30 and Hyundai IONIQ 5.",
  "Why does cold weather reduce EV range?",
  "What would it cost to charge a Tesla Model Y from 20% to 80% at €0.30/kWh?",
];
const DEVELOPMENT_PREVIEW = import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("preview") === "markdown";
const PREVIEW_MESSAGE: Message = {
  id: -1,
  role: "assistant",
  text: `## Winter EV comparison

Both cars are capable, but their strengths differ:

| Vehicle | Rated range | DC charging | Best suited to |
| --- | ---: | ---: | --- |
| **Volvo EX30** | 476 km WLTP | 153 kW | Compact urban driving |
| **Hyundai IONIQ 5** | 507 km WLTP | 220 kW | Longer trips and faster charging |

### Practical considerations

- Expect lower real-world range in cold weather.
- Preconditioning can improve charging performance.
- Compare the exact configuration because specifications may differ.

Use the vehicle ID in \`compare_vehicles\` when checking exact configurations.

[Read the EV Database winter range guide](https://ev-database.org/cheatsheet/range-electric-car).`,
  citations: [{
    url: "https://ev-database.org/cheatsheet/range-electric-car",
    title: "EV Database",
    document_filename: "winter-range.md",
    section_heading: "Real-world range",
  }],
  agentsInvoked: ["vehicle", "research"],
  toolsCalled: ["compare_vehicles", "search_ev_knowledge"],
};

function ExecutionSummary({ message }: { message: Message }) {
  const agents = message.agentsInvoked ?? [];
  const tools = message.toolsCalled ?? [];
  if (agents.length === 0 && tools.length === 0) return null;

  return (
    <details className="execution-summary">
      <summary>How this answer was prepared</summary>
      <div className="execution-details">
        {agents.length > 0 && <div><strong>Agents</strong><ul>{agents.map((agent, index) => <li key={`${agent}-${index}`}><code>{agent}</code></li>)}</ul></div>}
        {tools.length > 0 && <div><strong>Tools</strong><ul>{tools.map((tool, index) => <li key={`${tool}-${index}`}><code>{tool}</code></li>)}</ul></div>}
      </div>
    </details>
  );
}

function App() {
  const [messages, setMessages] = useState<Message[]>(DEVELOPMENT_PREVIEW ? [PREVIEW_MESSAGE] : []);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  async function sendMessage(message: string) {
    if (!message || isLoading) return;
    setMessages((current) => [...current, { id: Date.now(), role: "user", text: message }]);
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
        if (response.status === 504) throw new Error("EV Advisor took too long to respond. Please try again.");
        throw new Error(`Request failed (${response.status})`);
      }

      const data: ChatResponse = await response.json();
      setConversationId(data.conversation_id);
      setMessages((current) => [...current, {
        id: Date.now(),
        role: "assistant",
        text: data.reply,
        citations: data.citations,
        agentsInvoked: data.agents_invoked,
        toolsCalled: data.tools_called,
      }]);
    } catch (requestError) {
      const detail = requestError instanceof Error ? requestError.message : "Unknown error";
      setError(`Could not reach EV Advisor. ${detail}`);
    } finally {
      setIsLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(input.trim());
  }

  function startNewChat() {
    if (isLoading) return;
    setConversationId(null);
    setError(null);
    setInput("");
    setMessages([]);
  }

  return (
    <main className="page-shell">
      <section className="chat-card" aria-labelledby="page-title">
        <header className="chat-header">
          <div className="brand-mark" aria-hidden="true">EV</div>
          <div className="brand-copy"><p className="eyebrow">Electric mobility, made clearer</p><h1 id="page-title">EV Advisor</h1></div>
          <button className="new-chat" type="button" onClick={startNewChat} disabled={isLoading}>New Chat</button>
        </header>

        <div className={`messages ${messages.length === 0 ? "is-welcome" : ""}`} aria-live="polite">
          {messages.length === 0 && !isLoading && (
            <section className="welcome" aria-labelledby="welcome-title">
              <div className="welcome-icon" aria-hidden="true">⚡</div>
              <p className="welcome-kicker">Your electric-car research companion</p>
              <h2 id="welcome-title">Find an EV that fits your life</h2>
              <p className="welcome-copy">Explore vehicle specifications, compare models, estimate charging costs, and understand batteries, range, and ownership using curated data and sources.</p>
              <div className="example-prompts" aria-label="Example questions">
                {EXAMPLE_QUESTIONS.map((question) => (
                  <button key={question} type="button" onClick={() => void sendMessage(question)} disabled={isLoading}>
                    <span>{question}</span><span aria-hidden="true">→</span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              <span>{message.role === "user" ? "You" : "EV Advisor"}</span>
              {message.role === "assistant" ? <MarkdownMessage>{message.text}</MarkdownMessage> : <p>{message.text}</p>}
              {message.citations && message.citations.length > 0 && (
                <ul className="citations" aria-label="Sources">
                  {message.citations.map((citation) => <li key={`${message.id}-${citation.url}`}><a href={citation.url} target="_blank" rel="noreferrer">{citation.title}: {citation.section_heading}</a></li>)}
                </ul>
              )}
              {message.role === "assistant" && <ExecutionSummary message={message} />}
            </article>
          ))}

          {isLoading && <div className="loading" role="status" aria-live="polite"><span className="loading-dots" aria-hidden="true"><i /><i /><i /></span><span>Preparing your answer…</span></div>}
        </div>

        {DEVELOPMENT_PREVIEW && <p className="preview-notice" role="status">Development Markdown preview — remove <code>?preview=markdown</code> to return to chat.</p>}
        {error && <p className="error" role="alert">{error}</p>}

        <form className="composer" onSubmit={handleSubmit}>
          <label htmlFor="message">What are you looking for?</label>
          <div className="composer-row">
            <input id="message" value={input} onChange={(event) => setInput(event.target.value)} placeholder="e.g. A practical EV for winter commuting" disabled={isLoading} autoComplete="off" />
            <button type="submit" disabled={isLoading || !input.trim()}>{isLoading ? "Sending…" : "Send"}</button>
          </div>
        </form>
      </section>
    </main>
  );
}

export default App;
