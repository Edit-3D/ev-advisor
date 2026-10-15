import { FormEvent, useEffect, useRef, useState } from "react";
import DetailsPanel, { Citation, DetailsView, hasExecutionMetadata, uniqueCitations } from "./DetailsPanel";
import MarkdownMessage from "./MarkdownMessage";
import { PREVIEW_SCENARIOS, PreviewFailure, PreviewMessage, PreviewScenario, PreviewScenarioId } from "./previewFixtures";

type Message = PreviewMessage;
type ChatResponse = {
  reply: string;
  conversation_id: string;
  citations: Citation[];
  agents_invoked?: string[];
  tools_called?: string[];
};
type RequestFailure = PreviewFailure;
type ApiErrorBody = { detail?: { code?: string; message?: string } | string };
type Theme = "dark" | "light";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const EXAMPLE_QUESTIONS = [
  { topic: "Find an EV", label: "Find EVs with 400+ km range", question: "Find electric SUVs with at least 400 km of range." },
  { topic: "Compare EVs", label: "Compare Volvo EX30 and IONIQ 5", question: "Compare the Volvo EX30 and Hyundai IONIQ 5." },
  { topic: "Charging costs", label: "Calculate Volvo EX30 charging costs", question: "What does it cost to charge a Volvo EX30 from 20% to 80% at 3 SEK/kWh?" },
  { topic: "EV knowledge", label: "Why does cold reduce EV range?", question: "Why does cold weather reduce EV range?" },
  { topic: "Winter comparison", label: "Compare EVs for Swedish winters", question: "Compare the Volvo EX30 and Hyundai IONIQ 5 for winter driving in Sweden. Include range, charging speeds, and cold-weather effects." },
];
const PREVIEW_MODE = import.meta.env.DEV && import.meta.env.VITE_PREVIEW_MODE === "true";

function BoltLogo({ className }: { className: string }) {
  return <span className={className} aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M13.4 2 5.8 13h5.1l-.7 9L18.3 10h-5.1l.2-8Z" /></svg></span>;
}

type ChatComposerProps = {
  centered?: boolean;
  input: string;
  isLoading: boolean;
  onInputChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

function ChatComposer({ centered = false, input, isLoading, onInputChange, onSubmit }: ChatComposerProps) {
  return (
    <form className={`composer ${centered ? "welcome-composer" : ""}`} onSubmit={onSubmit}>
      {!centered && <label htmlFor="message">What are you looking for?</label>}
      <div className="composer-row">
        <input
          id="message"
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder={PREVIEW_MODE ? "Preview mode: backend requests are disabled" : "Ask about EVs, charging, range, or batteries..."}
          disabled={isLoading || PREVIEW_MODE}
          autoComplete="off"
          aria-label={centered ? "Ask EV Advisor" : undefined}
        />
        <button type="submit" disabled={PREVIEW_MODE || isLoading || !input.trim()}>{isLoading ? "Sending…" : "Send"}</button>
      </div>
    </form>
  );
}

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [failure, setFailure] = useState<RequestFailure | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [details, setDetails] = useState<{ message: Message; view: DetailsView } | null>(null);
  const [previewScenario, setPreviewScenario] = useState<PreviewScenarioId>("welcome");
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = window.localStorage.getItem("ev-advisor-theme");
      const initial = saved === "light" ? "light" : "dark";
      document.documentElement.dataset.theme = initial;
      return initial;
    } catch {
      return "dark";
    }
  });
  const activeController = useRef<AbortController | null>(null);
  const activeRequest = useRef<{ message: string; conversationId: string } | null>(null);
  const requestVersion = useRef(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { window.localStorage.setItem("ev-advisor-theme", theme); } catch { /* Storage can be unavailable. */ }
  }, [theme]);

  useEffect(() => () => {
    requestVersion.current += 1;
    activeController.current?.abort();
  }, []);

  async function sendMessage(message: string, options: { appendUser?: boolean; retry?: boolean; conversationId?: string | null } = {}) {
    if (PREVIEW_MODE) return;
    if (!message || isLoading) return;
    const appendUser = options.appendUser ?? true;
    const requestedConversationId = options.conversationId === undefined ? conversationId : options.conversationId;
    const requestConversationId = requestedConversationId ?? window.crypto.randomUUID();
    if (appendUser) setMessages((current) => [...current, { id: Date.now(), role: "user", text: message }]);
    setInput("");
    setFailure(null);
    setIsLoading(true);
    const controller = new AbortController();
    activeController.current = controller;
    activeRequest.current = { message, conversationId: requestConversationId };
    const version = ++requestVersion.current;

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, conversation_id: requestConversationId, retry: options.retry ?? false }),
        signal: controller.signal,
      });
      if (!response.ok) {
        let body: ApiErrorBody = {};
        try { body = await response.json() as ApiErrorBody; } catch { /* Use status fallback below. */ }
        const backendMessage = typeof body.detail === "object" ? body.detail?.message : undefined;
        const fallback = response.status === 504
          ? "This response took too long. Please try again."
          : response.status >= 500
            ? "Something went wrong while generating your response. Please try again."
            : "EV Advisor could not process that request. Please try again.";
        throw new Error(backendMessage || fallback);
      }

      const data: ChatResponse = await response.json();
      if (version !== requestVersion.current || controller.signal.aborted) return;
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
      if (version !== requestVersion.current || controller.signal.aborted) return;
      const friendlyMessage = requestError instanceof TypeError
        ? "Unable to connect to EV Advisor. Check your connection and try again."
        : requestError instanceof Error
          ? requestError.message
          : "Something went wrong while generating your response. Please try again.";
      setFailure({ message: friendlyMessage, originalMessage: activeRequest.current?.message ?? message, conversationId: requestConversationId, stopped: false });
    } finally {
      if (version === requestVersion.current) {
        setIsLoading(false);
        activeController.current = null;
        activeRequest.current = null;
      }
    }
  }

  function stopGenerating() {
    if (!isLoading || !activeController.current) return;
    const stoppedRequest = activeRequest.current;
    requestVersion.current += 1;
    activeController.current.abort();
    activeController.current = null;
    activeRequest.current = null;
    setIsLoading(false);
    setFailure({ message: "Response stopped", originalMessage: stoppedRequest?.message ?? "", conversationId: stoppedRequest?.conversationId ?? conversationId, stopped: true });
  }

  function retryLastRequest() {
    if (!failure || isLoading) return;
    if (failure.originalMessage) {
      void sendMessage(failure.originalMessage, { appendUser: false, retry: true, conversationId: failure.conversationId });
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(input.trim());
  }

  function startNewChat() {
    if (PREVIEW_MODE) {
      applyPreviewScenario("welcome");
      return;
    }
    requestVersion.current += 1;
    activeController.current?.abort();
    activeController.current = null;
    activeRequest.current = null;
    setIsLoading(false);
    setConversationId(null);
    setFailure(null);
    setInput("");
    setMessages([]);
    setDetails(null);
  }

  function applyPreviewScenario(id: PreviewScenarioId) {
    const scenario: PreviewScenario = PREVIEW_SCENARIOS[id];
    requestVersion.current += 1;
    activeController.current?.abort();
    activeController.current = null;
    activeRequest.current = null;
    setPreviewScenario(id);
    setMessages([...scenario.messages]);
    setInput("");
    setConversationId(null);
    setIsLoading(scenario.loading ?? false);
    setFailure(scenario.failure ?? null);
    const assistant = [...scenario.messages].reverse().find((message) => message.role === "assistant");
    setDetails(scenario.detailsView && assistant ? { message: assistant, view: scenario.detailsView } : null);
  }

  const isWelcome = messages.length === 0 && !isLoading && !failure;

  return (
    <main className={`page-shell ${details ? "has-details-panel" : ""}`} data-theme={theme}>
      <section className="chat-card" aria-labelledby="page-title">
        <header className="chat-header">
          <BoltLogo className="brand-mark" />
          <div className="brand-copy"><h1 id="page-title">EV Advisor</h1><p className="eyebrow">Electric mobility, made clearer</p></div>
          <button className="theme-toggle" type="button" onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
          </button>
          <button className="new-chat" type="button" onClick={startNewChat}>New Chat</button>
        </header>

        {PREVIEW_MODE && (
          <div className="preview-toolbar" role="region" aria-label="Development preview controls">
            <label htmlFor="preview-scenario">UI preview</label>
            <select id="preview-scenario" value={previewScenario} onChange={(event) => applyPreviewScenario(event.target.value as PreviewScenarioId)}>
              {Object.entries(PREVIEW_SCENARIOS).map(([id, scenario]) => <option key={id} value={id}>{scenario.label}</option>)}
            </select>
            <span>Development only · backend requests disabled</span>
          </div>
        )}

        <div className={`messages ${isWelcome ? "is-welcome" : ""}`} aria-live="polite">
          {isWelcome && (
            <section className="welcome" aria-labelledby="welcome-title">
              <h2 id="welcome-title">Where should we start?</h2>
              <p className="welcome-copy">Explore electric vehicles with data-backed comparisons, charging estimates, and practical EV knowledge.</p>
              <ChatComposer centered input={input} isLoading={isLoading} onInputChange={setInput} onSubmit={handleSubmit} />
              <div className="example-prompts" aria-label="Example questions">
                {EXAMPLE_QUESTIONS.map(({ topic, label, question }) => (
                  <button key={question} type="button" onClick={() => void sendMessage(question)} disabled={isLoading || PREVIEW_MODE}>
                    <span><small>{topic}</small>{label}</span><span aria-hidden="true">→</span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              {message.role === "assistant" ? (
                <div className="assistant-identity"><BoltLogo className="assistant-avatar" /><span>EV Advisor</span></div>
              ) : <span>You</span>}
              {message.role === "assistant" ? <MarkdownMessage>{message.text}</MarkdownMessage> : <p>{message.text}</p>}
              {message.role === "assistant" && (() => {
                const sourceCount = uniqueCitations(message.citations ?? []).length;
                const hasTrace = hasExecutionMetadata(message.agentsInvoked ?? [], message.toolsCalled ?? []);
                if (sourceCount === 0 && !hasTrace) return null;
                return (
                  <div className="message-actions" aria-label="Answer details">
                    {sourceCount > 0 && (
                      <button type="button" aria-haspopup="dialog" aria-label={`Open sources (${sourceCount})`} onClick={() => setDetails({ message, view: "sources" })}>
                        <svg className="message-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 5.5A2.5 2.5 0 0 1 7 3h5v16H7a2.5 2.5 0 0 0-2.5 2V5.5Zm15 0A2.5 2.5 0 0 0 17 3h-5v16h5a2.5 2.5 0 0 1 2.5 2V5.5Z" /></svg>
                        <span>Sources ({sourceCount})</span>
                        <svg className="message-action-chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="m7.5 5 5 5-5 5" /></svg>
                      </button>
                    )}
                    {hasTrace && (
                      <button type="button" aria-haspopup="dialog" aria-label="Open execution details" onClick={() => setDetails({ message, view: "execution" })}>
                        <svg className="message-action-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2" /><path d="M7 6h10M6.5 7.5l4.4 8.7m6.6-8.7-4.4 8.7" /></svg>
                        <span>Execution Details</span>
                        <svg className="message-action-chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="m7.5 5 5 5-5 5" /></svg>
                      </button>
                    )}
                  </div>
                );
              })()}
            </article>
          ))}

          {isLoading && <div className="loading" role="status" aria-live="polite"><BoltLogo className="assistant-avatar loading-avatar" /><span className="loading-dots" aria-hidden="true"><i /><i /><i /></span><span>Preparing your answer…</span></div>}
        </div>

        {failure && (
          <div className={`request-status ${failure.stopped ? "stopped" : "error"}`} role={failure.stopped ? "status" : "alert"}>
            <span>{failure.message}</span>
            <button type="button" onClick={retryLastRequest} disabled={isLoading}>Retry</button>
          </div>
        )}

        {isLoading && <div className="generation-controls"><button type="button" onClick={stopGenerating}>Stop generating</button></div>}

        {!isWelcome && <ChatComposer input={input} isLoading={isLoading} onInputChange={setInput} onSubmit={handleSubmit} />}
      </section>
      {details && (
        <DetailsPanel
          view={details.view}
          citations={details.message.citations ?? []}
          agents={details.message.agentsInvoked ?? []}
          tools={details.message.toolsCalled ?? []}
          onChangeView={(view) => setDetails((current) => current ? { ...current, view } : current)}
          onClose={() => setDetails(null)}
        />
      )}
    </main>
  );
}

export default App;
