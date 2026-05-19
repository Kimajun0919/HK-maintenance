from __future__ import annotations

import unittest
from pathlib import Path
import sys
import os
import json
from unittest.mock import patch

os.environ.setdefault("EMBEDDING_BACKEND", "hash")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rag
from models import Chunk


def make_chunk(source: str, title: str, heading: str, body: str) -> Chunk:
    document_id = rag._stable_document_id(source)
    return Chunk(
        text=body,
        source=source,
        title=title,
        document_id=document_id,
        chunk_id=f"{document_id}_{heading}",
        heading=heading,
        filename=source.rsplit("/", 1)[-1],
        folder=source.rsplit("/", 1)[0] if "/" in source else "",
        updated_at="2026-05-19T00:00:00+00:00",
        normalized_body=rag.normalize_search_text(body),
        compact_body=rag.compact_search_text(body),
    )


class HybridSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_settings = rag.copy.deepcopy(rag._SETTINGS)
        rag._SETTINGS = rag._deep_merge(
            rag.copy.deepcopy(rag._DEFAULT_SETTINGS),
            {
                "synonyms": {
                    "synonyms": {
                        "물이": ["누수", "물샘"],
                        "새요": ["누수", "물샘"],
                        "엘베": ["엘리베이터", "승강기"],
                        "고장": ["점검", "유지보수"],
                        "전기": ["차단기", "브레이커", "트립"],
                        "내려감": ["차단기", "브레이커", "트립"],
                        "에어컨": ["냉난방기", "공조기"],
                        "냄새": ["필터", "청소", "점검"],
                        "도면": ["평면도", "cad"],
                        "확인": ["점검"],
                        "as": ["수리", "점검"],
                        "접수": ["요청", "처리"],
                    }
                }
            },
        )
        self.retriever = rag.Retriever(
            [
                make_chunk("facility/plumbing/leak.md", "누수 조치 내역", "배관 점검", "천장 물샘과 누수 발생 시 밸브를 잠그고 배관을 점검한다."),
                make_chunk("facility/elevator/check.md", "엘리베이터 점검", "승강기 유지보수", "승강기 고장 신고 접수 후 안전 점검을 진행한다."),
                make_chunk("facility/electric/breaker.md", "차단기 트립 대응 매뉴얼", "브레이커 점검", "전기 차단 및 브레이커 트립 발생 시 차단기를 확인한다."),
                make_chunk("facility/hvac/filter.md", "냉난방기 필터 청소", "공조기 점검", "에어컨 냄새가 날 때 필터를 교체하고 공조기를 점검한다."),
                make_chunk("facility/drawing/cad.md", "평면도 CAD 도면", "도면 확인", "시설 평면도와 CAD 파일 위치를 확인한다."),
                make_chunk("service/as.md", "A/S 처리 내역", "수리 접수", "as 접수와 점검 요청 처리 내역을 기록한다."),
            ]
        )

    def tearDown(self) -> None:
        rag._SETTINGS = self.original_settings

    def test_normalization_handles_as_variants(self) -> None:
        self.assertEqual(rag.normalize_search_text("A/S 접수, a.s 완료, 에이에스"), "as 접수 as 완료 as")
        self.assertEqual(rag.compact_search_text("A/S 접수"), "as접수")

    def test_empty_synonyms_do_not_block_search(self) -> None:
        rag._SETTINGS["synonyms"] = {"synonyms": {}}
        results = self.retriever.search("as 접수", top_k=1)
        self.assertTrue(results)
        detail = self.retriever.last_score_details[results[0][0].chunk_id]
        self.assertFalse(detail["synonym_used"])
        self.assertEqual(detail["expanded_terms"], [])

    def test_expected_maintenance_queries(self) -> None:
        cases = {
            "물이 새요": "누수 조치 내역",
            "엘베 고장": "엘리베이터 점검",
            "전기 내려감": "차단기 트립 대응 매뉴얼",
            "에어컨 냄새": "냉난방기 필터 청소",
            "도면 확인": "평면도 CAD 도면",
            "as 접수": "A/S 처리 내역",
        }
        for query, expected_title in cases.items():
            with self.subTest(query=query):
                results = self.retriever.search(query, top_k=1)
                self.assertTrue(results)
                self.assertEqual(results[0][0].title, expected_title)
                detail = self.retriever.last_score_details[results[0][0].chunk_id]
                self.assertIn("bm25", detail)
                self.assertIn("ngram", detail)
                self.assertIn("embedding", detail)

    def test_document_grouping_removes_duplicate_top_level_docs(self) -> None:
        source = "facility/hvac/filter.md"
        retriever = rag.Retriever(
            [
                make_chunk(source, "냉난방기 필터 청소", "필터 청소", "에어컨 냄새 필터 청소 절차"),
                make_chunk(source, "냉난방기 필터 청소", "공조기 점검", "공조기 냄새 점검 기록"),
            ]
        )
        old_retriever = rag.retriever
        try:
            rag.retriever = retriever
            results = rag.search_documents("에어컨 냄새", top_k=5)
        finally:
            rag.retriever = old_retriever
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "냉난방기 필터 청소")
        self.assertEqual(len(results[0]["related_chunks"]), 1)


    def test_debug_search_includes_ranking_signals(self) -> None:
        old_retriever = rag.retriever
        try:
            rag.retriever = self.retriever
            payload = rag.search_documents("as 접수", top_k=3, debug=True)
        finally:
            rag.retriever = old_retriever
        self.assertIn("debug", payload)
        self.assertIn("results", payload)
        self.assertEqual(payload["debug"]["original_query"], "as 접수")
        self.assertIn("normalized_query", payload["debug"])
        self.assertGreater(payload["debug"]["candidate_count"], 0)
        score_detail = payload["results"][0]["score_detail"]
        for key in ("bm25", "ngram", "embedding", "field_boost", "exact_match_boost", "recency_boost"):
            self.assertIn(key, score_detail)

    def test_embedding_failure_falls_back_to_lexical_search(self) -> None:
        class BrokenModel:
            def encode(self, *_args, **_kwargs):
                raise RuntimeError("embedding failed")

        old_backend = os.environ.get("EMBEDDING_BACKEND")
        os.environ["EMBEDDING_BACKEND"] = "sentence-transformers"
        try:
            rag.EmbeddingStore._model_failed = False
            with patch.object(rag.EmbeddingStore, "_load_model", return_value=BrokenModel()):
                retriever = rag.Retriever(
                    [make_chunk("service/as.md", "A/S 처리 내역", "수리 접수", "as 접수 점검 요청")]
                )
                results = retriever.search("as 접수", top_k=1)
        finally:
            if old_backend is None:
                os.environ.pop("EMBEDDING_BACKEND", None)
            else:
                os.environ["EMBEDDING_BACKEND"] = old_backend
            rag.EmbeddingStore._model_failed = False
        self.assertTrue(results)
        detail = retriever.last_score_details[results[0][0].chunk_id]
        self.assertEqual(detail["embedding"], 0.0)

    def test_pgvector_candidates_are_merged_with_lexical_candidates(self) -> None:
        first = make_chunk("docs/lexical.md", "Lexical", "Lexical", "alpha alpha alpha")
        second = make_chunk("docs/vector.md", "Vector", "Vector", "semantic-only content")
        retriever = rag.Retriever([first, second])
        rag._SETTINGS = rag._deep_merge(
            rag.copy.deepcopy(rag._SETTINGS),
            {
                "search": {
                    "candidate_limits": {"bm25": 1, "ngram": 1, "vector": 1, "merged_max": 2},
                    "weights": {
                        "bm25": 0.35,
                        "ngram": 0.15,
                        "embedding": 0.35,
                        "field_boost": 0.10,
                        "exact_match_boost": 0.05,
                        "recency_boost_max": 0.05,
                    },
                }
            },
        )
        with patch.object(rag, "SUPABASE_ENABLED", True), patch.object(
            rag, "_db_vector_search_chunks", return_value=[{"chunk_id": second.chunk_id, "similarity": 0.99}]
        ):
            results = retriever.search("alpha", top_k=2, debug=True)
        result_ids = [chunk.chunk_id for chunk, _score in results]
        self.assertIn(second.chunk_id, result_ids)
        self.assertEqual(retriever.last_debug["vector_candidate_count"], 1)
        detail = retriever.last_score_details[second.chunk_id]
        self.assertTrue(detail["sources"]["vector"])
        self.assertFalse(detail["sources"]["bm25"])
        self.assertEqual(detail["embedding"], 0.99)

    def test_sync_vector_index_upserts_only_changed_chunks_and_deletes_stale(self) -> None:
        local_chunks = [
            make_chunk("facility/a.md", "A", "A1", "alpha body"),
            make_chunk("facility/b.md", "B", "B1", "beta body"),
        ]
        retriever = rag.Retriever(local_chunks)
        first_hash = retriever.embedding_store.text_hash(retriever.embedding_store.chunk_embedding_text(local_chunks[0]))
        old_chunks = rag.chunks
        old_retriever = rag.retriever
        try:
            rag.chunks = local_chunks
            rag.retriever = retriever
            with patch.object(rag, "SUPABASE_ENABLED", True), \
                 patch.object(rag, "_db_existing_chunk_hashes", return_value={local_chunks[0].chunk_id: first_hash}), \
                 patch.object(rag, "_db_delete_stale_chunks", return_value=1) as delete_stale, \
                 patch.object(rag, "_db_upsert_search_chunks", return_value=1) as upsert:
                result = rag.sync_vector_index()
        finally:
            rag.chunks = old_chunks
            rag.retriever = old_retriever
        self.assertTrue(result["ok"])
        self.assertEqual(result["upserted"], 1)
        self.assertEqual(result["stale_deleted"], 1)
        delete_stale.assert_called_once_with([chunk.chunk_id for chunk in local_chunks])
        self.assertEqual(len(upsert.call_args.args[0]), 1)
        self.assertEqual(upsert.call_args.args[0][0]["chunk_id"], local_chunks[1].chunk_id)

    def test_force_sync_vector_index_rebuilds_unchanged_chunks(self) -> None:
        local_chunks = [make_chunk("facility/a.md", "A", "A1", "alpha body")]
        retriever = rag.Retriever(local_chunks)
        current_hash = retriever.embedding_store.text_hash(retriever.embedding_store.chunk_embedding_text(local_chunks[0]))
        old_chunks = rag.chunks
        old_retriever = rag.retriever
        try:
            rag.chunks = local_chunks
            rag.retriever = retriever
            with patch.object(rag, "SUPABASE_ENABLED", True), \
                 patch.object(rag, "_db_existing_chunk_hashes", return_value={local_chunks[0].chunk_id: current_hash}), \
                 patch.object(rag, "_db_delete_stale_chunks", return_value=0), \
                 patch.object(rag, "_db_upsert_search_chunks", return_value=1) as upsert:
                result = rag.sync_vector_index(force=True)
        finally:
            rag.chunks = old_chunks
            rag.retriever = old_retriever
        self.assertTrue(result["ok"])
        self.assertTrue(result["force"])
        self.assertEqual(len(upsert.call_args.args[0]), 1)

    def test_quality_case_set_has_at_least_30_queries(self) -> None:
        cases_path = Path(__file__).with_name("search_quality_cases.json")
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 30)
        for case in cases:
            self.assertIn("query", case)
            self.assertTrue(case.get("expected_keywords") or case.get("expected_document_ids"))


if __name__ == "__main__":
    unittest.main()
