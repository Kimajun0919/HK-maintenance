from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _default_csv_path() -> Path:
    candidates = sorted(ROOT.glob("*.csv"))
    if len(candidates) == 1:
        return candidates[0]
    return ROOT / "유지보수 접수내역.csv"


def _masked_db_url(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.netloc:
        return "(invalid url)"
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += ":****"
        auth += "@"
    return urlunparse((parsed.scheme, f"{auth}{host}{port}", parsed.path, "", "", ""))


def _configure_target_env(args: argparse.Namespace) -> None:
    db_url = args.db_url or os.getenv("NEW_SUPABASE_DB_URL", "").strip()
    if not db_url:
        raise SystemExit("--db-url 또는 NEW_SUPABASE_DB_URL이 필요합니다.")

    os.environ["SUPABASE_DB_URL"] = db_url
    os.environ["DOC_STORAGE"] = "supabase"
    os.environ["SUPABASE_AUTO_MIGRATE"] = "1"
    os.environ["SUPABASE_SEED_FROM_FILES"] = "0"
    os.environ.setdefault("EMBEDDING_BACKEND", args.embedding_backend)
    if args.docs_table:
        os.environ["SUPABASE_DOCS_TABLE"] = args.docs_table
    if args.requests_table:
        os.environ["SUPABASE_REQUESTS_TABLE"] = args.requests_table


def _table_count(cur, table_name: str) -> int:
    cur.execute("select to_regclass(%s)", (f"public.{table_name}",))
    if cur.fetchone()[0] is None:
        return 0
    cur.execute(f"select count(*) from {table_name}")  # table_name is validated in backend.config
    return int(cur.fetchone()[0])


def _ensure_empty_target(allow_non_empty: bool) -> dict[str, int]:
    from config import SUPABASE_DOCS_TABLE, SUPABASE_REQUESTS_TABLE
    from maintenance_requests import ensure_maintenance_request_schema
    from storage import _db_connect, _init_supabase_storage

    _init_supabase_storage()
    ensure_maintenance_request_schema()
    with _db_connect() as conn:
        with conn.cursor() as cur:
            counts = {
                SUPABASE_DOCS_TABLE: _table_count(cur, SUPABASE_DOCS_TABLE),
                SUPABASE_REQUESTS_TABLE: _table_count(cur, SUPABASE_REQUESTS_TABLE),
            }
    if not allow_non_empty and any(counts.values()):
        details = ", ".join(f"{table}={count}" for table, count in counts.items())
        raise SystemExit(
            "대상 DB가 비어 있지 않습니다. 새 DB URL인지 확인하세요. "
            f"현재 row 수: {details}. 계속하려면 --allow-non-empty를 명시하세요."
        )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a fresh Supabase-backed RAG database from a maintenance request CSV."
    )
    parser.add_argument("csv_path", nargs="?", default=str(_default_csv_path()), help="CSV path to import.")
    parser.add_argument("--db-url", default="", help="Fresh Supabase/Postgres connection URL. Prefer NEW_SUPABASE_DB_URL.")
    parser.add_argument("--folder", default="유지보수_접수내역", help="Generated document folder name.")
    parser.add_argument("--docs-table", default="", help="Optional documents table name. Defaults to maintenance_docs.")
    parser.add_argument("--requests-table", default="", help="Optional structured request table name. Defaults to maintenance_requests.")
    parser.add_argument("--embedding-backend", default="none", help="Embedding backend for index sync. Defaults to none.")
    parser.add_argument("--allow-non-empty", action="store_true", help="Allow importing into a DB that already has rows.")
    parser.add_argument("--skip-index", action="store_true", help="Skip RAG index refresh after import.")
    parser.add_argument("--dry-run", action="store_true", help="Validate CSV only; do not connect to or write the new DB.")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        raise SystemExit(f"CSV 파일을 찾을 수 없습니다: {csv_path}")
    sys.path.insert(0, str(BACKEND))

    if args.dry_run:
        from maintenance_requests import import_maintenance_requests_csv

        result = import_maintenance_requests_csv(csv_path, folder=args.folder, dry_run=True)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    _configure_target_env(args)

    from maintenance_requests import import_maintenance_requests_csv

    before_counts = _ensure_empty_target(args.allow_non_empty)
    result = import_maintenance_requests_csv(csv_path, folder=args.folder)
    if not args.skip_index:
        import rag

        result["indexRefresh"] = rag.refresh_index(force=False)
    result["target"] = {
        "dbUrl": _masked_db_url(os.environ["SUPABASE_DB_URL"]),
        "beforeCounts": before_counts,
        "seedFromFiles": os.environ["SUPABASE_SEED_FROM_FILES"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
