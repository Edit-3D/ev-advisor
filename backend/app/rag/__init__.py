"""Deterministic local retrieval for EV background knowledge."""

from backend.app.rag.retrieval import KnowledgeIndex, search_ev_knowledge

__all__ = ["KnowledgeIndex", "search_ev_knowledge"]
