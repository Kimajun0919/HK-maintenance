from __future__ import annotations

import os
import re
import math
import json
import mimetypes
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import Request
from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR.parent / ".env", override=False)
load_dotenv(APP_DIR / ".env", override=False)

DEFAULT_DOCS_DIR = APP_DIR / "organized_maintenance_docs_simple"
if not DEFAULT_DOCS_DIR.exists():
    DEFAULT_DOCS_DIR = APP_DIR.parent / "organized_maintenance_docs_simple"
DOCS_DIR = Path(os.getenv("DOCS_DIR", DEFAULT_DOCS_DIR)).resolve()
MODEL_NAME = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
USE_LLM = os.getenv("USE_LLM", "1") != "0"
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "512"))
DEFAULT_CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL", "")
DOC_STORAGE = os.getenv("DOC_STORAGE", "supabase" if SUPABASE_DB_URL else "files").strip().lower()
SUPABASE_ENABLED = DOC_STORAGE == "supabase" and bool(SUPABASE_DB_URL)
SUPABASE_AUTO_MIGRATE = os.getenv("SUPABASE_AUTO_MIGRATE", "1") != "0"
SUPABASE_SEED_FROM_FILES = os.getenv("SUPABASE_SEED_FROM_FILES", "1") != "0"
ASSET_MAX_SIZE_MB = float(os.getenv("ASSET_MAX_SIZE_MB", "2"))
ASSET_MAX_SIZE_BYTES = int(ASSET_MAX_SIZE_MB * 1024 * 1024)
SUPABASE_DOCS_TABLE = os.getenv("SUPABASE_DOCS_TABLE", "maintenance_docs")
SUPABASE_ASSETS_TABLE = os.getenv("SUPABASE_ASSETS_TABLE", f"{SUPABASE_DOCS_TABLE}_assets")
SUPABASE_FOLDERS_TABLE = os.getenv("SUPABASE_FOLDERS_TABLE", f"{SUPABASE_DOCS_TABLE}_folders")
SUPABASE_META_TABLE = f"{SUPABASE_DOCS_TABLE}_meta"
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", SUPABASE_DOCS_TABLE):
    raise ValueError("SUPABASE_DOCS_TABLE must be a simple SQL identifier")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", SUPABASE_ASSETS_TABLE):
    raise ValueError("SUPABASE_ASSETS_TABLE must be a simple SQL identifier")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", SUPABASE_FOLDERS_TABLE):
    raise ValueError("SUPABASE_FOLDERS_TABLE must be a simple SQL identifier")


QUERY_ALIASES = {
    "시도지사": "시도지사협의회 대한시도지사협회",
    "대한시도지사": "시도지사협의회 대한시도지사협회",
    "차세대": "KIAPS_차세대 KIAPS",
    "대한항공": "대한항공씨앤디서비스 KCND",
    "안과": "안과의사회 대한안과의사회 KIOS",
    "고혈압": "고혈압학회 대한고혈압학회",
    "순환자원": "한국순환자원 한국순환자원유통지원센터 KORA",
    "성의교정": "성의교정_공동연구지원센터 성의교정_카톨릭대학교",
}

INTENT_EXPANSIONS = {
    "접속정보": "접속 정보 계정 로그인 관리자 URL VPN FTP 서버 클라우드 id pw password host 경로",
    "접속 정보": "접속 정보 계정 로그인 관리자 URL VPN FTP 서버 클라우드 id pw password host 경로",
    "계정": "계정 로그인 id pw password 관리자",
    "서버": "서버 host 경로 FTP VPN",
    "경로": "경로 디렉토리 폴더 서버 파일",
    "보고서": "보고서 월간 내역서 점검대장 발송",
}


@dataclass
class Chunk:
    text: str
    source: str
    title: str


@dataclass
class DocRecord:
    source: str
    title: str
    customer: str
    content: str
    updated_at: str | None = None


@dataclass
class AssetRecord:
    path: str
    mime_type: str
    content: bytes


@dataclass
class FolderRecord:
    name: str
    sort_order: int


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
    return psycopg.connect(SUPABASE_DB_URL, autocommit=True)


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


def clean_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_markdown(path: Path, text: str, max_chars: int = 1800, overlap: int = 250) -> list[Chunk]:
    rel = path.relative_to(DOCS_DIR).as_posix()
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.M)
    title = title_match.group(1).strip() if title_match else path.stem

    sections = re.split(r"(?=^#{1,3}\s+)", text, flags=re.M)
    chunks: list[Chunk] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        section_title_match = re.search(r"^#{1,3}\s+(.+)$", section, flags=re.M)
        section_title = section_title_match.group(1).strip() if section_title_match else title
        if any(
            skip in section_title
            for skip in (
                "문서 개요",
                "핵심 요약",
                "상세 내용",
                "작업 절차",
                "주의사항",
                "오류 및 대응 방법",
                "확인 필요 사항",
                "원본 보존 내용",
                "기존 정리본 문서",
                "공통 작업 가능 여부",
            )
        ):
            continue

        start = 0
        while start < len(section):
            end = min(start + max_chars, len(section))
            part = section[start:end].strip()
            if len(part) >= 80:
                chunks.append(Chunk(text=part, source=rel, title=section_title))
            if end == len(section):
                break
            start = max(0, end - overlap)
    return chunks


def load_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for record in _doc_records():
        path = DOCS_DIR / record.source
        text = clean_text(record.content)
        if text:
            chunks.extend(split_markdown(path, text))
    return chunks


class Retriever:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.vectors = [self._vector(f"{c.title}\n{c.source}\n{c.text}") for c in chunks]
        self.norms = [self._norm(v) for v in self.vectors]

    @staticmethod
    def _ngrams(text: str) -> list[str]:
        compact = re.sub(r"\s+", " ", text.lower())
        grams: list[str] = []
        for n in (2, 3, 4):
            grams.extend(compact[i : i + n] for i in range(max(0, len(compact) - n + 1)))
        tokens = re.findall(r"[가-힣A-Za-z0-9_./:@!+-]{2,}", text.lower())
        grams.extend(tokens)
        return grams

    @staticmethod
    def _expand_query(query: str) -> str:
        expanded = [query]
        compact_query = query.replace(" ", "")
        for key, value in QUERY_ALIASES.items():
            if key.replace(" ", "") in compact_query:
                expanded.append(value)
        for key, value in INTENT_EXPANSIONS.items():
            if key.replace(" ", "") in compact_query:
                expanded.append(value)
        return " ".join(expanded)

    @classmethod
    def _vector(cls, text: str) -> Counter[str]:
        return Counter(cls._ngrams(text))

    @staticmethod
    def _norm(vector: Counter[str]) -> float:
        return math.sqrt(sum(value * value for value in vector.values()))

    @staticmethod
    def _cosine(left: Counter[str], left_norm: float, right: Counter[str], right_norm: float) -> float:
        if not left_norm or not right_norm:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        dot = sum(value * right.get(key, 0) for key, value in left.items())
        return dot / (left_norm * right_norm)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        expanded_query = self._expand_query(query)
        qv = self._vector(expanded_query)
        qn = self._norm(qv)
        query_terms = set(re.findall(r"[가-힣A-Za-z0-9_]{2,}", expanded_query.lower()))
        compact_query = expanded_query.lower().replace(" ", "")
        wants_report = any(term in compact_query for term in ("보고서", "월간", "내역서", "점검대장"))
        wants_access = any(term in compact_query for term in ("접속정보", "접속", "계정", "로그인", "서버", "경로"))
        scored = []
        for idx, (vector, norm) in enumerate(zip(self.vectors, self.norms)):
            score = self._cosine(qv, qn, vector, norm)
            chunk = self.chunks[idx]
            source_title = f"{chunk.source} {chunk.title}".lower()
            folder = chunk.source.split("/", 1)[0].lower()
            folder_boost = 0.55 if folder and folder in compact_query else 0.0
            exact_boost = sum(0.04 for term in query_terms if term in source_title)
            exact_boost += folder_boost
            if folder == "공통자료" and not wants_report:
                exact_boost -= 0.35
            if wants_access:
                access_text = f"{chunk.title}\n{chunk.text}".lower()
                access_hits = sum(
                    1
                    for term in ("접속", "계정", "로그인", "관리자", "vpn", "ftp", "id", "pw", "password", "host", "클라우드", "경로")
                    if term in access_text
                )
                exact_boost += min(access_hits * 0.035, 0.28)
            scored.append((idx, score + exact_boost))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [(self.chunks[idx], score) for idx, score in scored[:top_k] if score > 0]


class LocalLLM:
    def __init__(self):
        self.enabled = False
        self.error = ""
        self.tokenizer = None
        self.model = None
        if not USE_LLM:
            self.error = "USE_LLM=0"
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            self.model = AutoModelForCausalLM.from_pretrained(
                MODEL_NAME,
                torch_dtype=torch.float32,
                device_map="cpu",
                low_cpu_mem_usage=True,
            )
            self.model.eval()
            self.enabled = True
        except Exception as exc:
            self.error = str(exc)

    def generate(self, prompt: str) -> str:
        if not self.enabled or self.model is None or self.tokenizer is None:
            return ""

        import torch

        messages = [
            {
                "role": "system",
                "content": (
                    "너는 홈페이지코리아 유지보수 문서 RAG 챗봇이다. "
                    "반드시 제공된 근거 안에서만 답하고, 모르면 확인 필요라고 말한다. "
                    "계정, 경로, 서버, 주의사항은 임의로 바꾸지 않는다."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        if hasattr(self.tokenizer, "apply_chat_template"):
            text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        else:
            text = f"System: {messages[0]['content']}\nUser: {prompt}\nAssistant:"

        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=4096)
        with torch.no_grad():
            output = self.model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                temperature=None,
                top_p=None,
                repetition_penalty=1.08,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        generated = output[0][inputs["input_ids"].shape[-1] :]
        return self.tokenizer.decode(generated, skip_special_tokens=True).strip()


llm_instance: LocalLLM | None = None


def get_llm() -> LocalLLM:
    global llm_instance
    if llm_instance is None:
        llm_instance = LocalLLM()
    return llm_instance


def build_context(results: list[tuple[Chunk, float]], max_chars: int = 5200) -> str:
    parts: list[str] = []
    used = 0
    for idx, (chunk, score) in enumerate(results, 1):
        item = (
            f"[근거 {idx}] score={score:.3f}\n"
            f"파일: {chunk.source}\n"
            f"섹션: {chunk.title}\n"
            f"{chunk.text}\n"
        )
        if used + len(item) > max_chars:
            break
        parts.append(item)
        used += len(item)
    return "\n---\n".join(parts)


def source_based_answer(query: str, results: list[tuple[Chunk, float]]) -> str:
    if not results:
        return "관련 문서를 찾지 못했습니다. 고객사명이나 기능명을 더 구체적으로 입력해 주세요."

    best_source = results[0][0].source
    primary = []
    seen_chunk_text: set[str] = set()
    seen_titles: set[str] = set()
    for chunk, score in results:
        if chunk.source != best_source:
            continue
        if is_noise_title_for_answer(query, chunk.title):
            continue
        if chunk.title in seen_titles:
            continue
        seen_titles.add(chunk.title)
        key = re.sub(r"\s+", " ", chunk.text[:500])
        if key in seen_chunk_text:
            continue
        seen_chunk_text.add(key)
        primary.append((chunk, score))
    if not primary:
        primary = [(chunk, score) for chunk, score in results[:2] if not is_noise_title_for_answer(query, chunk.title)]
    if not primary:
        primary = results[:1]

    lines = [
        "## 검색 기반 답변",
        "",
        f"질문과 가장 관련도가 높은 문서는 `{best_source}`입니다.",
        "",
        "### 핵심 근거",
    ]
    for idx, (chunk, score) in enumerate(primary[:3], 1):
        lines.append(f"{idx}. `{chunk.title}`")
        bullets = extract_readable_bullets(chunk.text)
        for bullet in bullets[:10]:
            lines.append(f"   - {bullet}")

    lines.extend(["", "### 참고 문서"])
    seen: set[str] = set()
    for chunk, score in results:
        if is_noise_title_for_answer(query, chunk.title):
            continue
        key = f"{chunk.source}|{chunk.title}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- `{chunk.source}` / {chunk.title} / score={score:.3f}")
    return "\n".join(lines)


def is_noise_title_for_answer(query: str, title: str) -> bool:
    compact_query = query.replace(" ", "")
    title_compact = title.replace(" ", "")
    noise_titles = (
        "문서개요",
        "핵심요약",
        "상세내용",
        "작업절차",
        "주의사항",
        "오류및대응방법",
        "관련이미지",
        "원본보존내용",
        "확인필요사항",
        "기존정리본문서",
        "HK매뉴얼에서확인된고객사별정보",
    )
    if any(noise in title_compact for noise in noise_titles):
        return True
    if "보고서" in title_compact and not any(term in compact_query for term in ("보고서", "월간", "내역", "점검")):
        return True
    return False


def extract_readable_bullets(text: str) -> list[str]:
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = text.replace("아래 내용은 원본 md 문서의 본문 전체입니다.", "")
    text = text.replace("내용 누락 방지를 위해 원문 표현, 계정 정보, 경로, URL, 메모를 삭제하지 않고 보존했습니다.", "")

    candidates: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        if line.startswith("|") and line.endswith("|"):
            continue
        if line in {"```", "````markdown", "````"}:
            continue
        if len(line) > 220:
            parts = re.split(
                r"\s{2,}|(?<=\))\s+|(?<=!)\s+|(?=https?://)|(?=\b[a-zA-Z0-9_.-]{3,}\s+[A-Za-z0-9!@#$%^&*()_+=~.-]{4,})",
                line,
            )
            candidates.extend(part.strip() for part in parts if part.strip())
        else:
            candidates.append(line)

    important: list[str] = []
    keywords = [
        "http", "https", "id", "pw", "비밀번호", "계정", "인증", "접속", "경로",
        "서버", "관리자", "주의", "적용", "메인", "이미지", "inc", "ftp", "vpn",
    ]
    for line in candidates:
        lower = line.lower()
        if any(keyword in lower for keyword in keywords) or re.search(r"[/\\][\w가-힣./\\_-]+", line):
            important.append(line)
    for line in candidates:
        if line not in important:
            important.append(line)

    deduped: list[str] = []
    seen: set[str] = set()
    for line in important:
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


_init_supabase_storage()
chunks = load_chunks()
retriever = Retriever(chunks)


def refresh_index() -> None:
    global chunks, retriever
    chunks = load_chunks()
    retriever = Retriever(chunks)


def retrieve(query: str, top_k: int) -> tuple[list[tuple[Chunk, float]], str]:
    query = query.strip()
    if not query:
        return [], ""

    results = retriever.search(query, top_k=top_k)
    context = build_context(results)
    return results, context


def immediate_answer(query: str, top_k: int) -> str:
    query = query.strip()
    if not query:
        return "질문을 입력해 주세요."

    results, context = retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 오류명, 서버/계정/작업명을 포함해 다시 질문해 주세요."

    return source_based_answer(query, results)


def llm_answer(query: str, top_k: int) -> str:
    results, context = retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 오류명, 서버/계정/작업명을 포함해 다시 질문해 주세요."

    prompt = f"""질문:
{query}

문서 근거:
{context}

답변 조건:
- 근거에 있는 내용만 사용
- 고객사별 작업 절차, 계정, 서버, 경로, 주의사항은 원문 그대로 유지
- 불확실하면 "확인 필요"라고 표시
- 마지막에 참고한 파일명을 bullet로 표시
"""
    llm = get_llm()
    generated = llm.generate(prompt)
    if not generated:
        generated = source_based_answer(query, results)

    sources = "\n".join(
        f"- `{chunk.source}` / {chunk.title} / score={score:.3f}"
        for chunk, score in results
    )
    return f"{generated}\n\n---\n참고 문서:\n{sources}"


def answer(query: str, top_k: int, history: list[dict] | None = None) -> str:
    if USE_LLM:
        return llm_answer(query, top_k)
    return immediate_answer(query, top_k)


def claude_answer(query: str, top_k: int, api_key: str, model: str) -> str:
    api_key = api_key.strip()
    model = (model or DEFAULT_CLAUDE_MODEL).strip()
    if not api_key:
        return "Claude API 키를 입력해야 합니다."

    results, context = retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 작업명, 서버/계정/경로 같은 단어를 포함해 다시 질문해 주세요."

    sources = "\n".join(f"- `{chunk.source}` / {chunk.title} / score={score:.3f}" for chunk, score in results)
    prompt = f"""질문:
{query}

문서 근거:
{context}

답변 조건:
- 반드시 위 문서 근거 안의 내용만 사용하세요.
- 계정, 경로, 서버, 작업 절차, 주의사항은 원문 값을 임의로 바꾸지 마세요.
- 근거에 없으면 "확인 필요"라고 답하세요.
- 답변 마지막에 참고 문서 파일명을 bullet로 정리하세요.
"""
    payload = {
        "model": model,
        "max_tokens": MAX_NEW_TOKENS,
        "system": "당신은 HK 유지보수 문서 RAG 도우미입니다. 제공된 문서 근거만 바탕으로 한국어로 간결하고 정확하게 답변합니다.",
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return f"Claude API 오류({exc.code}): {body[:700]}"
    except Exception as exc:
        return f"Claude API 호출 실패: {exc}"

    parts = []
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")).strip())
    generated = "\n\n".join(part for part in parts if part)
    if not generated:
        generated = source_based_answer(query, results)
    return f"{generated}\n\n---\n참고 문서:\n{sources}"


def build_demo():
    import gradio as gr

    with gr.Blocks(title="HK Maintenance RAG Chatbot") as demo:
        gr.Markdown(
            f"""
# HK Maintenance RAG Chatbot

- 문서 경로: `{DOCS_DIR}`
- 문서 청크: `{len(chunks)}`
- LLM: `{MODEL_NAME if USE_LLM else "비활성"}`
"""
        )
        if USE_LLM:
            gr.Markdown("검색 결과를 먼저 표시한 뒤, LLM 답변이 준비되면 같은 답변 영역을 업데이트합니다.")
        try:
            chatbot = gr.Chatbot(type="messages", height=520)
        except TypeError:
            chatbot = gr.Chatbot(height=520)
        data_model_name = getattr(getattr(chatbot, "data_model", None), "__name__", "")
        chat_format = "messages" if "Messages" in data_model_name else "tuples"
        query = gr.Textbox(label="질문", placeholder="예: 대한항공 VPN 접속 방법 알려줘")
        top_k = gr.Slider(label="검색 근거 수", minimum=2, maximum=8, value=5, step=1)
        generate_llm = gr.Checkbox(
            label="LLM 답변도 생성",
            value=False,
            interactive=USE_LLM,
            info="무료 CPU에서는 느리고 품질이 낮을 수 있습니다. 기본 답변은 검색 근거 기반입니다.",
        )
        gr.ClearButton([query, chatbot])

        def normalize_history(chat_history: list | None) -> list:
            chat_history = chat_history or []
            normalized: list = []
            if chat_format == "messages":
                for item in chat_history:
                    if isinstance(item, dict) and "role" in item and "content" in item:
                        normalized.append(item)
                    elif isinstance(item, (list, tuple)) and len(item) == 2:
                        user_msg, assistant_msg = item
                        normalized.append({"role": "user", "content": str(user_msg)})
                        normalized.append({"role": "assistant", "content": str(assistant_msg)})
                return normalized

            for item in chat_history:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    normalized.append((str(item[0]), str(item[1])))
                elif isinstance(item, dict) and item.get("role") == "user":
                    normalized.append((str(item.get("content", "")), ""))
                elif isinstance(item, dict) and item.get("role") == "assistant":
                    if normalized and normalized[-1][1] == "":
                        normalized[-1] = (normalized[-1][0], str(item.get("content", "")))
                    else:
                        normalized.append(("", str(item.get("content", ""))))
            return normalized

        def respond(message: str, chat_history: list, k: int, use_llm_for_question: bool):
            chat_history = normalize_history(chat_history)
            bot_message = immediate_answer(message, int(k))
            if chat_format == "messages":
                chat_history = chat_history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": bot_message},
                ]
            else:
                chat_history = chat_history + [(message, bot_message)]
            yield "", chat_history

            if not USE_LLM or not use_llm_for_question:
                return

            llm_message = llm_answer(message, int(k))
            combined = (
                f"{bot_message}\n\n"
                "---\n"
                "<details><summary>LLM 답변 보기</summary>\n\n"
                f"{llm_message}"
                "\n\n</details>"
            )
            if chat_format == "messages":
                chat_history[-1] = {"role": "assistant", "content": combined}
            else:
                chat_history[-1] = (message, combined)
            yield "", chat_history

        query.submit(respond, [query, chatbot, top_k, generate_llm], [query, chatbot])
    return demo


try:
    demo = build_demo()
except ModuleNotFoundError as exc:
    if exc.name != "gradio":
        raise
    demo = None

WEB_DIR = APP_DIR / "web"


def _json_response(data, status_code: int = 200):
    from fastapi.responses import JSONResponse

    return JSONResponse(data, status_code=status_code)


def _safe_doc_path(source: str) -> Path | None:
    try:
        path = (DOCS_DIR / source).resolve()
        path.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if not path.exists() or path.suffix.lower() != ".md":
        return None
    return path


def _safe_new_doc_path(source: str) -> Path | None:
    normalized = urllib.parse.unquote(str(source or "")).replace("\\", "/").strip("/")
    if not normalized or normalized.startswith(".") or "/." in normalized:
        return None
    if not normalized.lower().endswith(".md"):
        normalized += ".md"
    try:
        path = (DOCS_DIR / normalized).resolve()
        path.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if path.name in {"README.md", "SIMPLIFY_CHANGELOG.md", "SIMPLIFY_VALIDATION_REPORT.md"}:
        return None
    return path


def _safe_source_value(source: str, require_md: bool = True) -> str | None:
    normalized = urllib.parse.unquote(str(source or "")).replace("\\", "/").strip("/")
    if not normalized or normalized.startswith(".") or "/." in normalized:
        return None
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    if require_md and not normalized.lower().endswith(".md"):
        normalized += ".md"
    if PurePosixPath(normalized).name in {"README.md", "SIMPLIFY_CHANGELOG.md", "SIMPLIFY_VALIDATION_REPORT.md"}:
        return None
    return normalized


def _safe_folder_name(name: str) -> str | None:
    normalized = _slug_part(str(name or "").strip(), "")
    if not normalized or "/" in normalized or "\\" in normalized:
        return None
    if normalized.startswith(".") or normalized in {".", ".."}:
        return None
    return normalized


def _slug_part(value: str, fallback: str = "document") -> str:
    value = re.sub(r'[<>:"|?*\x00-\x1f]+', "", str(value or "")).strip()
    value = value.replace("\\", "/").split("/")[-1].strip()
    value = re.sub(r"\s+", "_", value)
    return value or fallback


def _doc_source_from_payload(payload: dict) -> str | None:
    source = str(payload.get("source", "")).strip()
    if source:
        return source
    customer = _slug_part(str(payload.get("customer", "")).strip(), "미분류")
    title = _slug_part(str(payload.get("title", "")).strip(), "새_문서")
    return f"{customer}/{title}.md"


def _is_system_doc(path: Path) -> bool:
    return path.name.startswith("READABILITY_") or path.name in {
        "README.md",
        "SIMPLIFY_CHANGELOG.md",
        "SIMPLIFY_VALIDATION_REPORT.md",
        "HK_CUSTOMER_INFO_INDEX.md",
    }


def _is_system_source(source: str) -> bool:
    name = Path(source).name
    return name.startswith("READABILITY_") or name in {
        "README.md",
        "SIMPLIFY_CHANGELOG.md",
        "SIMPLIFY_VALIDATION_REPORT.md",
        "HK_CUSTOMER_INFO_INDEX.md",
    }


def _safe_file_asset_path(rel_path: str) -> Path | None:
    """Validate and resolve an asset's relative path within DOCS_DIR (file mode only)."""
    try:
        resolved = (DOCS_DIR / rel_path).resolve()
        resolved.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    if resolved.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return None
    return resolved


def _safe_asset_path(source: str, asset_path: str) -> Path | None:
    doc_path = _safe_doc_path(source)
    if doc_path is None:
        return None
    decoded_path = urllib.parse.unquote(asset_path).replace("\\", "/")
    try:
        path = (doc_path.parent / decoded_path).resolve()
        path.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if path.exists() and path.is_file():
        return path

    images_dir = doc_path.parent / "images"
    if images_dir.exists():
        original_name = Path(decoded_path).name
        doc_key = re.sub(r"_\d{8}$", "", doc_path.stem)
        name_match = re.match(r"image(?:\s+(\d+))?\.[A-Za-z0-9]+$", original_name, flags=re.I)
        if name_match:
            number = name_match.group(1)
            patterns = (
                [f"{doc_key}_image_{number}_*.png", f"*image_{number}_*.png"]
                if number
                else [f"{doc_key}_image_*.png", f"{doc_key}_image.*", "*image_*.png"]
            )
            candidates = []
            for pattern in patterns:
                candidates = sorted(images_dir.glob(pattern))
                if candidates:
                    break
            if candidates:
                return candidates[0].resolve()
        direct_matches = sorted(images_dir.glob(f"*{Path(original_name).stem.replace(' ', '_')}*"))
        if direct_matches:
            return direct_matches[0].resolve()
    return None


def _asset_target_from_source(source: str, filename: str) -> tuple[str, str] | None:
    source_value = _safe_source_value(source)
    if source_value is None:
        return None
    source_parts = PurePosixPath(source_value).parts
    if len(source_parts) < 2:
        return None
    clean_name = _slug_part(Path(filename or "image.png").name, "image.png")
    if "." not in clean_name:
        clean_name += ".png"
    stem = PurePosixPath(source_value).stem
    unique = f"{int(time.time() * 1000)}_{clean_name}"
    asset_rel = (PurePosixPath(*source_parts[:-1]) / "images" / f"{stem}_{unique}").as_posix()
    markdown_rel = f"images/{stem}_{unique}"
    return asset_rel, markdown_rel


def _safe_posix_parts(value: str) -> tuple[str, ...] | None:
    parts = PurePosixPath(value.replace("\\", "/")).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    if str(value).startswith(("/", "\\")):
        return None
    return parts


def _db_asset_record_for_request(source: str, asset_path: str) -> AssetRecord | None:
    source_parts = _safe_posix_parts(urllib.parse.unquote(source))
    asset_parts = _safe_posix_parts(urllib.parse.unquote(asset_path))
    if source_parts is None or asset_parts is None:
        return None

    doc_parent = PurePosixPath(*source_parts[:-1])
    direct_path = (doc_parent / PurePosixPath(*asset_parts)).as_posix()
    direct = _db_asset_record(direct_path)
    if direct is not None:
        return direct

    requested_name = PurePosixPath(*asset_parts).name
    for path in _db_asset_paths():
        if PurePosixPath(path).name == requested_name:
            return _db_asset_record(path)

    images_prefix = (doc_parent / "images").as_posix().strip("/")
    if images_prefix:
        images_prefix += "/"
    paths = _db_asset_paths(images_prefix)
    if not paths:
        return None

    original_name = PurePosixPath(*asset_parts).name
    doc_key = re.sub(r"_\d{8}$", "", PurePosixPath(*source_parts).stem)
    name_match = re.match(r"image(?:\s+(\d+))?\.[A-Za-z0-9]+$", original_name, flags=re.I)
    if name_match:
        number = name_match.group(1)
        if number:
            patterns = (f"{doc_key}_image_{number}_", f"image_{number}_")
        else:
            patterns = (f"{doc_key}_image_", "image_")
        for path in paths:
            filename = PurePosixPath(path).name
            if any(pattern in filename for pattern in patterns):
                return _db_asset_record(path)

    original_stem = PurePosixPath(original_name).stem.replace(" ", "_")
    for path in paths:
        if original_stem and original_stem in PurePosixPath(path).stem:
            return _db_asset_record(path)
    return None


def docs_index() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for record in _doc_records():
        name = Path(record.source).name
        if name in {"SIMPLIFY_CHANGELOG.md", "SIMPLIFY_VALIDATION_REPORT.md"}:
            continue
        items.append({"source": record.source, "title": record.title, "customer": record.customer, "updatedAt": record.updated_at})
    return items


def folders_index() -> list[dict[str, str | int]]:
    records = _db_folder_records() if SUPABASE_ENABLED else _file_folder_records()
    doc_counts: Counter[str] = Counter(record.customer for record in _doc_records())
    seen = {record.name for record in records}
    for folder in sorted(doc_counts):
        if folder and folder not in seen:
            records.append(FolderRecord(name=folder, sort_order=len(records)))
            seen.add(folder)
    return [
        {"name": record.name, "sortOrder": record.sort_order, "docCount": doc_counts.get(record.name, 0)}
        for record in records
    ]


def create_api_app():
    from fastapi import FastAPI, Query
    from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles

    api_app = FastAPI(title="HK Maintenance Portal")
    if WEB_DIR.exists():
        api_app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")

    @api_app.get("/", response_class=HTMLResponse)
    def home():
        index = WEB_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return HTMLResponse("<h1>HK Maintenance Portal</h1><p>web/index.html is missing.</p>")

    @api_app.get("/healthz")
    def healthz():
        return {"ok": True, "docs_dir": str(DOCS_DIR), "chunks": len(chunks), "llm": MODEL_NAME if USE_LLM else "disabled"}

    @api_app.get("/api/meta")
    def api_meta():
        asset_total_bytes = _db_asset_total_bytes() if SUPABASE_ENABLED else 0
        return {
            "docsDir": str(DOCS_DIR),
            "storage": "supabase" if SUPABASE_ENABLED else "files",
            "chunkCount": len(chunks),
            "docCount": len(docs_index()),
            "assetCount": _db_asset_count() if SUPABASE_ENABLED else len(_file_asset_records()),
            "assetTotalBytes": asset_total_bytes,
            "assetMaxSizeBytes": ASSET_MAX_SIZE_BYTES,
            "llm": MODEL_NAME if USE_LLM else "disabled",
            "claudeDefaultModel": DEFAULT_CLAUDE_MODEL,
        }

    @api_app.get("/api/docs")
    def api_docs():
        return {"docs": docs_index(), "folders": folders_index()}

    @api_app.get("/api/folders")
    def api_folders():
        return {"folders": folders_index()}

    @api_app.post("/api/folder")
    async def api_create_folder(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        name = _safe_folder_name(str(payload.get("name", "")))
        if not name:
            return _json_response({"error": "invalid folder name"}, status_code=400)
        if SUPABASE_ENABLED:
            if _db_folder_exists(name):
                return _json_response({"error": "folder already exists"}, status_code=409)
            _db_create_folder(name)
        else:
            path = (DOCS_DIR / name).resolve()
            try:
                path.relative_to(DOCS_DIR)
            except ValueError:
                return _json_response({"error": "invalid folder name"}, status_code=400)
            if path.exists():
                return _json_response({"error": "folder already exists"}, status_code=409)
            path.mkdir(parents=True)
        return {"folder": name}

    @api_app.put("/api/folder")
    async def api_update_folder(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        old_name = _safe_folder_name(str(payload.get("name", "")))
        new_name = _safe_folder_name(str(payload.get("newName", "")))
        if not old_name or not new_name:
            return _json_response({"error": "invalid folder name"}, status_code=400)
        if old_name == new_name:
            return {"folder": new_name}
        if SUPABASE_ENABLED:
            if not _db_folder_exists(old_name):
                return _json_response({"error": "folder not found"}, status_code=404)
            if _db_folder_exists(new_name):
                return _json_response({"error": "folder already exists"}, status_code=409)
            _db_rename_folder(old_name, new_name)
        else:
            old_path = (DOCS_DIR / old_name).resolve()
            new_path = (DOCS_DIR / new_name).resolve()
            try:
                old_path.relative_to(DOCS_DIR)
                new_path.relative_to(DOCS_DIR)
            except ValueError:
                return _json_response({"error": "invalid folder name"}, status_code=400)
            if not old_path.exists() or not old_path.is_dir():
                return _json_response({"error": "folder not found"}, status_code=404)
            if new_path.exists():
                return _json_response({"error": "folder already exists"}, status_code=409)
            old_path.rename(new_path)
        refresh_index()
        return {"folder": new_name}

    @api_app.put("/api/folders/order")
    async def api_update_folder_order(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        names = [_safe_folder_name(str(name)) for name in payload.get("folders", [])]
        if not names or any(name is None for name in names):
            return _json_response({"error": "invalid folder order"}, status_code=400)
        if SUPABASE_ENABLED:
            _db_update_folder_order([str(name) for name in names])
        return {"folders": folders_index()}

    @api_app.delete("/api/folder")
    async def api_delete_folder(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        name = _safe_folder_name(str(payload.get("name", "")))
        if not name:
            return _json_response({"error": "invalid folder name"}, status_code=400)
        if SUPABASE_ENABLED:
            if not _db_folder_exists(name):
                return _json_response({"error": "folder not found"}, status_code=404)
            if _db_folder_doc_count(name) > 0:
                return _json_response({"error": "folder is not empty"}, status_code=409)
            _db_delete_folder(name)
        else:
            path = (DOCS_DIR / name).resolve()
            try:
                path.relative_to(DOCS_DIR)
            except ValueError:
                return _json_response({"error": "invalid folder name"}, status_code=400)
            if not path.exists() or not path.is_dir():
                return _json_response({"error": "folder not found"}, status_code=404)
            if any(path.iterdir()):
                return _json_response({"error": "folder is not empty"}, status_code=409)
            path.rmdir()
        return {"ok": True, "folder": name}

    @api_app.get("/api/doc")
    def api_doc(source: str = Query(...)):
        if SUPABASE_ENABLED:
            record = _db_doc_record(source)
            if record is None:
                return _json_response({"error": "document not found"}, status_code=404)
            return {"source": record.source, "title": record.title, "content": record.content}
        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        return {"source": source, "title": path.stem, "content": path.read_text(encoding="utf-8", errors="replace")}

    @api_app.post("/api/doc")
    async def api_create_doc(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        source = _doc_source_from_payload(payload)
        path = _safe_new_doc_path(source or "")
        if path is None:
            return _json_response({"error": "invalid document path"}, status_code=400)
        rel = path.relative_to(DOCS_DIR).as_posix()
        if SUPABASE_ENABLED and _db_doc_record(rel) is not None:
            return _json_response({"error": "document already exists"}, status_code=409)
        if not SUPABASE_ENABLED and path.exists():
            return _json_response({"error": "document already exists"}, status_code=409)
        content = str(payload.get("content", "")).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not content:
            title = path.stem.replace("_", " ")
            content = f"# {title}\n\n## 본문\n\n"
        content = content.rstrip() + "\n"
        if SUPABASE_ENABLED:
            parts = Path(rel).parts
            if parts and not _db_folder_exists(parts[0]):
                _db_create_folder(parts[0])
            _db_create_doc(
                DocRecord(
                    source=rel,
                    title=path.stem,
                    customer=parts[0] if parts else "",
                    content=content,
                )
            )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        refresh_index()
        return {"source": rel, "title": path.stem, "content": content}

    @api_app.put("/api/doc")
    async def api_update_doc(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        source = str(payload.get("source", "")).strip()
        if SUPABASE_ENABLED:
            record = _db_doc_record(source)
            if record is None:
                return _json_response({"error": "document not found"}, status_code=404)
            if _is_system_source(source):
                return _json_response({"error": "system document cannot be edited"}, status_code=403)
            content = str(payload.get("content", "")).replace("\r\n", "\n").replace("\r", "\n")
            if not content.strip():
                return _json_response({"error": "content is empty"}, status_code=400)
            content = content.rstrip() + "\n"
            _db_update_doc(source, content)
            refresh_index()
            updated = _db_doc_record(source)
            return {"source": source, "title": record.title, "content": updated.content if updated else content}
        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        if _is_system_doc(path):
            return _json_response({"error": "system document cannot be edited"}, status_code=403)
        content = str(payload.get("content", "")).replace("\r\n", "\n").replace("\r", "\n")
        if not content.strip():
            return _json_response({"error": "content is empty"}, status_code=400)
        path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
        refresh_index()
        return {"source": source, "title": path.stem, "content": path.read_text(encoding="utf-8", errors="replace")}

    @api_app.put("/api/doc/rename")
    async def api_rename_doc(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        source = _safe_source_value(str(payload.get("source", "")))
        folder = _safe_folder_name(str(payload.get("folder", "")))
        title = _slug_part(str(payload.get("title", "")).strip(), "")
        if not source or not folder or not title:
            return _json_response({"error": "invalid document name"}, status_code=400)
        new_source = _safe_source_value(f"{folder}/{title}.md")
        if not new_source:
            return _json_response({"error": "invalid document path"}, status_code=400)
        if _is_system_source(source):
            return _json_response({"error": "system document cannot be renamed"}, status_code=403)
        if SUPABASE_ENABLED:
            record = _db_doc_record(source)
            if record is None:
                return _json_response({"error": "document not found"}, status_code=404)
            existing = _db_doc_record(new_source)
            if existing is not None and new_source != source:
                return _json_response({"error": "document already exists"}, status_code=409)
            if not _db_folder_exists(folder):
                _db_create_folder(folder)
            renamed = _db_rename_doc(source, new_source, Path(new_source).stem, folder)
            refresh_index()
            return {"source": renamed.source, "title": renamed.title, "content": renamed.content}

        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        if _is_system_doc(path):
            return _json_response({"error": "system document cannot be renamed"}, status_code=403)
        new_path = _safe_new_doc_path(new_source)
        if new_path is None:
            return _json_response({"error": "invalid document path"}, status_code=400)
        if new_path.exists() and new_path != path:
            return _json_response({"error": "document already exists"}, status_code=409)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        path.rename(new_path)
        refresh_index()
        rel = new_path.relative_to(DOCS_DIR).as_posix()
        return {"source": rel, "title": new_path.stem, "content": new_path.read_text(encoding="utf-8", errors="replace")}

    @api_app.delete("/api/doc")
    async def api_delete_doc(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        source = str(payload.get("source", "")).strip()
        if SUPABASE_ENABLED:
            record = _db_doc_record(source)
            if record is None:
                return _json_response({"error": "document not found"}, status_code=404)
            if _is_system_source(source):
                return _json_response({"error": "system document cannot be deleted"}, status_code=403)
            _db_cascade_soft_delete_assets(source, record.content)
            _db_soft_delete_doc(source)
            refresh_index()
            return {"ok": True, "source": source}
        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        if _is_system_doc(path):
            return _json_response({"error": "system document cannot be deleted"}, status_code=403)
        path.unlink()
        refresh_index()
        return {"ok": True, "source": source}

    @api_app.get("/api/asset")
    def api_asset(source: str = Query(...), path: str = Query(...)):
        if SUPABASE_ENABLED:
            asset_record = _db_asset_record_for_request(source, path)
            if asset_record is None:
                return _json_response({"error": "asset not found"}, status_code=404)
            return Response(content=asset_record.content, media_type=asset_record.mime_type)
        asset = _safe_asset_path(source, path)
        if asset is None:
            return _json_response({"error": "asset not found"}, status_code=404)
        return FileResponse(asset)

    @api_app.post("/api/asset")
    async def api_upload_asset(request: Request):
        form = await request.form()
        source = str(form.get("source", "")).strip()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "filename"):
            return _json_response({"error": "file is required"}, status_code=400)
        target = _asset_target_from_source(source, str(upload.filename))
        if target is None:
            return _json_response({"error": "valid document source is required"}, status_code=400)
        asset_rel, markdown_rel = target
        content = await upload.read()
        if not content:
            return _json_response({"error": "file is empty"}, status_code=400)
        if len(content) > ASSET_MAX_SIZE_BYTES:
            limit_mb = ASSET_MAX_SIZE_MB if ASSET_MAX_SIZE_MB == int(ASSET_MAX_SIZE_MB) else ASSET_MAX_SIZE_MB
            return _json_response({"error": f"파일이 너무 큽니다. 최대 {int(limit_mb) if limit_mb == int(limit_mb) else limit_mb}MB까지 업로드할 수 있습니다."}, status_code=413)
        mime_type = getattr(upload, "content_type", None) or mimetypes.guess_type(str(upload.filename))[0] or "application/octet-stream"
        if not mime_type.startswith("image/"):
            return _json_response({"error": "only image uploads are supported"}, status_code=400)
        if SUPABASE_ENABLED:
            _db_upsert_asset(AssetRecord(path=asset_rel, mime_type=mime_type, content=content))
        else:
            path = (DOCS_DIR / asset_rel).resolve()
            try:
                path.relative_to(DOCS_DIR)
            except ValueError:
                return _json_response({"error": "invalid asset path"}, status_code=400)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        url = "/api/asset?source=" + urllib.parse.quote(source) + "&path=" + urllib.parse.quote(markdown_rel)
        return {"path": markdown_rel, "url": url}

    @api_app.delete("/api/asset")
    async def api_delete_asset(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        path = str(payload.get("path", "")).strip()
        if not path:
            return _json_response({"error": "path is required"}, status_code=400)
        if SUPABASE_ENABLED:
            if _db_asset_record(path) is None:
                return _json_response({"error": "asset not found"}, status_code=404)
            _db_soft_delete_asset(path)
            return {"ok": True, "path": path}
        asset_file = _safe_file_asset_path(path)
        if asset_file is None:
            return _json_response({"error": "asset not found"}, status_code=404)
        asset_file.unlink()
        return {"ok": True, "path": path}

    @api_app.get("/api/trash")
    def api_trash():
        if not SUPABASE_ENABLED:
            return {"docs": [], "assets": []}
        return _db_trash_records()

    @api_app.post("/api/trash/restore")
    async def api_trash_restore(request: Request):
        if not SUPABASE_ENABLED:
            return _json_response({"error": "trash requires Supabase storage"}, status_code=400)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        item_type = str(payload.get("type", "")).strip()
        key = str(payload.get("key", "")).strip()
        if not key:
            return _json_response({"error": "key is required"}, status_code=400)
        if item_type == "doc":
            _db_restore_doc(key)
            refresh_index()
        elif item_type == "asset":
            _db_restore_asset(key)
        else:
            return _json_response({"error": "type must be 'doc' or 'asset'"}, status_code=400)
        return {"ok": True, "type": item_type, "key": key}

    @api_app.delete("/api/trash")
    async def api_trash_delete(request: Request):
        if not SUPABASE_ENABLED:
            return _json_response({"error": "trash requires Supabase storage"}, status_code=400)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        item_type = str(payload.get("type", "")).strip()
        key = str(payload.get("key", "")).strip()
        if item_type == "all":
            with _db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"delete from {SUPABASE_DOCS_TABLE} where deleted_at is not null")
                    cur.execute(f"delete from {SUPABASE_ASSETS_TABLE} where deleted_at is not null")
            refresh_index()
            return {"ok": True}
        if not key:
            return _json_response({"error": "key is required"}, status_code=400)
        if item_type == "doc":
            _db_permanent_delete_doc(key)
            refresh_index()
        elif item_type == "asset":
            _db_permanent_delete_asset(key)
        else:
            return _json_response({"error": "type must be 'doc', 'asset', or 'all'"}, status_code=400)
        return {"ok": True, "type": item_type, "key": key}

    @api_app.get("/api/search")
    def api_search(q: str = Query(..., min_length=1), top_k: int = Query(5, ge=1, le=10)):
        results, _context = retrieve(q, top_k)
        return {
            "query": q,
            "answer": source_based_answer(q, results),
            "results": [
                {
                    "source": chunk.source,
                    "title": chunk.title,
                    "score": round(score, 4),
                    "snippet": re.sub(r"\s+", " ", chunk.text).strip()[:700],
                }
                for chunk, score in results
            ],
        }

    @api_app.post("/api/chat")
    async def api_chat(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        query = str(payload.get("query", "")).strip()
        top_k = max(1, min(int(payload.get("topK", 5)), 10))
        use_llm = bool(payload.get("useLlm", False))
        if not query:
            return _json_response({"error": "query is required"}, status_code=400)
        provider = str(payload.get("provider", "local")).strip().lower()
        if provider == "claude":
            response = claude_answer(
                query,
                top_k,
                str(payload.get("apiKey", "")),
                str(payload.get("model", DEFAULT_CLAUDE_MODEL)),
            )
        elif provider == "quick":
            response = immediate_answer(query, top_k)
        else:
            response = llm_answer(query, top_k) if USE_LLM else immediate_answer(query, top_k)
        return {"query": query, "answer": response}

    @api_app.get("/robots.txt")
    def robots_txt():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    # Existing Gradio chatbot is intentionally not mounted in the portal.
    # if demo is not None:
    #     api_app = gr.mount_gradio_app(api_app, demo, path="/chat")
    return api_app


app = create_api_app() if demo is not None else None


if __name__ == "__main__":
    if demo is None:
        raise SystemExit("gradio가 설치되어 있지 않습니다. `pip install -r requirements.txt`를 실행하세요.")
    if app is None:
        demo.launch(ssr_mode=False)
    else:
        import uvicorn

        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("APP_PORT", "7860")))
