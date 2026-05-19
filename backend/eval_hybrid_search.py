from __future__ import annotations

import json
import sys
from pathlib import Path

import rag


CASES_PATH = Path(__file__).with_name("search_quality_cases.json")
REPORT_PATH = Path(__file__).with_name("search_quality_report.json")


def _result_text(item: dict) -> str:
    parts = [
        item.get("document_id", ""),
        item.get("title", ""),
        item.get("filename", ""),
        item.get("folder", ""),
        item.get("matched_heading", ""),
        item.get("matched_text", ""),
    ]
    return " ".join(str(part).lower() for part in parts)


def _matches(item: dict, expected_keywords: list[str], expected_document_ids: list[str]) -> bool:
    if expected_document_ids and item.get("document_id") in expected_document_ids:
        return True
    text = _result_text(item)
    return any(keyword.lower() in text for keyword in expected_keywords)


MODES = ("bm25_only", "ngram_only", "vector_only", "hybrid")


def _compact_candidate(item: dict) -> dict:
    keys = (
        "chunk_id",
        "document_id",
        "title",
        "filename",
        "folder",
        "heading",
        "matched_text",
        "sources",
        "bm25_score",
        "ngram_score",
        "embedding_score",
        "field_boost",
        "exact_match_boost",
        "final_score",
    )
    return {key: item.get(key) for key in keys}


def evaluate(top_k: int = 5, mode: str = "hybrid", include_failures: bool = False) -> dict:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    rows = []
    failures = []
    top3_hits = 0
    top5_hits = 0
    for case in cases:
        search_top_k = max(top_k, 10) if include_failures else top_k
        payload = rag.search_documents(case["query"], top_k=search_top_k, debug=include_failures, mode=mode)
        results = payload["results"] if include_failures else payload
        expected_keywords = case.get("expected_keywords", [])
        expected_document_ids = case.get("expected_document_ids", [])
        hit_rank = None
        for rank, item in enumerate(results, 1):
            if _matches(item, expected_keywords, expected_document_ids):
                hit_rank = rank
                break
        if hit_rank is not None and hit_rank <= 3:
            top3_hits += 1
        if hit_rank is not None and hit_rank <= 5:
            top5_hits += 1
        rows.append(
            {
                "query": case["query"],
                "hit_rank": hit_rank,
                "top_title": results[0]["title"] if results else "",
                "top_score": results[0]["score"] if results else 0,
            }
        )
        if include_failures and hit_rank is None:
            debug = payload.get("debug", {})
            candidates = debug.get("candidates", {})
            failures.append(
                {
                    "query": case["query"],
                    "expected_keywords": expected_keywords,
                    "expected_document_ids": expected_document_ids,
                    "bm25_candidates": [_compact_candidate(item) for item in candidates.get("bm25", [])[:10]],
                    "ngram_candidates": [_compact_candidate(item) for item in candidates.get("ngram", [])[:10]],
                    "vector_candidates": [_compact_candidate(item) for item in candidates.get("vector", [])[:10]],
                    "final_results": [_compact_candidate(item) for item in debug.get("final_results", [])[:10]],
                }
            )
    total = len(cases)
    report = {
        "mode": mode,
        "total": total,
        "top3_hits": top3_hits,
        "top5_hits": top5_hits,
        "top3_accuracy": round(top3_hits / total, 4) if total else 0,
        "top5_accuracy": round(top5_hits / total, 4) if total else 0,
        "rows": rows,
    }
    if include_failures:
        report["failures"] = failures
    return report


def evaluate_all_modes(top_k: int = 5) -> dict:
    return {mode: evaluate(top_k=top_k, mode=mode, include_failures=False) for mode in MODES}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    modes = evaluate_all_modes()
    report = {
        "summary": {
            mode: {
                "top3_accuracy": data["top3_accuracy"],
                "top5_accuracy": data["top5_accuracy"],
                "top3_hits": data["top3_hits"],
                "top5_hits": data["top5_hits"],
                "total": data["total"],
            }
            for mode, data in modes.items()
        },
        "hybrid": evaluate(mode="hybrid", include_failures=True),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "report_path": str(REPORT_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
