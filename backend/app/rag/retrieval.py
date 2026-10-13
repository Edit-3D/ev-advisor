from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


DEFAULT_KNOWLEDGE_PATH = Path("data/knowledge")
REQUIRED_DOCUMENTS = {
    "ev_charging.md",
    "battery_health.md",
    "real_world_range.md",
    "charging_costs.md",
    "ev_ownership.md",
}
SOURCE_LINE = re.compile(r"^- (.+?): (https?://\S+)$")
WORD_PATTERN = re.compile(r"[A-Za-z0-9]+")
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "this",
    "to", "used", "what", "when", "where", "which", "why", "with",
}


def _normalize_text(text: str) -> str:
    words = []
    for word in WORD_PATTERN.findall(text.lower()):
        if len(word) > 4 and word.endswith("ies"):
            word = f"{word[:-3]}y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if word not in STOP_WORDS:
            words.append(word)
    return " ".join(words)


@dataclass(frozen=True)
class KnowledgeChunk:
    passage: str
    document_title: str
    section_heading: str
    document_filename: str
    source_urls: tuple[str, ...]
    verification_date: str | None

    def to_result(self, relevance_score: float) -> dict[str, Any]:
        result = asdict(self)
        result["source_urls"] = list(self.source_urls)
        result["relevance_score"] = round(relevance_score, 6)
        return result


def _word_windows(text: str, size: int, overlap: int) -> list[str]:
    words = text.split()
    windows: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        windows.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap
    return windows


def _parse_sources(source_block: str) -> dict[str, tuple[str, ...]]:
    sources: dict[str, list[str]] = {}
    for line in source_block.splitlines():
        match = SOURCE_LINE.match(line.strip())
        if match:
            sources.setdefault(match.group(1), []).append(match.group(2))
    return {heading: tuple(dict.fromkeys(urls)) for heading, urls in sources.items()}


def _load_document(path: Path, chunk_words: int, overlap_words: int) -> list[KnowledgeChunk]:
    markdown = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    sources_match = re.search(r"^##\s+Sources\s*$", markdown, re.MULTILINE)
    verification_match = re.search(r"^Verification date:\s*(.+)$", markdown, re.MULTILINE)
    if title_match is None:
        raise ValueError(f"Knowledge document has no H1 title: {path}")
    if sources_match is None:
        raise ValueError(f"Knowledge document has no Sources section: {path}")

    title = title_match.group(1).strip()
    sources = _parse_sources(markdown[sources_match.end() :])
    content = markdown[: sources_match.start()]
    headings = list(re.finditer(r"^##\s+(.+)$", content, re.MULTILINE))
    chunks: list[KnowledgeChunk] = []
    for index, heading in enumerate(headings):
        section_heading = heading.group(1).strip()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        section_text = re.sub(r"\s+", " ", content[heading.end() : end]).strip()
        if not section_text:
            continue
        section_sources = sources.get(section_heading)
        if not section_sources:
            raise ValueError(f"No source mapped to section '{section_heading}' in {path}")
        for passage in _word_windows(section_text, chunk_words, overlap_words):
            chunks.append(
                KnowledgeChunk(
                    passage=passage,
                    document_title=title,
                    section_heading=section_heading,
                    document_filename=path.name,
                    source_urls=section_sources,
                    verification_date=(
                        verification_match.group(1).strip() if verification_match else None
                    ),
                )
            )
    return chunks


class KnowledgeIndex:
    """An immutable in-memory TF-IDF index built from local Markdown files."""

    def __init__(
        self,
        knowledge_path: str | Path = DEFAULT_KNOWLEDGE_PATH,
        *,
        chunk_words: int = 110,
        overlap_words: int = 20,
        minimum_score: float = 0.08,
    ) -> None:
        if chunk_words <= 0 or overlap_words < 0 or overlap_words >= chunk_words:
            raise ValueError("chunk_words must be positive and overlap smaller than chunk_words")
        self.knowledge_path = Path(knowledge_path)
        if not self.knowledge_path.is_dir():
            raise FileNotFoundError(f"Knowledge directory not found: {self.knowledge_path}")

        paths = sorted(self.knowledge_path.glob("*.md"))
        found = {path.name for path in paths}
        missing = sorted(REQUIRED_DOCUMENTS - found)
        if missing:
            raise FileNotFoundError(f"Missing knowledge documents: {', '.join(missing)}")

        self.document_count = len(paths)
        self.chunks = [
            chunk
            for path in paths
            for chunk in _load_document(path, chunk_words, overlap_words)
        ]
        self.minimum_score = minimum_score
        self.vectorizer = TfidfVectorizer(
            lowercase=False,
            preprocessor=_normalize_text,
            stop_words=None,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        indexed_text = [
            f"{chunk.document_title} {chunk.section_heading} "
            f"{chunk.section_heading} {chunk.passage}"
            for chunk in self.chunks
        ]
        self.matrix = self.vectorizer.fit_transform(indexed_text)

    def search(self, query: str, top_k: int = 3) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"query": query, "count": 0, "results": [], "message": "Query is empty."}
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")

        query_vector = self.vectorizer.transform([query.strip()])
        if query_vector.nnz == 0:
            return {
                "query": query,
                "count": 0,
                "results": [],
                "message": "No sufficiently relevant knowledge was found.",
            }
        scores = cosine_similarity(query_vector, self.matrix).ravel()
        ranked = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
        results = [
            self.chunks[index].to_result(float(scores[index]))
            for index in ranked
            if scores[index] >= self.minimum_score
        ][:top_k]
        return {
            "query": query,
            "count": len(results),
            "results": results,
            "message": None if results else "No sufficiently relevant knowledge was found.",
        }


@lru_cache(maxsize=4)
def _get_index(knowledge_path: str) -> KnowledgeIndex:
    return KnowledgeIndex(knowledge_path)


def search_ev_knowledge(
    query: str,
    top_k: int = 3,
    *,
    knowledge_path: str | Path = DEFAULT_KNOWLEDGE_PATH,
) -> dict[str, Any]:
    """Search the local EV knowledge base and return citation-ready results."""
    resolved_path = str(Path(knowledge_path).resolve())
    return _get_index(resolved_path).search(query, top_k)
