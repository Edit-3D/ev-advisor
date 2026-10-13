from pathlib import Path

import pytest

from backend.app.rag import KnowledgeIndex, search_ev_knowledge


KNOWLEDGE_PATH = Path("data/knowledge")


@pytest.fixture(scope="module")
def index() -> KnowledgeIndex:
    return KnowledgeIndex(KNOWLEDGE_PATH)


def test_all_five_documents_load_and_are_chunked(index: KnowledgeIndex) -> None:
    assert index.document_count == 5
    assert len(index.chunks) > index.document_count
    assert {chunk.document_filename for chunk in index.chunks} == {
        "ev_charging.md",
        "battery_health.md",
        "real_world_range.md",
        "charging_costs.md",
        "ev_ownership.md",
    }


@pytest.mark.parametrize(
    ("query", "expected_document"),
    [
        ("Why does DC fast charging slow near a high state of charge?", "ev_charging.md"),
        ("How can charging habits affect long-term battery degradation?", "battery_health.md"),
        ("How do cold weather and cabin heating affect driving range?", "real_world_range.md"),
        ("How do I estimate charging cost from kWh and electricity price?", "charging_costs.md"),
    ],
)
def test_topic_queries_retrieve_relevant_documents(
    index: KnowledgeIndex, query: str, expected_document: str
) -> None:
    results = index.search(query, top_k=3)["results"]
    assert expected_document in {result["document_filename"] for result in results}


def test_citation_and_document_metadata_are_preserved(index: KnowledgeIndex) -> None:
    result = index.search("J1772 CCS CHAdeMO NACS connector regional differences", top_k=1)[
        "results"
    ][0]

    assert result["document_title"]
    assert result["section_heading"] == "Connectors and regional differences"
    assert result["document_filename"] == "ev_charging.md"
    assert result["source_urls"] == ["https://afdc.energy.gov/vehicles/electric-consumers"]
    assert result["verification_date"] == "2026-10-13"
    assert 0 < result["relevance_score"] <= 1


def test_empty_and_unrelated_queries_are_conservative(index: KnowledgeIndex) -> None:
    assert index.search("   ")["results"] == []
    unrelated = index.search("quasar nebula sourdough archaeology")
    assert unrelated["results"] == []
    assert unrelated["message"]


def test_top_k_is_enforced(index: KnowledgeIndex) -> None:
    assert len(index.search("charging battery range electricity", top_k=2)["results"]) <= 2
    with pytest.raises(ValueError, match="top_k"):
        index.search("charging", top_k=0)


def test_retrieval_is_deterministic(index: KnowledgeIndex) -> None:
    first = index.search("home versus public charging costs", top_k=3)
    second = index.search("home versus public charging costs", top_k=3)
    assert first == second


def test_missing_knowledge_files_raise_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Missing knowledge documents"):
        KnowledgeIndex(tmp_path)


def test_tool_works_offline_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = search_ev_knowledge("public charging road trip planning", top_k=2)
    assert result["results"]
