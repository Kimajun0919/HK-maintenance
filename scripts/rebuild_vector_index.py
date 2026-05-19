from __future__ import annotations

import sys
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import rag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the Supabase pgvector search index.")
    parser.add_argument("--force", action="store_true", help="Regenerate and upsert all chunk embeddings.")
    args = parser.parse_args()
    result = rag.refresh_index(force=args.force) or {}
    print(result)
    if not result.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
