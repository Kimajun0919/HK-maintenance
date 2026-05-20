from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from maintenance_requests import (  # noqa: E402
    DEFAULT_REQUEST_FOLDER,
    import_maintenance_requests_csv,
)


def _default_csv_path() -> Path:
    candidates = sorted(ROOT.glob("*.csv"))
    if len(candidates) == 1:
        return candidates[0]
    return ROOT / "유지보수 접수내역.csv"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import maintenance request CSV rows into Supabase and generated searchable docs."
    )
    parser.add_argument("csv_path", nargs="?", default=str(_default_csv_path()), help="CSV path to import.")
    parser.add_argument("--folder", default=DEFAULT_REQUEST_FOLDER, help="Generated document folder name.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize without writing to Supabase.")
    parser.add_argument("--no-structured", action="store_true", help="Skip the maintenance_requests structured table.")
    parser.add_argument("--no-docs", action="store_true", help="Skip generated Markdown docs in maintenance_docs.")
    args = parser.parse_args()

    result = import_maintenance_requests_csv(
        Path(args.csv_path),
        folder=args.folder,
        upsert_structured=not args.no_structured,
        upsert_docs=not args.no_docs,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
