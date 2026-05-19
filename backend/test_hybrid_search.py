from __future__ import annotations

import unittest
from pathlib import Path
import sys

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


if __name__ == "__main__":
    unittest.main()
