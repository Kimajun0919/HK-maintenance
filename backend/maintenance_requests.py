from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from config import (
    SUPABASE_DOCS_TABLE,
    SUPABASE_ENABLED,
    SUPABASE_FOLDERS_TABLE,
    SUPABASE_REQUEST_IMPORTS_TABLE,
    SUPABASE_REQUESTS_TABLE,
)
from storage import _db_connect, _init_supabase_storage

try:
    from psycopg.types.json import Jsonb
except Exception:  # pragma: no cover - psycopg is optional until Supabase is enabled
    Jsonb = None  # type: ignore


DEFAULT_REQUEST_FOLDER = "유지보수_접수내역"

CSV_COLUMNS = [
    "idx",
    "user_id",
    "contact_person",
    "manager_id",
    "worker_id",
    "type_id",
    "status_id",
    "title",
    "content",
    "request_date",
    "expected_date",
    "completed_date",
    "expected_pm_hours",
    "expected_design_hours",
    "expected_pub_hours",
    "expected_dev_hours",
    "expected_hours_confirmed",
    "expected_hours_confirmed_at",
    "actual_pm_hours",
    "actual_design_hours",
    "actual_pub_hours",
    "actual_dev_hours",
    "is_urgent",
    "issues",
    "report_title",
    "progress_rate",
    "progress_status",
    "notes",
    "created_at",
    "updated_at",
]

INTEGER_COLUMNS = {"idx", "manager_id", "worker_id", "type_id", "status_id"}
NUMERIC_COLUMNS = {
    "expected_pm_hours",
    "expected_design_hours",
    "expected_pub_hours",
    "expected_dev_hours",
    "actual_pm_hours",
    "actual_design_hours",
    "actual_pub_hours",
    "actual_dev_hours",
    "progress_rate",
}
BOOLEAN_COLUMNS = {"expected_hours_confirmed", "is_urgent"}
DATE_COLUMNS = {"request_date", "expected_date", "completed_date"}
TIMESTAMP_COLUMNS = {"expected_hours_confirmed_at", "created_at", "updated_at"}

REQUEST_TABLE_COLUMNS = [
    "idx",
    "user_id",
    "contact_person",
    "manager_id",
    "worker_id",
    "type_id",
    "status_id",
    "title",
    "content",
    "request_date",
    "expected_date",
    "completed_date",
    "expected_pm_hours",
    "expected_design_hours",
    "expected_pub_hours",
    "expected_dev_hours",
    "expected_hours_confirmed",
    "expected_hours_confirmed_at",
    "actual_pm_hours",
    "actual_design_hours",
    "actual_pub_hours",
    "actual_dev_hours",
    "is_urgent",
    "issues",
    "report_title",
    "progress_rate",
    "progress_status",
    "notes",
    "created_at",
    "updated_at",
    "raw_data",
    "row_hash",
    "source",
    "folder",
    "search_text",
    "last_import_id",
]


def _clean_folder_name(value: str) -> str:
    value = re.sub(r'[<>:"|?*\x00-\x1f]+', "", str(value or "")).strip()
    value = value.replace("\\", "/").split("/")[-1].strip()
    value = re.sub(r"\s+", "_", value)
    return value or DEFAULT_REQUEST_FOLDER


def _empty_to_none(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _parse_int(value: object, field: str) -> int | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be an integer: {text!r}") from exc


def _parse_decimal(value: object, field: str) -> Decimal | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be numeric: {text!r}") from exc


def _parse_bool(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "y", "yes", "on"}


def _parse_date(value: object, field: str) -> date | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise ValueError(f"{field} must be a date: {text!r}") from exc


def _parse_timestamp(value: object, field: str) -> datetime | None:
    text = _empty_to_none(value)
    if text is None:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be a timestamp: {text!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _typed_value(field: str, value: object):
    if field in INTEGER_COLUMNS:
        return _parse_int(value, field)
    if field in NUMERIC_COLUMNS:
        return _parse_decimal(value, field)
    if field in BOOLEAN_COLUMNS:
        return _parse_bool(value)
    if field in DATE_COLUMNS:
        return _parse_date(value, field)
    if field in TIMESTAMP_COLUMNS:
        return _parse_timestamp(value, field)
    return "" if value is None else str(value).strip()


_BR_RE = re.compile(r"<\s*br\s*/?>", flags=re.I)
_BLOCK_END_RE = re.compile(r"</\s*(p|div|li|tr|h[1-6])\s*>", flags=re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(value: str) -> str:
    text = html.unescape(str(value or "").replace("&nbsp;", " "))
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _markdown_value(value: object) -> str:
    text = "" if value is None else str(value)
    text = html.unescape(text.replace("&nbsp;", " "))
    text = html.escape(text, quote=False)
    text = text.replace("|", "\\|")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _row_hash(raw_data: dict[str, str]) -> str:
    payload = json.dumps(raw_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _request_source(row: dict[str, str], folder: str) -> str:
    idx = _parse_int(row.get("idx"), "idx")
    return f"{folder}/접수_{idx}.md"


def _request_title(row: dict[str, str]) -> str:
    idx = str(row.get("idx") or "").strip()
    title = str(row.get("title") or row.get("report_title") or f"접수 {idx}").strip()
    return f"[{idx}] {title}" if idx else title


def _search_text(row: dict[str, str], headers: list[str]) -> str:
    parts = [
        row.get("idx", ""),
        row.get("user_id", ""),
        row.get("contact_person", ""),
        row.get("manager_id", ""),
        row.get("worker_id", ""),
        row.get("type_id", ""),
        row.get("status_id", ""),
        row.get("title", ""),
        row.get("report_title", ""),
        html_to_text(row.get("content", "")),
        row.get("issues", ""),
        row.get("progress_status", ""),
        row.get("notes", ""),
        row.get("request_date", ""),
        row.get("expected_date", ""),
        row.get("completed_date", ""),
        row.get("created_at", ""),
        row.get("updated_at", ""),
    ]
    parts.extend(f"{header}: {row.get(header, '')}" for header in headers)
    return re.sub(r"\s+", " ", "\n".join(part for part in parts if part)).strip()


def request_markdown(row: dict[str, str], headers: list[str]) -> str:
    request_body = html_to_text(row.get("content", ""))
    summary_rows = [
        ("접수번호", row.get("idx", "")),
        ("고객사", row.get("user_id", "")),
        ("제목", row.get("title", "")),
        ("보고서 제목", row.get("report_title", "")),
        ("상태 ID", row.get("status_id", "")),
        ("유형 ID", row.get("type_id", "")),
        ("담당자 ID", row.get("manager_id", "")),
        ("작업자 ID", row.get("worker_id", "")),
        ("요청일", row.get("request_date", "")),
        ("예정일", row.get("expected_date", "")),
        ("완료일", row.get("completed_date", "")),
        ("긴급", "예" if _parse_bool(row.get("is_urgent")) else "아니오"),
        ("진행률", row.get("progress_rate", "")),
        ("진행상태", row.get("progress_status", "")),
    ]
    lines = [
        f"# {_request_title(row)}",
        "",
        "## 접수 요약",
        "",
    ]
    lines.extend(f"- {label}: {_markdown_value(value)}" for label, value in summary_rows if str(value or "").strip())
    if request_body:
        lines.extend(["", "## 요청 내용", "", _markdown_value(request_body).replace("<br>", "\n")])
    if row.get("issues", "").strip():
        lines.extend(["", "## 이슈", "", _markdown_value(row.get("issues", ""))])
    if row.get("notes", "").strip():
        lines.extend(["", "## 메모", "", _markdown_value(row.get("notes", ""))])
    lines.extend(["", "## CSV 원본 필드", "", "| field | value |", "|---|---|"])
    lines.extend(f"| `{header}` | {_markdown_value(row.get(header, ''))} |" for header in headers)
    return "\n".join(lines).rstrip() + "\n"


def read_request_csv(csv_path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
        missing = [column for column in CSV_COLUMNS if column not in headers]
        if missing:
            raise ValueError(f"CSV header is missing required columns: {', '.join(missing)}")
        rows: list[dict[str, str]] = []
        for line_no, row in enumerate(reader, start=2):
            normalized = {header: str(row.get(header, "") or "").strip() for header in headers}
            if not any(normalized.values()):
                continue
            try:
                _parse_int(normalized.get("idx"), "idx")
            except ValueError as exc:
                raise ValueError(f"line {line_no}: {exc}") from exc
            rows.append(normalized)
    return rows, headers


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_maintenance_request_schema() -> None:
    if not SUPABASE_ENABLED:
        raise RuntimeError("Supabase is not enabled. Set DOC_STORAGE=supabase and SUPABASE_DB_URL.")
    with _db_connect() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("create extension if not exists pg_trgm")
            except Exception:
                pass
            cur.execute(
                f"""
                create table if not exists {SUPABASE_REQUEST_IMPORTS_TABLE} (
                    id text primary key,
                    file_name text not null,
                    file_sha256 text not null,
                    headers text[] not null,
                    row_count integer not null default 0,
                    folder text not null default '',
                    upserted_requests integer not null default 0,
                    upserted_docs integer not null default 0,
                    imported_at timestamptz not null default now()
                )
                """
            )
            cur.execute(
                f"""
                create table if not exists {SUPABASE_REQUESTS_TABLE} (
                    idx bigint primary key,
                    user_id text not null default '',
                    contact_person text not null default '',
                    manager_id bigint,
                    worker_id bigint,
                    type_id integer,
                    status_id integer,
                    title text not null default '',
                    content text not null default '',
                    request_date date,
                    expected_date date,
                    completed_date date,
                    expected_pm_hours numeric(10, 2),
                    expected_design_hours numeric(10, 2),
                    expected_pub_hours numeric(10, 2),
                    expected_dev_hours numeric(10, 2),
                    expected_hours_confirmed boolean not null default false,
                    expected_hours_confirmed_at timestamptz,
                    actual_pm_hours numeric(10, 2),
                    actual_design_hours numeric(10, 2),
                    actual_pub_hours numeric(10, 2),
                    actual_dev_hours numeric(10, 2),
                    is_urgent boolean not null default false,
                    issues text not null default '',
                    report_title text not null default '',
                    progress_rate numeric(6, 2),
                    progress_status text not null default '',
                    notes text not null default '',
                    created_at timestamptz,
                    updated_at timestamptz,
                    raw_data jsonb not null default '{{}}'::jsonb,
                    row_hash text not null,
                    source text not null,
                    folder text not null,
                    search_text text not null,
                    last_import_id text,
                    imported_at timestamptz not null default now(),
                    synced_at timestamptz not null default now()
                )
                """
            )
            cur.execute(f"create index if not exists {SUPABASE_REQUESTS_TABLE}_user_id_idx on {SUPABASE_REQUESTS_TABLE} (user_id)")
            cur.execute(f"create index if not exists {SUPABASE_REQUESTS_TABLE}_status_id_idx on {SUPABASE_REQUESTS_TABLE} (status_id)")
            cur.execute(f"create index if not exists {SUPABASE_REQUESTS_TABLE}_request_date_idx on {SUPABASE_REQUESTS_TABLE} (request_date desc)")
            cur.execute(f"create index if not exists {SUPABASE_REQUESTS_TABLE}_updated_at_idx on {SUPABASE_REQUESTS_TABLE} (updated_at desc)")
            cur.execute(f"create index if not exists {SUPABASE_REQUESTS_TABLE}_row_hash_idx on {SUPABASE_REQUESTS_TABLE} (row_hash)")
            cur.execute(f"create index if not exists {SUPABASE_REQUESTS_TABLE}_last_import_id_idx on {SUPABASE_REQUESTS_TABLE} (last_import_id)")
            try:
                cur.execute(
                    f"""
                    do $$
                    begin
                        if not exists (
                            select 1 from pg_constraint
                            where conname = '{SUPABASE_REQUESTS_TABLE}_last_import_id_fkey'
                        ) then
                            alter table {SUPABASE_REQUESTS_TABLE}
                            add constraint {SUPABASE_REQUESTS_TABLE}_last_import_id_fkey
                            foreign key (last_import_id)
                            references {SUPABASE_REQUEST_IMPORTS_TABLE}(id)
                            on update cascade
                            on delete set null;
                        end if;
                    end $$;
                    """
                )
            except Exception:
                pass
            try:
                cur.execute(
                    f"create index if not exists {SUPABASE_REQUESTS_TABLE}_search_text_trgm_idx "
                    f"on {SUPABASE_REQUESTS_TABLE} using gin (search_text gin_trgm_ops)"
                )
            except Exception:
                pass


def _jsonb_payload(value: dict[str, str]):
    if Jsonb is not None:
        return Jsonb(value)
    return json.dumps(value, ensure_ascii=False)


def _request_row_payload(row: dict[str, str], headers: list[str], folder: str, import_id: str) -> tuple:
    raw_data = {header: row.get(header, "") for header in headers}
    typed = [_typed_value(column, row.get(column)) for column in CSV_COLUMNS]
    return tuple(
        typed
        + [
            _jsonb_payload(raw_data),
            _row_hash(raw_data),
            _request_source(row, folder),
            folder,
            _search_text(row, headers),
            import_id,
        ]
    )


def upsert_maintenance_requests(rows: list[dict[str, str]], headers: list[str], folder: str, import_id: str) -> int:
    if not rows:
        return 0
    columns = ", ".join(REQUEST_TABLE_COLUMNS)
    placeholders = ", ".join(["%s"] * len(REQUEST_TABLE_COLUMNS))
    update_columns = [column for column in REQUEST_TABLE_COLUMNS if column != "idx"]
    update_set = ",\n                    ".join(f"{column} = excluded.{column}" for column in update_columns)
    payload = [_request_row_payload(row, headers, folder, import_id) for row in rows]
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                insert into {SUPABASE_REQUESTS_TABLE} ({columns})
                values ({placeholders})
                on conflict (idx) do update set
                    {update_set},
                    synced_at = now()
                """,
                payload,
            )
    return len(rows)


def ensure_request_folder(folder: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                insert into {SUPABASE_FOLDERS_TABLE} (name, sort_order)
                select %s, coalesce(max(sort_order), -1) + 1
                from {SUPABASE_FOLDERS_TABLE}
                on conflict (name) do nothing
                """,
                (folder,),
            )


def upsert_request_docs(rows: list[dict[str, str]], headers: list[str], folder: str) -> int:
    if not rows:
        return 0
    ensure_request_folder(folder)
    payload = [
        (
            _request_source(row, folder),
            _request_title(row),
            folder,
            request_markdown(row, headers),
        )
        for row in rows
    ]
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                insert into {SUPABASE_DOCS_TABLE} (source, title, customer, content)
                values (%s, %s, %s, %s)
                on conflict (source) do update set
                    title = excluded.title,
                    customer = excluded.customer,
                    content = excluded.content,
                    deleted_at = null,
                    updated_at = now()
                """,
                payload,
            )
    return len(rows)


def record_import(
    import_id: str,
    csv_path: str | Path,
    file_hash: str,
    headers: list[str],
    row_count: int,
    folder: str,
    upserted_requests: int,
    upserted_docs: int,
) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                insert into {SUPABASE_REQUEST_IMPORTS_TABLE} (
                    id, file_name, file_sha256, headers, row_count, folder,
                    upserted_requests, upserted_docs
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do update set
                    row_count = excluded.row_count,
                    upserted_requests = excluded.upserted_requests,
                    upserted_docs = excluded.upserted_docs
                """,
                (
                    import_id,
                    Path(csv_path).name,
                    file_hash,
                    headers,
                    row_count,
                    folder,
                    upserted_requests,
                    upserted_docs,
                ),
            )


def import_maintenance_requests_csv(
    csv_path: str | Path,
    folder: str = DEFAULT_REQUEST_FOLDER,
    upsert_structured: bool = True,
    upsert_docs: bool = True,
    dry_run: bool = False,
) -> dict:
    rows, headers = read_request_csv(csv_path)
    folder = _clean_folder_name(folder)
    digest = file_sha256(csv_path)
    import_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{digest[:12]}"
    summary = {
        "ok": True,
        "dryRun": dry_run,
        "importId": import_id,
        "file": str(Path(csv_path)),
        "fileSha256": digest,
        "folder": folder,
        "headers": headers,
        "rows": len(rows),
        "upsertedRequests": 0,
        "upsertedDocs": 0,
    }
    if dry_run:
        return summary
    if not SUPABASE_ENABLED:
        raise RuntimeError("Supabase is not enabled. Set DOC_STORAGE=supabase and SUPABASE_DB_URL.")
    _init_supabase_storage()
    ensure_maintenance_request_schema()
    if upsert_structured:
        summary["upsertedRequests"] = upsert_maintenance_requests(rows, headers, folder, import_id)
    if upsert_docs:
        summary["upsertedDocs"] = upsert_request_docs(rows, headers, folder)
    record_import(
        import_id,
        csv_path,
        digest,
        headers,
        len(rows),
        folder,
        int(summary["upsertedRequests"]),
        int(summary["upsertedDocs"]),
    )
    return summary


def _make_snippet(text: str, query: str, max_chars: int = 260) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return ""
    terms = [term.lower() for term in re.split(r"\s+", query.strip()) if term]
    lower = compact.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    start = max(0, min(positions) - 60) if positions else 0
    snippet = compact[start : start + max_chars].strip()
    return ("... " if start > 0 else "") + snippet + (" ..." if start + max_chars < len(compact) else "")


def request_graph_rows(limit: int = 4000) -> list[dict]:
    """v3 그래프용 티켓 레코드.

    마크다운 사본(유지보수_접수내역/접수_N.md)이 아니라 정규화된 테이블을
    직접 읽는다. 마크다운 사본은 폴더=고객사 규칙 때문에 '유지보수_접수내역'
    이라는 가짜 고객사 밑에 티켓 수백 건이 문서로 매달리는 왜곡을 만든다.
    실제 고객사는 user_id, 담당자는 manager_id / worker_id 에 있다.
    """
    if not SUPABASE_ENABLED:
        return []
    limit = max(1, min(int(limit), 20000))
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select idx, user_id, manager_id, worker_id, type_id, status_id,
                       title, request_date, completed_date, is_urgent, source
                from {SUPABASE_REQUESTS_TABLE}
                order by request_date desc nulls last, idx desc
                limit %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {
            "idx": r[0],
            "customer": (r[1] or "").strip(),
            "manager_id": r[2],
            "worker_id": r[3],
            "type_id": r[4],
            "status_id": r[5],
            "title": (r[6] or "").strip(),
            "request_date": r[7].isoformat() if r[7] else None,
            "completed_date": r[8].isoformat() if r[8] else None,
            "is_urgent": bool(r[9]),
            "source": r[10],
        }
        for r in rows
    ]


def search_maintenance_requests(query: str, limit: int = 10) -> list[dict]:
    query = str(query or "").strip()
    limit = max(1, min(int(limit), 50))
    if not SUPABASE_ENABLED:
        return []
    terms = [term for term in re.split(r"\s+", query) if term]
    where = " and ".join("search_text ilike %s" for _term in terms) if terms else "true"
    params = [f"%{term}%" for term in terms]
    fetch_limit = min(max(limit * 10, 100), 500)
    params.append(fetch_limit)
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select idx, user_id, title, report_title, request_date, expected_date,
                       completed_date, status_id, progress_rate, source, search_text, updated_at
                from {SUPABASE_REQUESTS_TABLE}
                where {where}
                order by updated_at desc nulls last, request_date desc nulls last, idx desc
                limit %s
                """,
                params,
            )
            rows = cur.fetchall()
    results = []
    lowered_terms = [term.lower() for term in terms]
    lowered_query = query.lower()
    for row in rows:
        search_text = row[10] or ""
        idx_text = str(row[0] or "")
        user_text = str(row[1] or "").lower()
        title_text = str(row[2] or "").lower()
        search_lower = search_text.lower()
        score = 0
        if query and idx_text == query:
            score += 100
        if lowered_query and lowered_query in title_text:
            score += 20
        elif lowered_query and lowered_query in search_lower:
            score += 10
        for term in lowered_terms:
            if term in title_text:
                score += 5
            if term in user_text:
                score += 3
            if term in search_lower:
                score += 1
        results.append(
            {
                "idx": row[0],
                "user_id": row[1],
                "title": row[2],
                "report_title": row[3],
                "request_date": row[4].isoformat() if row[4] else None,
                "expected_date": row[5].isoformat() if row[5] else None,
                "completed_date": row[6].isoformat() if row[6] else None,
                "status_id": row[7],
                "progress_rate": float(row[8]) if row[8] is not None else None,
                "source": row[9],
                "snippet": _make_snippet(search_text, query),
                "score": score,
                "updated_at": row[11].isoformat() if row[11] else None,
            }
        )
    results.sort(key=lambda item: (item["score"], item.get("updated_at") or "", item["idx"]), reverse=True)
    return results[:limit]
