from __future__ import annotations

import mimetypes
import re
from pathlib import PurePosixPath

from config import (
    DOCS_DIR,
    SUPABASE_ASSETS_TABLE,
    SUPABASE_AUTO_MIGRATE,
    SUPABASE_CHUNKS_TABLE,
    SUPABASE_DB_URL,
    SUPABASE_DOCS_TABLE,
    SUPABASE_ENABLED,
    SUPABASE_FOLDERS_TABLE,
    SUPABASE_META_TABLE,
    SUPABASE_SEED_FROM_FILES,
    EMBEDDING_DIM,
)
from models import AssetRecord, DocRecord, FolderRecord

def _file_doc_records() -> list[DocRecord]:
    if not DOCS_DIR.exists():
        return []

    records: list[DocRecord] = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel_parts = path.relative_to(DOCS_DIR).parts
        if rel_parts and rel_parts[0] == "HK_유지보수팀":
            continue
        if path.name in {"SIMPLIFY_CHANGELOG.md"}:
            continue
        rel = path.relative_to(DOCS_DIR).as_posix()
        records.append(
            DocRecord(
                source=rel,
                title=path.stem,
                customer=rel_parts[0] if rel_parts else "",
                content=path.read_text(encoding="utf-8", errors="replace"),
            )
        )
    return records


def _file_asset_records() -> list[AssetRecord]:
    if not DOCS_DIR.exists():
        return []

    records: list[AssetRecord] = []
    for path in sorted(DOCS_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            continue
        rel = path.relative_to(DOCS_DIR).as_posix()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        records.append(AssetRecord(path=rel, mime_type=mime_type, content=path.read_bytes()))
    return records


def _file_folder_records() -> list[FolderRecord]:
    names = {record.customer for record in _file_doc_records() if record.customer}
    if DOCS_DIR.exists():
        names.update(path.name for path in DOCS_DIR.iterdir() if path.is_dir())
    return [FolderRecord(name=name, sort_order=idx) for idx, name in enumerate(sorted(names, key=lambda value: value.lower()))]


def _db_connect():
    try:
        import psycopg
    except ModuleNotFoundError as exc:
        raise RuntimeError("Supabase DB storage requires `psycopg[binary]`. Run pip install -r requirements.txt.") from exc
    return psycopg.connect(SUPABASE_DB_URL, autocommit=True, connect_timeout=10)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


def _init_supabase_storage() -> None:
    if not SUPABASE_ENABLED:
        return
    with _db_connect() as conn:
        with conn.cursor() as cur:
            if SUPABASE_AUTO_MIGRATE:
                cur.execute(
                    f"""
                    create table if not exists {SUPABASE_DOCS_TABLE} (
                        id bigserial primary key,
                        source text not null unique,
                        title text not null,
                        customer text not null default '',
                        content text not null,
                        created_at timestamptz not null default now(),
                        updated_at timestamptz not null default now()
                    )
                    """
                )
                cur.execute(f"create index if not exists {SUPABASE_DOCS_TABLE}_customer_idx on {SUPABASE_DOCS_TABLE} (customer)")
                cur.execute(f"create index if not exists {SUPABASE_DOCS_TABLE}_updated_at_idx on {SUPABASE_DOCS_TABLE} (updated_at desc)")
                cur.execute(
                    f"""
                    create table if not exists {SUPABASE_ASSETS_TABLE} (
                        id bigserial primary key,
                        path text not null unique,
                        mime_type text not null default 'application/octet-stream',
                        content bytea not null,
                        size_bytes integer not null default 0,
                        created_at timestamptz not null default now(),
                        updated_at timestamptz not null default now()
                    )
                    """
                )
                cur.execute(f"create index if not exists {SUPABASE_ASSETS_TABLE}_updated_at_idx on {SUPABASE_ASSETS_TABLE} (updated_at desc)")
                cur.execute(
                    f"""
                    create table if not exists {SUPABASE_FOLDERS_TABLE} (
                        id bigserial primary key,
                        name text not null unique,
                        sort_order integer not null default 0,
                        created_at timestamptz not null default now(),
                        updated_at timestamptz not null default now()
                    )
                    """
                )
                cur.execute(f"create index if not exists {SUPABASE_FOLDERS_TABLE}_sort_order_idx on {SUPABASE_FOLDERS_TABLE} (sort_order, name)")
                cur.execute(
                    f"""
                    create table if not exists {SUPABASE_META_TABLE} (
                        key text primary key,
                        value text not null,
                        created_at timestamptz not null default now()
                    )
                    """
                )
                cur.execute(f"alter table {SUPABASE_DOCS_TABLE} add column if not exists deleted_at timestamptz")
                cur.execute(f"create index if not exists {SUPABASE_DOCS_TABLE}_deleted_at_idx on {SUPABASE_DOCS_TABLE} (deleted_at) where deleted_at is not null")
                cur.execute(f"alter table {SUPABASE_ASSETS_TABLE} add column if not exists deleted_at timestamptz")
                cur.execute(f"create index if not exists {SUPABASE_ASSETS_TABLE}_deleted_at_idx on {SUPABASE_ASSETS_TABLE} (deleted_at) where deleted_at is not null")
                try:
                    cur.execute("create extension if not exists vector")
                    cur.execute(
                        f"""
                        create table if not exists {SUPABASE_CHUNKS_TABLE} (
                            chunk_id text primary key,
                            document_id text not null,
                            source text not null,
                            title text not null,
                            filename text not null default '',
                            folder text not null default '',
                            heading text not null default '',
                            body text not null,
                            normalized_body text not null default '',
                            compact_body text not null default '',
                            body_hash text not null,
                            embedding vector({EMBEDDING_DIM}) not null,
                            updated_at timestamptz,
                            indexed_at timestamptz not null default now()
                        )
                        """
                    )
                    cur.execute(f"create index if not exists {SUPABASE_CHUNKS_TABLE}_document_id_idx on {SUPABASE_CHUNKS_TABLE} (document_id)")
                    cur.execute(f"create index if not exists {SUPABASE_CHUNKS_TABLE}_source_idx on {SUPABASE_CHUNKS_TABLE} (source)")
                    cur.execute(f"create index if not exists {SUPABASE_CHUNKS_TABLE}_body_hash_idx on {SUPABASE_CHUNKS_TABLE} (body_hash)")
                    cur.execute(
                        f"create index if not exists {SUPABASE_CHUNKS_TABLE}_embedding_hnsw_idx on {SUPABASE_CHUNKS_TABLE} using hnsw (embedding vector_cosine_ops)"
                    )
                except Exception:
                    # pgvector may be unavailable in local PostgreSQL. Core document storage should still boot.
                    pass
                cur.execute(f"delete from {SUPABASE_DOCS_TABLE} where deleted_at < now() - interval '30 days'")
                cur.execute(f"delete from {SUPABASE_ASSETS_TABLE} where deleted_at < now() - interval '30 days'")
            if SUPABASE_SEED_FROM_FILES:
                cur.execute(f"select 1 from {SUPABASE_META_TABLE} where key = 'seed_done'")
                if cur.fetchone() is None:
                    doc_rows = [(r.source, r.title, r.customer, r.content) for r in _file_doc_records()]
                    if doc_rows:
                        cur.executemany(
                            f"""
                            insert into {SUPABASE_DOCS_TABLE} (source, title, customer, content)
                            values (%s, %s, %s, %s)
                            on conflict (source) do nothing
                            """,
                            doc_rows,
                        )
                    folder_rows = [(r.customer,) for r in _file_doc_records() if r.customer]
                    if folder_rows:
                        cur.executemany(
                            f"""
                            insert into {SUPABASE_FOLDERS_TABLE} (name)
                            values (%s)
                            on conflict (name) do nothing
                            """,
                            folder_rows,
                        )
                    asset_rows = [(r.path, r.mime_type, r.content, len(r.content)) for r in _file_asset_records()]
                    if asset_rows:
                        cur.executemany(
                            f"""
                            insert into {SUPABASE_ASSETS_TABLE} (path, mime_type, content, size_bytes)
                            values (%s, %s, %s, %s)
                            on conflict (path) do nothing
                            """,
                            asset_rows,
                        )
                    cur.execute(
                        f"insert into {SUPABASE_META_TABLE} (key, value) values ('seed_done', '1') on conflict (key) do nothing"
                    )


def _db_doc_records() -> list[DocRecord]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select source, title, customer, content, updated_at from {SUPABASE_DOCS_TABLE} where deleted_at is null order by source")
            return [DocRecord(source=row[0], title=row[1], customer=row[2], content=row[3], updated_at=row[4].isoformat() if row[4] else None) for row in cur.fetchall()]


def _db_doc_index_records() -> list[DocRecord]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select source, title, customer, updated_at from {SUPABASE_DOCS_TABLE} where deleted_at is null order by source")
            return [DocRecord(source=row[0], title=row[1], customer=row[2], content="", updated_at=row[3].isoformat() if row[3] else None) for row in cur.fetchall()]


def _db_search_doc_records(query: str, limit: int) -> list[DocRecord]:
    terms = [term.strip() for term in re.split(r"\s+", str(query or "")) if term.strip()]
    if not terms or limit <= 0:
        return []
    clauses = []
    params: list[str | int] = []
    for term in terms:
        clauses.append("(source ilike %s or title ilike %s or customer ilike %s or content ilike %s)")
        pattern = f"%{term}%"
        params.extend([pattern, pattern, pattern, pattern])
    params.append(max(1, min(int(limit), 200)))
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select source, title, customer, content, updated_at
                from {SUPABASE_DOCS_TABLE}
                where deleted_at is null and {" and ".join(clauses)}
                order by updated_at desc nulls last, source
                limit %s
                """,
                params,
            )
            return [
                DocRecord(source=row[0], title=row[1], customer=row[2], content=row[3], updated_at=row[4].isoformat() if row[4] else None)
                for row in cur.fetchall()
            ]


def _db_asset_count() -> int:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select count(*) from {SUPABASE_ASSETS_TABLE} where deleted_at is null")
            return cur.fetchone()[0]


def _db_asset_total_bytes() -> int:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select coalesce(sum(size_bytes), 0) from {SUPABASE_ASSETS_TABLE} where deleted_at is null")
            return cur.fetchone()[0]


def _db_asset_paths(prefix: str = "") -> list[str]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            if prefix:
                cur.execute(f"select path from {SUPABASE_ASSETS_TABLE} where path like %s and deleted_at is null order by path", (f"{prefix}%",))
            else:
                cur.execute(f"select path from {SUPABASE_ASSETS_TABLE} where deleted_at is null order by path")
            return [row[0] for row in cur.fetchall()]


def _db_asset_record(path: str) -> AssetRecord | None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"select path, mime_type, content from {SUPABASE_ASSETS_TABLE} where path = %s and deleted_at is null",
                (path,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return AssetRecord(path=row[0], mime_type=row[1], content=bytes(row[2]))


def _db_soft_delete_asset(path: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"update {SUPABASE_ASSETS_TABLE} set deleted_at = now() where path = %s and deleted_at is null",
                (path,),
            )


def _db_restore_asset(path: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"update {SUPABASE_ASSETS_TABLE} set deleted_at = null where path = %s",
                (path,),
            )


def _db_permanent_delete_asset(path: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"delete from {SUPABASE_ASSETS_TABLE} where path = %s", (path,))


def _db_upsert_asset(record: AssetRecord) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                insert into {SUPABASE_ASSETS_TABLE} (path, mime_type, content, size_bytes)
                values (%s, %s, %s, %s)
                on conflict (path) do update set
                    mime_type = excluded.mime_type,
                    content = excluded.content,
                    size_bytes = excluded.size_bytes,
                    updated_at = now()
                """,
                (record.path, record.mime_type, record.content, len(record.content)),
            )


def _db_folder_records() -> list[FolderRecord]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select name, sort_order from {SUPABASE_FOLDERS_TABLE} order by sort_order, name")
            return [FolderRecord(name=row[0], sort_order=row[1]) for row in cur.fetchall()]


def _db_folder_exists(name: str) -> bool:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select 1 from {SUPABASE_FOLDERS_TABLE} where name = %s", (name,))
            return cur.fetchone() is not None


def _db_folder_doc_count(name: str) -> int:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select count(*) from {SUPABASE_DOCS_TABLE} where customer = %s and deleted_at is null", (name,))
            return cur.fetchone()[0]


def _db_create_folder(name: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select coalesce(max(sort_order), -1) + 1 from {SUPABASE_FOLDERS_TABLE}")
            sort_order = cur.fetchone()[0]
            cur.execute(
                f"""
                insert into {SUPABASE_FOLDERS_TABLE} (name, sort_order)
                values (%s, %s)
                """,
                (name, sort_order),
            )


def _db_update_folder_order(names: list[str]) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            for idx, name in enumerate(names):
                cur.execute(
                    f"update {SUPABASE_FOLDERS_TABLE} set sort_order = %s, updated_at = now() where name = %s",
                    (idx, name),
                )


def _db_rename_folder(old_name: str, new_name: str) -> None:
    old_prefix = f"{old_name}/"
    new_prefix = f"{new_name}/"
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"update {SUPABASE_FOLDERS_TABLE} set name = %s, updated_at = now() where name = %s",
                (new_name, old_name),
            )
            cur.execute(
                f"""
                update {SUPABASE_DOCS_TABLE}
                set source = %s || substring(source from %s),
                    customer = %s,
                    updated_at = now()
                where source like %s
                """,
                (new_prefix, len(old_prefix) + 1, new_name, f"{old_prefix}%"),
            )
            cur.execute(
                f"""
                update {SUPABASE_ASSETS_TABLE}
                set path = %s || substring(path from %s),
                    updated_at = now()
                where path like %s
                """,
                (new_prefix, len(old_prefix) + 1, f"{old_prefix}%"),
            )


def _db_soft_delete_folder_docs(folder_name: str) -> int:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"update {SUPABASE_DOCS_TABLE} set deleted_at = now() where customer = %s and deleted_at is null",
                (folder_name,),
            )
            return cur.rowcount


def _db_delete_folder(name: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"delete from {SUPABASE_FOLDERS_TABLE} where name = %s", (name,))


def _db_rename_doc(source: str, new_source: str, title: str, customer: str) -> DocRecord:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                update {SUPABASE_DOCS_TABLE}
                set source = %s, title = %s, customer = %s, updated_at = now()
                where source = %s
                returning source, title, customer, content
                """,
                (new_source, title, customer, source),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("document not found")
            return DocRecord(source=row[0], title=row[1], customer=row[2], content=row[3])


def _db_doc_record(source: str) -> DocRecord | None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"select source, title, customer, content from {SUPABASE_DOCS_TABLE} where source = %s and deleted_at is null",
                (source,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return DocRecord(source=row[0], title=row[1], customer=row[2], content=row[3])


def _db_create_doc(record: DocRecord) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                insert into {SUPABASE_DOCS_TABLE} (source, title, customer, content)
                values (%s, %s, %s, %s)
                """,
                (record.source, record.title, record.customer, record.content),
            )


def _db_update_doc(source: str, content: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"update {SUPABASE_DOCS_TABLE} set content = %s, updated_at = now() where source = %s",
                (content, source),
            )


def _db_soft_delete_doc(source: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"update {SUPABASE_DOCS_TABLE} set deleted_at = now() where source = %s and deleted_at is null",
                (source,),
            )


def _db_restore_doc(source: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"update {SUPABASE_DOCS_TABLE} set deleted_at = null where source = %s",
                (source,),
            )


def _db_permanent_delete_doc(source: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"delete from {SUPABASE_DOCS_TABLE} where source = %s", (source,))
            cur.execute(f"delete from {SUPABASE_CHUNKS_TABLE} where source = %s", (source,))


def _db_delete_chunks_for_source(source: str) -> None:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"delete from {SUPABASE_CHUNKS_TABLE} where source = %s", (source,))


def _db_delete_stale_chunks(valid_chunk_ids: list[str]) -> int:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            if valid_chunk_ids:
                cur.execute(f"delete from {SUPABASE_CHUNKS_TABLE} where not (chunk_id = any(%s))", (valid_chunk_ids,))
            else:
                cur.execute(f"delete from {SUPABASE_CHUNKS_TABLE}")
            return cur.rowcount


def _db_existing_chunk_hashes() -> dict[str, str]:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select chunk_id, body_hash from {SUPABASE_CHUNKS_TABLE}")
            return {row[0]: row[1] for row in cur.fetchall()}


def _db_upsert_search_chunks(rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = [
        (
            row["chunk_id"],
            row["document_id"],
            row["source"],
            row["title"],
            row.get("filename", ""),
            row.get("folder", ""),
            row.get("heading", ""),
            row["body"],
            row.get("normalized_body", ""),
            row.get("compact_body", ""),
            row["body_hash"],
            _vector_literal(row["embedding"]),
            row.get("updated_at"),
        )
        for row in rows
    ]
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                insert into {SUPABASE_CHUNKS_TABLE} (
                    chunk_id, document_id, source, title, filename, folder, heading,
                    body, normalized_body, compact_body, body_hash, embedding, updated_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                on conflict (chunk_id) do update set
                    document_id = excluded.document_id,
                    source = excluded.source,
                    title = excluded.title,
                    filename = excluded.filename,
                    folder = excluded.folder,
                    heading = excluded.heading,
                    body = excluded.body,
                    normalized_body = excluded.normalized_body,
                    compact_body = excluded.compact_body,
                    body_hash = excluded.body_hash,
                    embedding = excluded.embedding,
                    updated_at = excluded.updated_at,
                    indexed_at = now()
                """,
                payload,
            )
    return len(rows)


def _db_vector_search_chunks(query_embedding: list[float], limit: int) -> list[dict]:
    """Return nearest chunk ids from the pgvector index using cosine distance."""
    if not query_embedding or limit <= 0:
        return []
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select chunk_id, 1 - (embedding <=> %s::vector) as similarity
                from {SUPABASE_CHUNKS_TABLE}
                order by embedding <=> %s::vector
                limit %s
                """,
                (_vector_literal(query_embedding), _vector_literal(query_embedding), int(limit)),
            )
            return [
                {
                    "chunk_id": row[0],
                    "similarity": max(0.0, min(1.0, float(row[1] or 0.0))),
                }
                for row in cur.fetchall()
            ]


def _extract_asset_refs(source: str, content: str) -> list[str]:
    folder = PurePosixPath(source).parent.as_posix()
    paths = []
    for match in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', content):
        raw = match.group(1).strip().split()[0]
        if raw.startswith(("http://", "https://", "data:", "/")):
            continue
        resolved = f"{folder}/{raw}" if folder and folder != "." else raw
        paths.append(resolved)
    return paths


def _db_cascade_soft_delete_assets(source: str, content: str) -> None:
    paths = _extract_asset_refs(source, content)
    if not paths:
        return
    with _db_connect() as conn:
        with conn.cursor() as cur:
            for path in paths:
                cur.execute(
                    f"update {SUPABASE_ASSETS_TABLE} set deleted_at = now() where path = %s and deleted_at is null",
                    (path,),
                )


def _db_trash_records() -> dict:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"select source, title, customer, deleted_at from {SUPABASE_DOCS_TABLE} where deleted_at is not null order by deleted_at desc"
            )
            docs = [{"source": r[0], "title": r[1], "customer": r[2], "deleted_at": r[3].isoformat()} for r in cur.fetchall()]
            cur.execute(
                f"select path, size_bytes, deleted_at from {SUPABASE_ASSETS_TABLE} where deleted_at is not null order by deleted_at desc"
            )
            assets = [{"path": r[0], "size_bytes": r[1], "deleted_at": r[2].isoformat()} for r in cur.fetchall()]
    return {"docs": docs, "assets": assets}


def _doc_records() -> list[DocRecord]:
    return _db_doc_records() if SUPABASE_ENABLED else _file_doc_records()


def _doc_index_records() -> list[DocRecord]:
    return _db_doc_index_records() if SUPABASE_ENABLED else [DocRecord(r.source, r.title, r.customer, "", r.updated_at) for r in _file_doc_records()]


