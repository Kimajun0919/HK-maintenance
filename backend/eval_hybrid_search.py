from __future__ import annotations

import json
from pathlib import Path

import rag


CASES_PATH = Path(__file__).with_name("search_quality_cases.json")


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


def evaluate(top_k: int = 5) -> dict:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    rows = []
    top3_hits = 0
    top5_hits = 0
    for case in cases:
        results = rag.search_documents(case["query"], top_k=top_k)
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
    total = len(cases)
    return {
        "total": total,
        "top3_hits": top3_hits,
        "top5_hits": top5_hits,
        "top3_accuracy": round(top3_hits / total, 4) if total else 0,
        "top5_accuracy": round(top5_hits / total, 4) if total else 0,
        "rows": rows,
    }


def main() -> int:
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
