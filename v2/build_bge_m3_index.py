from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

from v2 import rag_v2  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Supabase v2 BGE-M3 chunk index.")
    parser.add_argument("--force", action="store_true", help="Regenerate and upsert all chunk embeddings.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max chunks for a smoke test.")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding/upsert batch size.")
    args = parser.parse_args()

    result = rag_v2.build_bge_m3_index(force=args.force, limit=args.limit or None, batch_size=args.batch_size)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

