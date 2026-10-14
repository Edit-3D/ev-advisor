import { useEffect, useMemo, useRef } from "react";
import { externalReferences, normalizedExternalUrl } from "./sourceReferences";
import type { Citation } from "./sourceReferences";

export type { Citation } from "./sourceReferences";

export type DetailsView = "sources" | "execution";

type DetailsPanelProps = {
  view: DetailsView;
  citations: Citation[];
  agents: string[];
  tools: string[];
  onChangeView: (view: DetailsView) => void;
  onClose: () => void;
};

function cleanValues(values: string[]): string[] {
  return values.map((value) => value.trim()).filter(Boolean);
}

export function uniqueCitations(citations: Citation[]): Citation[] {
  const seen = new Set<string>();
  return citations.filter((citation) => {
    const key = normalizedExternalUrl(citation.url);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function hasExecutionMetadata(agents: string[], tools: string[]): boolean {
  return cleanValues(agents).length > 0 || cleanValues(tools).length > 0;
}

function agentLabel(identifier: string): string {
  const labels: Record<string, string> = {
    vehicle: "Vehicle Agent",
    research: "Research Agent",
  };
  return labels[identifier] ?? identifier.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function groupedTools(tools: string[]): Array<{ name: string; count: number }> {
  const counts = new Map<string, number>();
  for (const tool of cleanValues(tools)) counts.set(tool, (counts.get(tool) ?? 0) + 1);
  return [...counts].map(([name, count]) => ({ name, count }));
}

function DetailsPanel({
  view,
  citations,
  agents,
  tools,
  onChangeView,
  onClose,
}: DetailsPanelProps) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const sources = useMemo(() => externalReferences(citations), [citations]);
  const uniqueAgents = [...new Set(cleanValues(agents))];
  const toolGroups = groupedTools(tools);

  useEffect(() => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButton.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab" && panel.current) {
        const focusable = [...panel.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        )];
        const first = focusable[0];
        const last = focusable.at(-1);
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      returnFocus.current?.focus();
    };
  }, [onClose]);

  return (
    <div className="details-panel-layer">
      <button className="details-panel-backdrop" type="button" onClick={onClose} aria-label="Close details panel" />
      <aside ref={panel} className="details-panel" role="dialog" aria-modal="true" aria-labelledby="details-panel-title">
        <header className="details-panel-header">
          <div>
            <p className="details-panel-kicker">Answer details</p>
            <h2 id="details-panel-title">{view === "sources" ? "Sources" : "Execution Details"}</h2>
          </div>
          <button ref={closeButton} className="details-panel-close" type="button" onClick={onClose} aria-label="Close details panel">×</button>
        </header>

        <div className="details-panel-tabs" role="tablist" aria-label="Answer details">
          {sources.length > 0 && (
            <button type="button" role="tab" aria-selected={view === "sources"} onClick={() => onChangeView("sources")}>
              Sources ({sources.length})
            </button>
          )}
          {hasExecutionMetadata(uniqueAgents, tools) && (
            <button type="button" role="tab" aria-selected={view === "execution"} onClick={() => onChangeView("execution")}>
              Execution Details
            </button>
          )}
        </div>

        <div className="details-panel-content">
          {view === "sources" ? (
            <div className="source-list">
              {sources.length === 0 && <p className="source-empty">No external references are available for this response.</p>}
              {sources.map((source) => (
                <a className="source-item" key={source.url} href={source.url} target="_blank" rel="noopener noreferrer">
                  <span className="source-copy">
                    <strong>{source.title}</strong>
                    <small>{source.publisher} <span aria-hidden="true">·</span> {source.website}</small>
                  </span>
                  <svg className="source-external-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5v5M19 5l-8 8M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>
                </a>
              ))}
            </div>
          ) : (
            <div className="execution-panel-content">
              {uniqueAgents.length > 0 && (
                <section>
                  <h3>Agents involved</h3>
                  <ul>{uniqueAgents.map((agent) => <li key={agent}><strong>{agentLabel(agent)}</strong><code>{agent}</code></li>)}</ul>
                </section>
              )}
              {toolGroups.length > 0 && (
                <section>
                  <h3>Tools executed</h3>
                  <ul>{toolGroups.map(({ name, count }) => <li key={name}><code>{name}</code>{count > 1 && <span>× {count}</span>}</li>)}</ul>
                </section>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

export default DetailsPanel;
