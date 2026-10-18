import json

import pytest

from app.rag import store
from app.rag.corpus import load_chunks, split_text
from app.rag.ranking import fuse_ranks
from scripts.evaluate_retrieval import evaluate


def test_keyword_benchmark_and_citations():
    report = evaluate()
    assert report["summary"]["recall_at_3"] == 1
    result = store.search_policy("tracking 48 hours", use_vectors=False)[0]
    assert result["source"] == "shipping_policy.md"
    assert result["citation"] == f"{result['source']}@{result['version']}#{result['chunk_id']}"
    assert result["retrieval_methods"] == ["keyword"]
    assert len(result["document_hash"]) == 64


def test_fusion_rewards_agreement_and_deduplicates():
    result = fuse_ranks(["a", "b", "b"], ["b", "c"])
    assert result[0][0] == "b"
    assert result[0][2] == ["keyword", "vector"]
    assert len(result) == 3


def test_vector_candidates_drop_stale_chunks_and_distant_matches(monkeypatch):
    chunks = load_chunks()

    class Collection:
        def count(self):
            return 3

        def query(self, **kwargs):
            assert kwargs["include"] == ["distances"]
            return {"ids": [["stale", chunks[0].id, chunks[1].id]], "distances": [[0.1, 0.2, 0.9]]}

    monkeypatch.setattr(store, "collection", lambda: Collection())
    assert store.vector_candidates("query", chunks) == ([chunks[0].id], "available")


def test_keyword_fallback_when_embedding_service_fails(monkeypatch):
    def unavailable():
        raise RuntimeError("private-vector-error")

    monkeypatch.setattr(store, "collection", unavailable)
    result = store.search_policy("cancel before shipment")
    assert result[0]["source"] == "cancellation_policy.md"
    assert result[0]["vector_status"] == "unavailable"
    assert "private-vector-error" not in json.dumps(result)


def test_chunk_ids_change_when_content_or_version_changes(tmp_path):
    policy = tmp_path / "policy.md"
    manifest = tmp_path / "manifest.json"
    policy.write_text("An approved policy.", encoding="utf-8")
    manifest.write_text('{"policy.md":"v1"}', encoding="utf-8")
    first = load_chunks(tmp_path)[0]
    assert load_chunks(tmp_path)[0] == first
    policy.write_text("An updated policy.", encoding="utf-8")
    assert load_chunks(tmp_path)[0].id != first.id
    manifest.write_text('{"policy.md":"v2"}', encoding="utf-8")
    assert load_chunks(tmp_path)[0].version == "v2"
    (tmp_path / "unapproved.md").write_text("Not in manifest")
    with pytest.raises(ValueError, match="manifest"):
        load_chunks(tmp_path)


def test_ingestion_removes_stale_chunks_after_upsert(monkeypatch):
    chunks = load_chunks()
    events = []

    class Collection:
        def upsert(self, **kwargs):
            events.append("upsert")
            assert kwargs["ids"] == [chunk.id for chunk in chunks]

        def get(self, **kwargs):
            return {"ids": [chunk.id for chunk in chunks] + ["stale"]}

        def delete(self, ids):
            events.append("delete")
            assert ids == ["stale"]

    monkeypatch.setattr(store, "collection", lambda: Collection())
    assert store.ingest() == 4
    assert events == ["upsert", "delete"]


def test_empty_and_unrelated_queries_do_not_invent_lexical_evidence():
    assert store.search_policy("   ", use_vectors=False) == []
    assert store.search_policy("quantum astrophysics", use_vectors=False) == []
    assert all(len(chunk) <= 900 for chunk in split_text("word " * 1000))
