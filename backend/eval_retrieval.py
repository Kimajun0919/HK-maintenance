"""
eval_retrieval.py — Retrieval quality evaluator.

Usage
-----
    python eval_retrieval.py cases.json    # JSON file
    python eval_retrieval.py cases.csv     # CSV file

A test case is only useful when you know exactly which document and section
should appear in the results.  Do not add cases unless both expected_source
and expected_title are confirmed from real documents in the corpus.

JSON schema
-----------
[
  {
    "question":        "string — the exact query to run",
    "expected_source": "string — relative path of the document, e.g. 고객사/접속정보.md",
    "expected_title":  "string — section title that must appear in the result"
  }
]

Both expected_source and expected_title may be non-empty.
If only one is provided the match logic uses whichever is present.
A case where both fields are empty will be skipped with a warning.

CSV schema
----------
question,expected_source,expected_title
(header row is required; same field rules as above)

Metrics
-------
  Top-1 accuracy  — expected document/section is rank 1
  Top-3 accuracy  — expected document/section appears within the first 3 results
  Top-5 accuracy  — expected document/section appears within the first 5 results
  MRR             — Mean Reciprocal Rank across all cases

No test cases are bundled in this file.
Add your own in cases.json or cases.csv using the schema above.

TODO: populate cases.json with real queries and known correct sources/titles
      before running this script.  Example entry (do not copy verbatim —
      replace with actual values from your corpus):

      {
        "question":        "<real query text>",
        "expected_source": "<folder>/<filename>.md",
        "expected_title":  "<section heading from that document>"
      }
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rag  # noqa: E402


# ──────────────────────────────────────────────
# Loaders
# ──────────────────────────────────────────────


def _load_json(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON file must be a list of test-case objects.")
    return data


def _load_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_cases(path: str) -> list[dict]:
    lower = path.lower()
    if lower.endswith(".json"):
        return _load_json(path)
    if lower.endswith(".csv"):
        return _load_csv(path)
    raise ValueError(f"Unsupported format: {path}. Use .json or .csv")


# ──────────────────────────────────────────────
# Match logic
# ──────────────────────────────────────────────


def _is_match(chunk_source: str, chunk_title: str, expected_source: str, expected_title: str) -> bool:
    """
    A result chunk matches when:
    - expected_source is non-empty and is a case-insensitive substring of chunk.source, AND/OR
    - expected_title  is non-empty and is a case-insensitive substring of chunk.title.

    If both fields are provided, both must match.
    If only one is provided, only that field is checked.
    """
    has_source = bool(expected_source)
    has_title = bool(expected_title)
    source_ok = expected_source.lower() in chunk_source.lower() if has_source else True
    title_ok = expected_title.lower() in chunk_title.lower() if has_title else True
    # At least one field must be provided; checked by caller.
    return source_ok and title_ok


def _rank_of_first_match(
    results: list[tuple],
    expected_source: str,
    expected_title: str,
) -> int | None:
    for rank, (chunk, _) in enumerate(results, 1):
        if _is_match(chunk.source, chunk.title, expected_source, expected_title):
            return rank
    return None


# ──────────────────────────────────────────────
# Evaluation
# ──────────────────────────────────────────────


def evaluate(cases: list[dict], top_k: int = 5) -> dict:
    hits: dict[int, int] = {1: 0, 3: 0, 5: 0}
    rrs: list[float] = []
    details: list[dict] = []
    skipped = 0

    for case in cases:
        question = str(case.get("question", "")).strip()
        exp_source = str(case.get("expected_source", "")).strip()
        exp_title = str(case.get("expected_title", "")).strip()

        if not question:
            skipped += 1
            continue
        if not exp_source and not exp_title:
            print(f"  [SKIP] No expected_source or expected_title — skipping: {question!r}")
            skipped += 1
            continue

        results, _ = rag.retrieve(question, top_k=max(top_k, 5))
        rank = _rank_of_first_match(results, exp_source, exp_title)
        rr = 1.0 / rank if rank is not None else 0.0
        rrs.append(rr)

        for k in (1, 3, 5):
            if rank is not None and rank <= k:
                hits[k] += 1

        top_src, top_title = (results[0][0].source, results[0][0].title) if results else ("—", "—")
        details.append({"question": question, "rank": rank, "rr": rr, "top_source": top_src, "top_title": top_title})

    n = len(rrs)
    return {
        "n": n,
        "skipped": skipped,
        "top1_acc": hits[1] / n if n else 0.0,
        "top3_acc": hits[3] / n if n else 0.0,
        "top5_acc": hits[5] / n if n else 0.0,
        "mrr": sum(rrs) / n if n else 0.0,
        "details": details,
    }


# ──────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────


def print_report(metrics: dict) -> None:
    n = metrics["n"]
    skipped = metrics["skipped"]
    print()
    print("=" * 62)
    print(f"  Retrieval Evaluation  ({n} evaluated, {skipped} skipped)")
    print("=" * 62)
    if n == 0:
        print("  No evaluable test cases.  Add real cases to your input file.")
        print("=" * 62)
        return
    print(f"  Top-1 accuracy : {metrics['top1_acc']:.1%}  ({int(metrics['top1_acc'] * n)}/{n})")
    print(f"  Top-3 accuracy : {metrics['top3_acc']:.1%}  ({int(metrics['top3_acc'] * n)}/{n})")
    print(f"  Top-5 accuracy : {metrics['top5_acc']:.1%}  ({int(metrics['top5_acc'] * n)}/{n})")
    print(f"  MRR            : {metrics['mrr']:.4f}")
    print()
    print("  Per-question detail:")
    print("  " + "-" * 58)
    for d in metrics["details"]:
        rank_str = f"rank={d['rank']}" if d["rank"] else "NOT FOUND"
        print(f"  [{rank_str:10s}] {d['question'][:45]}")
        print(f"               → {d['top_source'][:38]} / {d['top_title'][:22]}")
    print("=" * 62)
    print()


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    try:
        cases = load_cases(sys.argv[1])
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    print(f"Loaded {len(cases)} test case(s) from {sys.argv[1]}")
    metrics = evaluate(cases)
    print_report(metrics)
