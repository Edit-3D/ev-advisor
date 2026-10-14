import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownMessageProps = {
  children: string;
};

function safeLinkUrl(url: string): string {
  const normalized = url.trim().toLowerCase();
  return normalized.startsWith("https://") ||
    normalized.startsWith("http://") ||
    normalized.startsWith("mailto:")
    ? url
    : "";
}

function MarkdownMessage({ children }: MarkdownMessageProps) {
  return (
    <div className="markdown-message">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeLinkUrl}
        components={{
          a: ({ children: linkText, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer">
              {linkText}
            </a>
          ),
          img: () => null,
          table: ({ children: tableContents, ...props }) => (
            <div
              className="markdown-table-scroll"
              role="region"
              aria-label="Scrollable comparison table"
              tabIndex={0}
            >
              <table {...props}>{tableContents}</table>
            </div>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownMessage;
