from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import PurePosixPath
from typing import Iterable

from config import DOCS_DIR, SUPABASE_DOCS_TABLE, SUPABASE_ENABLED
from models import Chunk
from storage import (
    SUPABASE_CHUNKS_TABLE,
    _db_connect,
    _db_search_terms,
    _db_vector_search_chunks,
    _doc_records,
)
from rag import (
    build_context,
    calculate_recency_boost,
    char_ngram_tokens,
    clean_text,
    compact_search_text,
    normalize_search_text,
    split_markdown,
)


V2_TABLE = os.getenv("SUPABASE_CHUNKS_V2_TABLE", f"{SUPABASE_CHUNKS_TABLE}_v2")
V2_EMBEDDING_MODEL = os.getenv("RAG_V2_EMBEDDING_MODEL", "BAAI/bge-m3")
V2_EMBEDDING_DIM = int(os.getenv("RAG_V2_EMBEDDING_DIM", "1024"))
V2_QUERY_EMBEDDING_URL = os.getenv("RAG_V2_QUERY_EMBEDDING_URL", "").strip()
V2_RERANK_URL = os.getenv("RAG_V2_RERANK_URL", "").strip()

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
if not _IDENTIFIER_RE.fullmatch(V2_TABLE):
    raise ValueError("SUPABASE_CHUNKS_V2_TABLE must be a simple SQL identifier")


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


def _stable_document_id(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def _chunk_embedding_text(chunk: Chunk) -> str:
    return "\n".join(
        value
        for value in (
            f"문서 제목: {chunk.title}",
            f"폴더: {chunk.folder or ''}",
            f"파일명: {chunk.filename or chunk.source.rsplit('/', 1)[-1]}",
            f"섹션: {chunk.heading or ''}",
            f"내용: {chunk.text}",
        )
        if value.strip()
    )


def _text_hash(text: str) -> str:
    payload = f"{V2_EMBEDDING_MODEL}:{V2_EMBEDDING_DIM}\n{normalize_search_text(text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_schema() -> None:
    if not SUPABASE_ENABLED:
        raise RuntimeError("Supabase is not enabled.")
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("create extension if not exists vector")
            cur.execute(
                f"""
                create table if not exists {V2_TABLE} (
                    chunk_id text primary key,
                    document_id text not null,
                    document_pk bigint references {SUPABASE_DOCS_TABLE}(id) on delete cascade,
                    source text not null references {SUPABASE_DOCS_TABLE}(source) on update cascade on delete cascade,
                    title text not null,
                    filename text not null default '',
                    folder text not null default '',
                    heading text not null default '',
                    body text not null,
                    normalized_body text not null default '',
                    compact_body text not null default '',
                    body_hash text not null,
                    embedding_model text not null default '',
                    embedding_dim integer not null default {V2_EMBEDDING_DIM},
                    embedding vector({V2_EMBEDDING_DIM}),
                    updated_at timestamptz,
                    indexed_at timestamptz not null default now()
                )
                """
            )
            cur.execute(f"create index if not exists {V2_TABLE}_document_pk_idx on {V2_TABLE} (document_pk)")
            cur.execute(f"create index if not exists {V2_TABLE}_source_idx on {V2_TABLE} (source)")
            cur.execute(f"create index if not exists {V2_TABLE}_body_hash_idx on {V2_TABLE} (body_hash)")
            cur.execute(f"create index if not exists {V2_TABLE}_model_idx on {V2_TABLE} (embedding_model)")
            try:
                cur.execute(f"create index if not exists {V2_TABLE}_embedding_hnsw_idx on {V2_TABLE} using hnsw (embedding vector_cosine_ops)")
            except Exception:
                pass


def ensure_ready() -> None:
    if not SUPABASE_ENABLED:
        raise RuntimeError("Supabase is not enabled.")
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select exists (
                    select 1 from information_schema.tables
                    where table_schema = current_schema() and table_name = %s
                )
                """,
                (V2_TABLE,),
            )
            if not cur.fetchone()[0]:
                raise RuntimeError(f"{V2_TABLE} does not exist. Run v2/build_bge_m3_index.py first.")


class BgeM3Embedder:
    def __init__(self, model_name: str = V2_EMBEDDING_MODEL) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError as exc:
            raise RuntimeError("Install backend/requirements-embeddings.txt to build the v2 BGE-M3 index.") from exc
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        result: list[list[float]] = []
        for vector in vectors:
            values = [float(value) for value in vector.tolist()]
            if len(values) != V2_EMBEDDING_DIM:
                raise RuntimeError(f"Expected {V2_EMBEDDING_DIM}-dim embeddings, got {len(values)}.")
            result.append(values)
        return result


def _iter_chunks(limit: int | None = None) -> list[Chunk]:
    chunks: list[Chunk] = []
    for record in _doc_records():
        path = DOCS_DIR / record.source
        chunks.extend(split_markdown(path, clean_text(record.content), updated_at=record.updated_at))
        if limit and len(chunks) >= limit:
            return chunks[:limit]
    return chunks


def _existing_hashes() -> dict[str, str]:
    ensure_schema()
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"select chunk_id, body_hash from {V2_TABLE} where embedding_model = %s", (V2_EMBEDDING_MODEL,))
            return {row[0]: row[1] for row in cur.fetchall()}


def _delete_stale(valid_ids: list[str]) -> int:
    with _db_connect() as conn:
        with conn.cursor() as cur:
            if valid_ids:
                cur.execute(f"delete from {V2_TABLE} where embedding_model = %s and not (chunk_id = any(%s))", (V2_EMBEDDING_MODEL, valid_ids))
            else:
                cur.execute(f"delete from {V2_TABLE} where embedding_model = %s", (V2_EMBEDDING_MODEL,))
            return cur.rowcount


def _upsert(rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = [
        (
            row["chunk_id"],
            row["document_id"],
            row["source"],
            row["source"],
            row["title"],
            row["filename"],
            row["folder"],
            row["heading"],
            row["body"],
            row["normalized_body"],
            row["compact_body"],
            row["body_hash"],
            V2_EMBEDDING_MODEL,
            V2_EMBEDDING_DIM,
            _vector_literal(row["embedding"]),
            row.get("updated_at"),
        )
        for row in rows
    ]
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                f"""
                insert into {V2_TABLE} (
                    chunk_id, document_id, document_pk, source, title, filename, folder, heading,
                    body, normalized_body, compact_body, body_hash, embedding_model, embedding_dim, embedding, updated_at
                )
                values (
                    %s, %s, (select id from {SUPABASE_DOCS_TABLE} where source = %s),
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s
                )
                on conflict (chunk_id) do update set
                    document_id = excluded.document_id,
                    document_pk = excluded.document_pk,
                    source = excluded.source,
                    title = excluded.title,
                    filename = excluded.filename,
                    folder = excluded.folder,
                    heading = excluded.heading,
                    body = excluded.body,
                    normalized_body = excluded.normalized_body,
                    compact_body = excluded.compact_body,
                    body_hash = excluded.body_hash,
                    embedding_model = excluded.embedding_model,
                    embedding_dim = excluded.embedding_dim,
                    embedding = excluded.embedding,
                    updated_at = excluded.updated_at,
                    indexed_at = now()
                """,
                payload,
            )
    return len(rows)


def build_bge_m3_index(force: bool = False, limit: int | None = None, batch_size: int = 32) -> dict:
    ensure_schema()
    chunks = _iter_chunks(limit=limit)
    valid_ids = [chunk.chunk_id for chunk in chunks if chunk.chunk_id]
    stale_deleted = _delete_stale(valid_ids) if not limit else 0
    existing = _existing_hashes()
    embedder = BgeM3Embedder()
    upserted = 0
    skipped = 0
    pending: list[tuple[Chunk, str, str]] = []

    def flush() -> None:
        nonlocal upserted, pending
        if not pending:
            return
        texts = [item[2] for item in pending]
        embeddings = embedder.encode(texts)
        rows = []
        for (chunk, body_hash, _text), embedding in zip(pending, embeddings):
            rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id or _stable_document_id(chunk.source),
                    "source": chunk.source,
                    "title": chunk.title,
                    "filename": chunk.filename or chunk.source.rsplit("/", 1)[-1],
                    "folder": chunk.folder if chunk.folder is not None else (chunk.source.rsplit("/", 1)[0] if "/" in chunk.source else ""),
                    "heading": chunk.heading or chunk.title,
                    "body": chunk.text,
                    "normalized_body": chunk.normalized_body or normalize_search_text(chunk.text),
                    "compact_body": chunk.compact_body or compact_search_text(chunk.text),
                    "body_hash": body_hash,
                    "embedding": embedding,
                    "updated_at": chunk.updated_at,
                }
            )
        upserted += _upsert(rows)
        pending = []

    for chunk in chunks:
        if not chunk.chunk_id:
            continue
        text = _chunk_embedding_text(chunk)
        body_hash = _text_hash(text)
        if not force and existing.get(chunk.chunk_id) == body_hash:
            skipped += 1
            continue
        pending.append((chunk, body_hash, text))
        if len(pending) >= batch_size:
            flush()
    flush()
    return {
        "ok": True,
        "table": V2_TABLE,
        "embeddingModel": V2_EMBEDDING_MODEL,
        "chunks": len(chunks),
        "upserted": upserted,
        "skipped": skipped,
        "staleDeleted": stale_deleted,
        "force": force,
    }


def _row_to_chunk(row: dict) -> Chunk:
    source = str(row.get("source") or "")
    body = str(row.get("body") or "")
    return Chunk(
        text=body,
        source=source,
        title=str(row.get("title") or source.rsplit("/", 1)[-1]),
        document_id=str(row.get("document_id") or _stable_document_id(source)),
        chunk_id=str(row.get("chunk_id") or ""),
        heading=str(row.get("heading") or row.get("title") or ""),
        filename=str(row.get("filename") or source.rsplit("/", 1)[-1]),
        folder=str(row.get("folder") or (source.rsplit("/", 1)[0] if "/" in source else "")),
        updated_at=row.get("updated_at"),
        normalized_body=str(row.get("normalized_body") or normalize_search_text(body)),
        compact_body=str(row.get("compact_body") or compact_search_text(body)),
    )


def _search_lexical(query: str, limit: int) -> list[dict]:
    terms = _db_search_terms(query)
    if not terms:
        return []
    clauses = []
    score_exprs = []
    where_params: list[str] = []
    score_params: list[str] = []
    for term in terms:
        pattern = f"%{term}%"
        score_exprs.append(
            """
            (case when c.title ilike %s then 12 else 0 end) +
            (case when c.filename ilike %s then 8 else 0 end) +
            (case when c.folder ilike %s then 8 else 0 end) +
            (case when c.heading ilike %s then 6 else 0 end) +
            (case when c.source ilike %s then 5 else 0 end) +
            (case when c.normalized_body ilike %s then 2 else 0 end) +
            (case when c.body ilike %s then 1 else 0 end)
            """
        )
        score_params.extend([pattern, pattern, pattern, pattern, pattern, pattern, pattern])
        clauses.append(
            """
            c.title ilike %s or c.filename ilike %s or c.folder ilike %s or
            c.heading ilike %s or c.source ilike %s or c.normalized_body ilike %s or c.body ilike %s
            """
        )
        where_params.extend([pattern, pattern, pattern, pattern, pattern, pattern, pattern])
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select c.chunk_id, c.document_id, c.source, c.title, c.filename, c.folder, c.heading,
                       c.body, c.normalized_body, c.compact_body, c.updated_at,
                       ({" + ".join(score_exprs)}) as match_score
                from {V2_TABLE} c
                join {SUPABASE_DOCS_TABLE} d on d.source = c.source and d.deleted_at is null
                where c.embedding_model = %s and ({" or ".join(clauses)})
                order by match_score desc, c.updated_at desc nulls last, c.source, c.chunk_id
                limit %s
                """,
                [*score_params, V2_EMBEDDING_MODEL, *where_params, int(limit)],
            )
            return [
                {
                    "chunk_id": row[0],
                    "document_id": row[1],
                    "source": row[2],
                    "title": row[3],
                    "filename": row[4],
                    "folder": row[5],
                    "heading": row[6],
                    "body": row[7],
                    "normalized_body": row[8],
                    "compact_body": row[9],
                    "updated_at": row[10].isoformat() if row[10] else None,
                    "score": float(row[11] or 0.0),
                }
                for row in cur.fetchall()
            ]


def _query_embedding(query: str) -> list[float]:
    if not V2_QUERY_EMBEDDING_URL:
        return []
    request = urllib.request.Request(
        V2_QUERY_EMBEDDING_URL,
        data=json.dumps({"text": query, "model": V2_EMBEDDING_MODEL}).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310
        payload = json.loads(response.read().decode("utf-8"))
    values = [float(value) for value in payload.get("embedding", [])]
    return values if len(values) == V2_EMBEDDING_DIM else []


def _search_vector(query_embedding: list[float], limit: int) -> list[dict]:
    if not query_embedding:
        return []
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select c.chunk_id, c.document_id, c.source, c.title, c.filename, c.folder, c.heading,
                       c.body, c.normalized_body, c.compact_body, c.updated_at,
                       1 - (c.embedding <=> %s::vector) as similarity
                from {V2_TABLE} c
                join {SUPABASE_DOCS_TABLE} d on d.source = c.source and d.deleted_at is null
                where c.embedding_model = %s and c.embedding is not null
                order by c.embedding <=> %s::vector
                limit %s
                """,
                (_vector_literal(query_embedding), V2_EMBEDDING_MODEL, _vector_literal(query_embedding), int(limit)),
            )
            return [
                {
                    "chunk_id": row[0],
                    "document_id": row[1],
                    "source": row[2],
                    "title": row[3],
                    "filename": row[4],
                    "folder": row[5],
                    "heading": row[6],
                    "body": row[7],
                    "normalized_body": row[8],
                    "compact_body": row[9],
                    "updated_at": row[10].isoformat() if row[10] else None,
                    "vector_score": max(0.0, min(1.0, float(row[11] or 0.0))),
                }
                for row in cur.fetchall()
            ]


def _rerank_external(query: str, candidates: list[tuple[Chunk, float]], top_k: int) -> list[tuple[Chunk, float]] | None:
    if not V2_RERANK_URL or not candidates:
        return None
    docs = [
        {"id": chunk.chunk_id or str(idx), "text": f"{chunk.title}\n{chunk.heading or ''}\n{chunk.text}"}
        for idx, (chunk, _score) in enumerate(candidates)
    ]
    request = urllib.request.Request(
        V2_RERANK_URL,
        data=json.dumps({"query": query, "documents": docs, "top_k": top_k}, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        payload = json.loads(response.read().decode("utf-8"))
    score_by_id = {str(item.get("id")): float(item.get("score", 0.0)) for item in payload.get("results", [])}
    if not score_by_id:
        return None
    reranked = [(chunk, score_by_id.get(chunk.chunk_id or "", score)) for chunk, score in candidates]
    reranked.sort(key=lambda item: item[1], reverse=True)
    return reranked[:top_k]


def retrieve(query: str, top_k: int = 5, candidate_limit: int = 50) -> tuple[list[tuple[Chunk, float]], str, dict]:
    query = query.strip()
    if not query:
        return [], "", {"backend": "v2", "reason": "empty query"}
    ensure_ready()
    lexical_rows = _search_lexical(query, candidate_limit)
    vector_rows = _search_vector(_query_embedding(query), candidate_limit)

    merged: dict[str, dict] = {}
    for row in lexical_rows:
        row["lexical_score"] = float(row.get("score") or 0.0)
        merged[str(row["chunk_id"])] = row
    for rank, row in enumerate(vector_rows):
        chunk_id = str(row["chunk_id"])
        existing = merged.setdefault(chunk_id, row)
        existing["vector_score"] = max(float(existing.get("vector_score") or 0.0), float(row.get("vector_score") or 0.0))
        existing["vector_rank_score"] = 1.0 / (rank + 1)

    if not merged:
        return [], "", {"backend": "v2", "lexicalCandidates": 0, "vectorCandidates": 0}

    max_lexical = max((float(row.get("lexical_score") or 0.0) for row in merged.values()), default=1.0) or 1.0
    query_terms = set(_db_search_terms(query))
    query_ngrams = char_ngram_tokens(query)
    scored: list[tuple[Chunk, float]] = []
    for row in merged.values():
        chunk = _row_to_chunk(row)
        searchable = "\n".join([chunk.title, chunk.folder or "", chunk.heading or "", chunk.source, chunk.text])
        normalized = normalize_search_text(searchable)
        field_hit = 1.0 if any(term in normalized for term in query_terms) else 0.0
        lexical_score = float(row.get("lexical_score") or 0.0) / max_lexical
        vector_score = float(row.get("vector_score") or 0.0)
        ngram_score = 0.0 if not query_terms else len(query_ngrams & char_ngram_tokens(searchable)) / max(1, len(query_ngrams | char_ngram_tokens(searchable)))
        score = lexical_score * 0.45 + vector_score * 0.30 + field_hit * 0.15 + ngram_score * 0.05 + calculate_recency_boost(chunk.updated_at, 0.05)
        if lexical_score <= 0 and field_hit <= 0 and not vector_score:
            continue
        scored.append((chunk, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    candidates = scored[: max(top_k, min(candidate_limit, 30))]
    try:
        reranked = _rerank_external(query, candidates, top_k)
    except Exception:
        reranked = None
    results = reranked if reranked is not None else candidates[:top_k]
    return results, build_context(results), {
        "backend": "v2",
        "table": V2_TABLE,
        "embeddingModel": V2_EMBEDDING_MODEL,
        "lexicalCandidates": len(lexical_rows),
        "vectorCandidates": len(vector_rows),
        "reranker": "external" if reranked is not None else "disabled",
    }


def search_documents(query: str, top_k: int = 5) -> dict:
    results, _context, debug = retrieve(query, top_k=top_k)
    grouped: dict[str, dict] = {}
    for chunk, score in results:
        doc_id = chunk.document_id or _stable_document_id(chunk.source)
        item = {
            "chunk_id": chunk.chunk_id,
            "heading": chunk.heading or chunk.title,
            "matched_text": re.sub(r"\s+", " ", chunk.text).strip()[:700],
            "score": round(score, 4),
            "score_detail": {"backend": "v2"},
        }
        if doc_id not in grouped:
            grouped[doc_id] = {
                "document_id": doc_id,
                "title": chunk.title,
                "filename": chunk.filename or chunk.source.rsplit("/", 1)[-1],
                "folder": chunk.folder or "",
                "source": chunk.source,
                "matched_heading": chunk.heading or chunk.title,
                "matched_text": item["matched_text"],
                "snippet": item["matched_text"],
                "score": round(score, 4),
                "score_detail": {"backend": "v2"},
                "related_chunks": [],
            }
        else:
            grouped[doc_id]["related_chunks"].append(item)
    return {"results": list(grouped.values())[:top_k], "debug": debug}
